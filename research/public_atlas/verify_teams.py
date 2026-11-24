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

    site = json.loads((recount.SITE / 'teams.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest()
    for season, teams in site['seasons'].items():
        table = saved.loc[int(season)]
        assert len(teams) == len(table)
        for team in teams:
            row = table.loc[team['id']]
            assert team['shots'] == row.shots and np.isclose(team['offence_quality']['estimate'], row.offence_quality_estimate, atol=.006)
            assert np.isclose(team['defence_making']['estimate'], row.defence_making_estimate, atol=.006) and np.isclose(team['net'], row.net, atol=.006)
    starts = pd.read_csv(RESULTS / 'teams/possession_starts.csv')
    assert np.allclose(starts.per_100, 100 * starts.points / starts.possessions) and starts.share.between(0, 1).all()
    assert np.allclose(starts.groupby(['season', 'side', 'team_id']).share.sum(), 1)
    certificate = dict(shots=len(joined), team_seasons=checked, split_half_shot_quality=round(float(mine), 3),
                       saved_split_half=repeats.split_half.round(3).to_dict(), manifestSha256=manifest_digest())
    (RESULTS / 'teams/verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('TEAMS_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
