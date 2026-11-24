"""Check the expected points model and the team study against raw shot rows."""
import json

import numpy as np
import pandas as pd

import recount
from fetch import manifest_digest

DERIVED = recount.ROOT / 'research/data/public_wnba/derived'
RESULTS = recount.RESULTS


def raw_shots(years):
    """Points, shooting team and defending team for every raw shot row, read without the build."""
    frames = []
    for year in years:
        raw = pd.read_csv(recount.RAW / f'shots_{year}.csv', usecols=['game_id', 'team_id', 'score_value'], low_memory=False)
        games = pd.read_csv(recount.RAW / f'wnba_schedule_{year}.csv', usecols=['game_id', 'home_id', 'away_id', 'season_type', 'game_date'], low_memory=False)
        raw['source_row'] = raw.index + 2
        raw = raw.merge(games, on='game_id', how='left').assign(season=year)
        raw['defence'] = np.where(raw.team_id.eq(raw.home_id), raw.away_id, raw.home_id)
        frames.append(raw)
    return pd.concat(frames)


def four_measures(mine, rest):
    """Observed measures for one set of shots against the rest of the league, written apart from the study code."""
    level = rest.points.sum() / rest.xp.sum()
    quality = 100 * (mine.xp.mean() - rest.xp.mean())
    making = 100 * (mine.points.sum() - level * mine.xp.sum()) / len(mine)
    return quality, making


def main():
    shots = pd.read_csv(DERIVED / 'expected_points.csv.gz')
    raw = raw_shots(sorted(shots.season.unique()))
    joined = shots.merge(raw, on=['season', 'source_row'], how='left', validate='one_to_one', suffixes=('', '_raw'))
    assert joined.game_id.eq(joined.game_id_raw).all() and joined.points.eq(joined.score_value).all()
    assert joined.team_id.eq(joined.team_id_raw).all() and joined.defence_id.eq(joined.defence).all()
    assert joined.scope.eq(joined.season_type.map({2: 'regular', 3: 'playoffs'})).all()
    assert joined.xp.between(0, 3).all() and joined.xp_distance.between(0, 3).all() and joined.xp_variance.ge(0).all()
    scores = pd.read_csv(RESULTS / 'expected_points/scores.csv')
    for row in scores.itertuples():
        part = joined if row.scope == 'both' else joined[joined.scope.eq(row.scope)]
        assert len(part) == row.attempts and np.isclose(row.rmse, np.sqrt(np.mean((part[row.forecast] - part.points) ** 2)))
        assert np.isclose(row.rmse_compared, np.sqrt(np.mean((part[row.compared_with] - part.points) ** 2)))

    regular = joined[joined.scope.eq('regular') & joined.team_id.ne(0)]
    saved = pd.read_csv(RESULTS / 'teams/team_seasons.csv').set_index(['season', 'team_id'])
    checked = 0
    for (season, team), row in saved.iterrows():
        league = regular[regular.season.eq(season)]
        for column, prefix in [('team_id', 'offence'), ('defence_id', 'defence')]:
            own = league[column].eq(team)
            quality, making = four_measures(league[own], league[~own])
            assert np.isclose(row[f'{prefix}_quality'], quality) and np.isclose(row[f'{prefix}_making'], making), (season, team, prefix)
        assert row.shots == league.team_id.eq(team).sum() and row.shots_against == league.defence_id.eq(team).sum()
        for name in ('offence_quality', 'offence_making', 'defence_quality', 'defence_making'):
            assert row[f'{name}_low'] <= row[f'{name}_estimate'] <= row[f'{name}_high']
            assert abs(row[f'{name}_estimate']) <= abs(row[f'{name}_observed']) + 1e-9
        checked += 1

    ordered = regular.sort_values(['season', 'game_date', 'game_id'])
    halves = []
    for (season, team), mine in ordered.groupby(['season', 'team_id']):
        games = mine.game_id.drop_duplicates().reset_index(drop=True)
        even = mine.game_id.isin(games[::2])
        rest = regular[regular.season.eq(season) & regular.team_id.ne(team)]
        halves.append((four_measures(mine[even], rest)[0], four_measures(mine[~even], rest)[0]))
    first, second = np.array(halves).T
    repeats = pd.read_csv(RESULTS / 'teams/repeatability.csv').set_index('measure')
    mine = np.corrcoef(first, second)[0, 1]
    assert abs(mine - repeats.loc['offence_quality', 'split_half']) < .02, mine

    # Opponent adjustment for one season, solved as least squares with one extra row per prior.
    year = regular[regular.season.eq(2026)]
    level = year.points.sum() / year.xp.sum()
    games = year.groupby(['game_id', 'team_id', 'defence_id']).agg(n=('points', 'size'), points=('points', 'sum'), expected=('xp', 'sum')).reset_index()
    teams = sorted(set(games.team_id) | set(games.defence_id))
    spreads = json.loads((recount.SITE / 'teams.json').read_bytes())['spread']
    noise = np.var(100 * (year.points - level * year.xp))
    rows, target = [], []
    for game in games.itertuples():
        line = np.zeros(2 * len(teams))
        line[teams.index(game.team_id)] = line[len(teams) + teams.index(game.defence_id)] = np.sqrt(game.n / noise)
        rows.append(line)
        target.append(np.sqrt(game.n / noise) * 100 * (game.points - level * game.expected) / game.n)
    prior = np.diag(np.repeat([1 / spreads['offence_making']['spread'], 1 / spreads['defence_making']['spread']], len(teams)))
    solution = np.linalg.lstsq(np.vstack([np.array(rows), prior]), np.concatenate([target, np.zeros(2 * len(teams))]), rcond=None)[0]
    for k, team in enumerate(teams):
        assert abs(solution[k] - saved.loc[(2026, team), 'offence_making_adjusted']) < 1e-6, team
        assert abs(solution[len(teams) + k] - saved.loc[(2026, team), 'defence_making_adjusted']) < 1e-6, team
    shift = pd.read_csv(RESULTS / 'teams/opponent_adjustment.csv')
    assert shift.correlation.min() > .9

    factors = pd.read_csv(RESULTS / 'teams/possession_factors.csv')
    turns = pd.read_csv(DERIVED / 'league_turns/turns_2026.csv.gz')
    turns = turns[turns.scope.eq('regular')]
    assert abs(factors[factors.season.eq(2026)].possessions.sum() - len(turns)) <= .01 * len(turns)
    latest = factors[factors.season.eq(2026)]
    assert np.isclose(np.average(latest.offence_points, weights=latest.possessions), 100 * turns.points.sum() / len(turns), atol=.5)
    for name in ('offence_points', 'defence_points', 'offence_turnovers', 'defence_turnovers'):
        assert (factors[f'{name}_low'] <= factors[f'{name}_estimate']).all() and (factors[f'{name}_estimate'] <= factors[f'{name}_high']).all()
        assert (factors[f'{name}_estimate'].abs() <= (factors[name] - factors[f'{name}_league']).abs() + 1e-9).all()
    for name in ('offence_points', 'defence_points', 'defence_turnovers'):
        assert (factors[f'{name}_adjusted_low'] <= factors[f'{name}_adjusted']).all() and (factors[f'{name}_adjusted'] <= factors[f'{name}_adjusted_high']).all()
        assert np.corrcoef(factors[f'{name}_estimate'], factors[f'{name}_adjusted'])[0, 1] > .9
        assert (factors[f'{name}_adjusted'] - factors[f'{name}_estimate']).abs().max() < 2.5 * factors[f'{name}_estimate'].abs().max()
    assert np.allclose(factors.net, factors.offence_points_adjusted - factors.defence_points_adjusted)
    drawn = json.loads((recount.SITE / 'team-possessions.json').read_bytes())
    assert drawn['manifestSha256'] == manifest_digest() and sum(len(v) for v in drawn['seasons'].values()) == len(factors)

    counted, _, _ = recount.espn_season(2026)
    counted = counted[counted.phase.isin(recount.PHASES)]
    defender = np.where(counted.team_id.eq(counted.home_id), counted.away_id, counted.home_id)
    by_defender = counted.groupby(defender).size()
    allowed = pd.DataFrame(json.loads((recount.SITE / 'against-2026.json').read_bytes())['rows']).groupby(1)[5].sum()
    assert allowed.drop(0, errors='ignore').to_dict() == {int(team): int(n) for team, n in by_defender.items()}
    for name in ('2026', 'all'):
        taken, against = (json.loads((recount.SITE / f'{prefix}{name}.json').read_bytes())['rows'] for prefix in ('', 'against-'))
        assert [sum(row[i] for row in taken) for i in (5, 6, 7)] == [sum(row[i] for row in against) for i in (5, 6, 7)]

    site = json.loads((recount.SITE / 'teams.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest()
    for season, teams in site['seasons'].items():
        table = saved.loc[int(season)]
        assert len(teams) == len(table)
        for team in teams:
            row = table.loc[team['id']]
            assert team['shots'] == row.shots and np.isclose(team['offence_quality']['estimate'], row.offence_quality_adjusted, atol=.006)
            assert np.isclose(team['defence_making']['estimate'], row.defence_making_adjusted, atol=.006) and np.isclose(team['net'], row.net, atol=.006)
    starts = pd.read_csv(RESULTS / 'teams/possession_starts.csv')
    assert np.allclose(starts.per_100, 100 * starts.points / starts.possessions) and starts.share.between(0, 1).all()
    assert np.allclose(starts.groupby(['season', 'side', 'team_id']).share.sum(), 1)
    certificate = dict(shots=len(joined), team_seasons=checked, split_half_shot_quality=round(float(mine), 3),
                       saved_split_half=repeats.split_half.round(3).to_dict(), manifestSha256=manifest_digest())
    (RESULTS / 'teams/verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('TEAMS_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
