"""Which team tendencies repeat: the quality of shots it takes and allows, and how those shots are made.

Shot quality is the league expected points of the shots. Shot making is the
points scored above that expectation. Both are measured for a team's own shots
and for its opponents' shots, in points per 100 shots against the league.
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from build import DERIVED, RESULTS, SITE, write_json
from fetch import RAW, manifest_digest

OUT = RESULTS / 'teams'
SEED = 20261123
DRAWS = 1000
MEASURES = {'offence_quality': 'Shot quality taken', 'offence_making': 'Shot making', 'defence_quality': 'Shot quality allowed', 'defence_making': 'Shot making allowed'}
STARTS = ('Steal', 'Defensive rebound', 'Opponent turnover', 'Opponent basket', 'Opponent free throw')


def game_table(shots):
    """Shots, points and expected points for each team in each game, on offence and on defence."""
    def side(column, prefix):
        table = shots.groupby(['season', 'game_id', column]).agg(shots=('points', 'size'), points=('points', 'sum'), expected=('xp', 'sum'))
        return table.rename_axis(['season', 'game_id', 'team_id']).add_prefix(prefix)
    table = side('team_id', 'off_').join(side('defence_id', 'def_'), how='outer').fillna(0).reset_index()
    league = shots.groupby('season').agg(league_points=('points', 'sum'), league_expected=('xp', 'sum'), league_shots=('points', 'size'))
    order = shots.groupby(['season', 'game_id']).game_date.first().rename('game_date')
    return table.join(league, on='season').join(order, on=['season', 'game_id'])


def measures(sums, whole=None):
    """Four measures in points per 100 shots against the rest of the league, from summed game rows.

    The rest of the league leaves out all of the team's shots. Pass the team's whole season in `whole` when `sums` holds only part of it.
    """
    whole = sums if whole is None else whole
    result = {}
    for side in ('off', 'def'):
        shots, points, expected = sums[f'{side}_shots'], sums[f'{side}_points'], sums[f'{side}_expected']
        rest_expected = sums['league_expected'] - whole[f'{side}_expected']
        level = (sums['league_points'] - whole[f'{side}_points']) / rest_expected
        name = 'offence' if side == 'off' else 'defence'
        result[f'{name}_quality'] = 100 * (expected / shots - rest_expected / (sums['league_shots'] - whole[f'{side}_shots']))
        result[f'{name}_making'] = 100 * (points - expected * level) / shots
    return result


def team_seasons(games):
    """Observed measures and their game to game noise for every team season."""
    rng = np.random.default_rng(SEED)
    rows = []
    columns = ['off_shots', 'off_points', 'off_expected', 'def_shots', 'def_points', 'def_expected']
    for (season, team), part in games.groupby(['season', 'team_id']):
        totals = part[columns].to_numpy()
        fixed = {key: part[key].iloc[0] for key in ('league_points', 'league_expected', 'league_shots')}
        observed = measures({**dict(zip(columns, totals.sum(axis=0))), **fixed})
        weights = rng.multinomial(len(part), np.full(len(part), 1 / len(part)), size=DRAWS)
        draws = measures({**dict(zip(columns, (weights @ totals).T)), **fixed}, dict(zip(columns, totals.sum(axis=0))))
        row = dict(season=season, team_id=team, games=len(part), shots=int(totals[:, 0].sum()), shots_against=int(totals[:, 3].sum()))
        for name in MEASURES:
            row[name] = float(observed[name])
            row[f'{name}_noise'] = float(np.var(draws[name]))
        rows.append(row)
    return pd.DataFrame(rows)


def pooled(table):
    """Pull each observed measure toward the league in proportion to its noise."""
    spread = {}
    for name in MEASURES:
        centred = table[name] - table.groupby('season')[name].transform('mean')
        noise = table[f'{name}_noise'].to_numpy()
        tau2 = minimize_scalar(lambda t: float(np.sum(np.log(t + noise) + centred.to_numpy() ** 2 / (t + noise))),
                               bounds=(0, 100), method='bounded', options={'xatol': 1e-8}).x
        table[f'{name}_observed'] = centred
        weight = tau2 / (tau2 + table[f'{name}_noise'])
        sd = np.sqrt(weight * table[f'{name}_noise'])
        table[f'{name}_estimate'] = weight * centred
        table[f'{name}_low'] = weight * centred - 1.96 * sd
        table[f'{name}_high'] = weight * centred + 1.96 * sd
        spread[name] = dict(spread=float(np.sqrt(tau2)), typical_noise=float(np.sqrt(table[f'{name}_noise'].median())),
                            share_kept=float(weight.median()))
    return table, spread


def adjusted(shots, spread):
    """Estimate every offence and every defence together from single games, so each is judged against the opponents it met.

    A game value is the offence's effect plus the defence's effect plus noise that shrinks with the number of shots.
    Effects have normal priors centred on the league with the spreads found by pooling. The posterior is exact.
    """
    rows = []
    for season, part in shots.groupby('season'):
        level, centre = part.points.sum() / part.xp.sum(), part.xp.mean()
        games = part.groupby(['game_id', 'team_id', 'defence_id']).agg(n=('points', 'size'), points=('points', 'sum'), expected=('xp', 'sum')).reset_index()
        teams = np.sort(pd.unique(games[['team_id', 'defence_id']].to_numpy().ravel()))
        place = {team: k for k, team in enumerate(teams)}
        design = np.zeros((len(games), 2 * len(teams)))
        design[np.arange(len(games)), games.team_id.map(place)] = 1
        design[np.arange(len(games)), games.defence_id.map(place) + len(teams)] = 1
        targets = {'quality': 100 * (games.expected / games.n - centre), 'making': 100 * (games.points - level * games.expected) / games.n}
        per_shot = {'quality': np.var(100 * part.xp), 'making': np.var(100 * (part.points - level * part.xp))}
        found = {team: dict(season=season, team_id=team) for team in teams}
        for kind, target in targets.items():
            prior = np.repeat([1 / spread[f'offence_{kind}']['spread'] ** 2, 1 / spread[f'defence_{kind}']['spread'] ** 2], len(teams))
            weight = (games.n / per_shot[kind]).to_numpy()
            covariance = np.linalg.inv(design.T @ (design * weight[:, None]) + np.diag(prior))
            mean = covariance @ (design.T @ (weight * target.to_numpy()))
            sd = np.sqrt(np.diag(covariance))
            for team, k in place.items():
                for side, at in [('offence', k), ('defence', k + len(teams))]:
                    found[team].update({f'{side}_{kind}_adjusted': mean[at], f'{side}_{kind}_adjusted_low': mean[at] - 1.96 * sd[at],
                                        f'{side}_{kind}_adjusted_high': mean[at] + 1.96 * sd[at]})
        rows += list(found.values())
    return pd.DataFrame(rows)


def correlation(a, b):
    rng = np.random.default_rng(SEED)
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    picks = rng.integers(0, len(a), size=(2000, len(a)))
    draws = [np.corrcoef(a[i], b[i])[0, 1] for i in picks]
    low, high = np.quantile(draws, [.025, .975])
    return float(np.corrcoef(a, b)[0, 1]), float(low), float(high)


def repeatability(games, table):
    """Does a measure in one set of games show up again in another set?"""
    ordered = games.sort_values(['season', 'team_id', 'game_date', 'game_id'])
    ordered['half'] = ordered.groupby(['season', 'team_id']).cumcount() % 2
    columns = ['off_shots', 'off_points', 'off_expected', 'def_shots', 'def_points', 'def_expected']
    halves = ordered.groupby(['season', 'team_id', 'half'])[columns].sum().join(
        ordered.groupby(['season', 'team_id'])[['league_points', 'league_expected', 'league_shots']].first())
    season_sums = ordered.groupby(['season', 'team_id'])[columns].sum()
    whole = halves[[]].join(season_sums)
    split = pd.DataFrame(measures(halves, whole)).unstack('half')
    following = table.assign(season=table.season - 1).set_index(['season', 'team_id'])
    current = table.set_index(['season', 'team_id'])
    pairs = current.join(following, rsuffix='_next', how='inner')
    rows = []
    for name, label in MEASURES.items():
        within = correlation(split[(name, 0)].to_numpy(), split[(name, 1)].to_numpy())
        centre = lambda column: (pairs[column] - pairs.groupby(level='season')[column].transform('mean')).to_numpy()
        across = correlation(centre(name), centre(f'{name}_next'))
        rows.append(dict(measure=name, label=label, team_seasons=len(split), split_half=within[0], split_half_low=within[1], split_half_high=within[2],
                         season_pairs=len(pairs), next_season=across[0], next_season_low=across[1], next_season_high=across[2]))
    return pd.DataFrame(rows)


def possession_starts(names):
    """Points per 100 possessions by how the possession started, for each team and against it."""
    link = pd.read_csv(RAW / 'wnba_team_crosswalk_2026.csv').dropna(subset=['wnba_team_id', 'espn_team_id']).drop_duplicates('wnba_team_id')
    link = link.set_index('wnba_team_id').espn_team_id
    frames = []
    for year in sorted(names.season.unique()):
        turns = pd.read_csv(DERIVED / 'league_turns' / f'turns_{year}.csv.gz')
        states = pd.read_csv(DERIVED / 'league_turns' / f'states_{year}.csv.gz', usecols=['game_id', 'period', 'turn', 'history_length', 'situation'])
        starts = states[states.history_length.eq(1)].drop(columns='history_length')
        turns = turns[turns.scope.eq('regular')].merge(starts, on=['game_id', 'period', 'turn'], validate='one_to_one')
        both = turns.groupby('game_id').team.unique()
        both = both[both.str.len().eq(2)]
        turns = turns[turns.game_id.isin(both.index)]
        other = turns.game_id.map(both.map(lambda pair: {pair[0]: pair[1], pair[1]: pair[0]}))
        turns['against'] = [pair[team] for pair, team in zip(other, turns.team)]
        frames.append(turns)
    turns = pd.concat(frames, ignore_index=True)
    league = turns.groupby(['season', 'situation']).points.agg(league_points='sum', league_possessions='size')
    rows = []
    for side, column in [('offence', 'team'), ('defence', 'against')]:
        table = turns.groupby(['season', column, 'situation']).points.agg(points='sum', possessions='size', spread='var').reset_index().rename(columns={column: 'wnba_team_id'})
        table = table.join(league, on=['season', 'situation'])
        table['side'] = side
        rows.append(table)
    table = pd.concat(rows, ignore_index=True)
    table['team_id'] = table.wnba_team_id.map(link)
    table = table.dropna(subset=['team_id']).astype({'team_id': 'int64'})
    table['per_100'] = 100 * table.points / table.possessions
    table['league_per_100'] = 100 * (table.league_points - table.points) / (table.league_possessions - table.possessions)
    table['margin_of_error'] = 196 * np.sqrt(table.spread / table.possessions)
    totals = table.groupby(['season', 'side', 'team_id']).possessions.transform('sum')
    table['share'] = table.possessions / totals
    return table.drop(columns=['wnba_team_id', 'league_points', 'league_possessions', 'spread'])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots = pd.read_csv(DERIVED / 'expected_points.csv.gz')
    shots = shots[shots.scope.eq('regular') & shots.team_id.ne(0)]
    games = game_table(shots)
    table, spread = pooled(team_seasons(games))
    names = pd.concat([pd.DataFrame([dict(season=year, team_id=int(team), team=name)
                                     for team, name in json.loads((SITE / f'{year}.json').read_bytes())['teams'].items()])
                       for year in sorted(table.season.unique())])
    table = table.merge(names, on=['season', 'team_id'], how='left', validate='one_to_one')
    assert table.team.notna().all()
    table = table.merge(adjusted(shots, spread), on=['season', 'team_id'], validate='one_to_one')
    table['net'] = table.offence_quality_adjusted + table.offence_making_adjusted - table.defence_quality_adjusted - table.defence_making_adjusted
    shift = pd.DataFrame([dict(measure=name, label=label, correlation=float(np.corrcoef(table[f'{name}_estimate'], table[f'{name}_adjusted'])[0, 1]),
                               largest_change=float((table[f'{name}_adjusted'] - table[f'{name}_estimate']).abs().max()),
                               typical_change=float((table[f'{name}_adjusted'] - table[f'{name}_estimate']).abs().median())) for name, label in MEASURES.items()])
    shift.to_csv(OUT / 'opponent_adjustment.csv', index=False)
    repeats = repeatability(games, table)
    starts = possession_starts(table)
    table.to_csv(OUT / 'team_seasons.csv', index=False)
    repeats.to_csv(OUT / 'repeatability.csv', index=False)
    starts.to_csv(OUT / 'possession_starts.csv', index=False)

    def line(row):
        return (f"| {row.label} | {row.split_half:.2f} | {row.split_half_low:.2f} to {row.split_half_high:.2f} | "
                f"{row.next_season:.2f} | {row.next_season_low:.2f} to {row.next_season_high:.2f} | {spread[row.measure]['spread']:.1f} | {100 * spread[row.measure]['share_kept']:.0f}% |")
    best = repeats.sort_values('split_half', ascending=False)
    lines = ['# Which team tendencies repeat', '',
             f"Across {len(table)} team seasons from 2016 to 2026, {best.iloc[0].label.lower()} is the most repeatable of the four measures "
             f"(correlation {best.iloc[0].split_half:.2f} between alternating games of the same season) and {best.iloc[-1].label.lower()} is the least ({best.iloc[-1].split_half:.2f}).", '',
             'Shot quality is the league expected points of the shots a team takes or allows. Shot making is the points scored above that expectation. All four are in points per 100 shots against the rest of the league in that regular season.', '',
             '| Measure | Same season, alternating games | 95% interval | Following season | 95% interval | Spread between teams | Share of an observed gap kept after pooling |',
             '| --- | ---: | --- | ---: | --- | ---: | ---: |', *[line(row) for row in repeats.itertuples()], '',
             'A higher correlation means the tendency repeated across alternating games. A value near zero indicates little agreement between the two halves. '
             'These are descriptions of past seasons. They do not show that changing a scheme would move a measure.', '',
             '## Adjusting for opponents', '',
             'The values shown on the site come from a model that estimates every offence and every defence together from single games, so a team that met strong defences is not marked down for it. '
             f"The schedule is close to balanced, so the adjustment is small. Across the four measures the adjusted and unadjusted values correlate at {shift.correlation.min():.3f} or more, "
             f"and the largest change for any team season is {shift.largest_change.max():.1f} points per 100 shots.", '',
             '## Method', '',
             'The league expectation comes from `expected_points.py` and uses no team or player. Before a team is compared, the expectation is scaled so that the rest of the league scores exactly what is expected that season. '
             f'Noise for each team season comes from drawing its games again {DRAWS:,} times. Each measure is then pulled toward the league average in proportion to that noise, and the 95% interval is the range of the resulting normal posterior. '
             'The same season check splits each team season into alternating games by date. The following season check pairs a franchise with its next season. Intervals for the correlations resample team seasons.', '',
             'Possession starts use the play by play reconstruction of complete possessions in regular season games. Each start is compared with the rest of the league, and the margin of error is 1.96 standard errors of the mean.', '',
             'The opponent adjustment treats a game value as the offence effect plus the defence effect plus noise that shrinks with the number of shots. Both effects have normal priors centred on the league, with the spreads found by pooling, and the posterior is exact.', '',
             '[Team seasons](team_seasons.csv) · [Repeatability](repeatability.csv) · [Opponent adjustment](opponent_adjustment.csv) · [Possession starts](possession_starts.csv) · [Whole possessions](POSSESSIONS.md)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

    def record(row):
        item = dict(id=int(row.team_id), name=row.team, games=int(row.games), shots=int(row.shots), shotsAgainst=int(row.shots_against), net=round(float(row.net), 2))
        for name in MEASURES:
            item[name] = dict(observed=round(float(row[f'{name}_observed']), 2), estimate=round(float(row[f'{name}_adjusted']), 2),
                              low=round(float(row[f'{name}_adjusted_low']), 2), high=round(float(row[f'{name}_adjusted_high']), 2))
        mine = starts[starts.season.eq(row.season) & starts.team_id.eq(row.team_id)]
        item['starts'] = {side: [dict(start=r.situation, possessions=int(r.possessions), share=round(float(r.share), 4), per100=round(float(r.per_100), 1),
                                      league=round(float(r.league_per_100), 1), margin=round(float(r.margin_of_error), 1))
                                 for r in mine[mine.side.eq(side)].set_index('situation').reindex(STARTS).dropna(subset=['possessions']).reset_index().itertuples()]
                          for side in ('offence', 'defence')}
        return item
    site = dict(manifestSha256=manifest_digest(), measures=MEASURES, spread=spread, repeatability=json.loads(repeats.to_json(orient='records')),
                seasons={str(year): [record(row) for _, row in frame.sort_values('net', ascending=False).iterrows()] for year, frame in table.groupby('season')})
    write_json(SITE / 'teams.json', site)
    print('TEAM_VALUE', len(table), 'team seasons', {row.measure: round(row.split_half, 3) for row in repeats.itertuples()}, flush=True)


if __name__ == '__main__':
    main()
