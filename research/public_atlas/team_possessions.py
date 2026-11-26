"""Beyond shots: what each team does with whole possessions, and what it allows.

For every regular season possession in the play by play reconstruction, the
study counts points, turnovers, offensive rebounds after misses and points from
free throws. Each team is compared with the rest of the league, small samples
are pulled toward average, and alternating games show which numbers repeat.
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from build import DERIVED, RESULTS, SITE, write_json
from fetch import RAW, manifest_digest

OUT = RESULTS / 'teams'
TURNS = DERIVED / 'league_turns'
SEASONS = range(2016, 2027)
SEED = 20261124
DRAWS = 1000
COUNTS = ['possessions', 'points', 'turnovers', 'misses', 'boards', 'field_goal_points']
RATES = {'points': ('points', 'possessions'), 'turnovers': ('turnovers', 'possessions'), 'rebounds': ('boards', 'misses'), 'free_throws': ('free_throw_points', 'possessions')}
LABELS = {'offence_points': 'Points per 100 possessions', 'offence_turnovers': 'Turnovers per 100 possessions', 'offence_rebounds': 'Offensive rebounds per 100 misses',
          'offence_free_throws': 'Free throw points per 100 possessions', 'defence_points': 'Points allowed per 100 possessions',
          'defence_turnovers': 'Turnovers forced per 100 possessions', 'defence_rebounds': 'Offensive rebounds allowed per 100 misses',
          'defence_free_throws': 'Free throw points allowed per 100 possessions'}


def game_counts():
    """Possession counts for each team in each game, with its own possessions and its opponent's."""
    link = pd.read_csv(RAW / 'wnba_team_crosswalk_2026.csv').dropna(subset=['wnba_team_id', 'espn_team_id']).drop_duplicates('wnba_team_id')
    link = link.set_index('wnba_team_id').espn_team_id.astype('int64')
    frames = []
    for year in SEASONS:
        key = ['game_id', 'period', 'turn']
        turns = pd.read_csv(TURNS / f'turns_{year}.csv.gz')
        turns = turns[turns.scope.eq('regular')]
        shots = pd.read_csv(TURNS / f'shots_{year}.csv.gz', usecols=key + ['points']).groupby(key).points.sum().rename('field_goal_points')
        misses = pd.read_csv(TURNS / f'misses_{year}.csv.gz', usecols=key + ['off_rebound']).groupby(key).off_rebound.agg(misses='size', boards='sum')
        turns = turns.join(shots, on=key).join(misses, on=key).fillna({'field_goal_points': 0, 'misses': 0, 'boards': 0})
        turns['possessions'] = 1
        turns['turnovers'] = turns.end_reason.eq('turnover').astype(int)
        pairs = turns.groupby('game_id').team.unique()
        pairs = pairs[pairs.str.len().eq(2)]
        turns = turns[turns.game_id.isin(pairs.index)]
        other = {game: {a: b, b: a} for game, (a, b) in pairs.items()}
        turns['opponent'] = [other[game][team] for game, team in zip(turns.game_id, turns.team)]
        own = turns.groupby(['game_id', 'team'])[COUNTS].sum().rename_axis(['game_id', 'team_id']).add_prefix('off_')
        against = turns.groupby(['game_id', 'opponent'])[COUNTS].sum().rename_axis(['game_id', 'team_id']).add_prefix('def_')
        table = own.join(against, how='outer').fillna(0).reset_index().assign(season=year)
        table['opponent_id'] = [other[game][team] for game, team in zip(table.game_id, table.team_id)]
        table['team_id'], table['opponent_id'] = table.team_id.map(link), table.opponent_id.map(link)
        frames.append(table.dropna(subset=['team_id', 'opponent_id']).astype({'team_id': 'int64', 'opponent_id': 'int64'}))
    return pd.concat(frames, ignore_index=True)


def rate(sums, side, name):
    top, bottom = RATES[name]
    upper = sums[f'{side}_points'] - sums[f'{side}_field_goal_points'] if top == 'free_throw_points' else sums[f'{side}_{top}']
    return 100 * upper / sums[f'{side}_{bottom}']


def measures(sums, league):
    """Each rate for the team and for the rest of the league, which leaves the team's possessions out."""
    result = {}
    for side, label in [('off', 'offence'), ('def', 'defence')]:
        rest = {key: league[key] - sums[key] for key in league}
        for name in RATES:
            result[f'{label}_{name}'] = rate(sums, side, name)
            result[f'{label}_{name}_league'] = rate(rest, side, name)
    return result


def team_seasons(games):
    rng = np.random.default_rng(SEED)
    columns = [f'{side}_{name}' for side in ('off', 'def') for name in COUNTS]
    rows = []
    for season, part in games.groupby('season'):
        league = dict(part[columns].sum())
        for team, mine in part.groupby('team_id'):
            totals = mine[columns].to_numpy()
            observed = measures(dict(zip(columns, totals.sum(axis=0))), league)
            weights = rng.multinomial(len(mine), np.full(len(mine), 1 / len(mine)), size=DRAWS)
            draws = measures(dict(zip(columns, (weights @ totals).T)), league)
            row = dict(season=season, team_id=team, games=len(mine), possessions=int(mine.off_possessions.sum()))
            for name in LABELS:
                row[name] = float(observed[name])
                row[f'{name}_league'] = float(observed[f'{name}_league'])
                row[f'{name}_noise'] = float(np.var(draws[name] - draws[f'{name}_league']))
            rows.append(row)
    return pd.DataFrame(rows)


def pooled(table):
    spread = {}
    for name in LABELS:
        gap = (table[name] - table[f'{name}_league']).to_numpy()
        noise = table[f'{name}_noise'].to_numpy()
        tau2 = minimize_scalar(lambda t: float(np.sum(np.log(t + noise) + gap ** 2 / (t + noise))), bounds=(0, 400), method='bounded').x
        weight = tau2 / (tau2 + noise)
        sd = np.sqrt(weight * noise)
        table[f'{name}_estimate'], table[f'{name}_low'], table[f'{name}_high'] = weight * gap, weight * gap - 1.96 * sd, weight * gap + 1.96 * sd
        spread[name] = float(np.sqrt(tau2))
    return table, spread


def adjusted(games, spread):
    """Estimate each offence and each defence together from single games, so a team is judged against the opponents it met.

    A game rate is the league rate plus the offence's effect plus the defence's effect plus noise that shrinks with the
    number of possessions or misses. Effects have normal priors with the spreads found by pooling.
    """
    rows = []
    for season, part in games.groupby('season'):
        teams = np.sort(pd.unique(part[['team_id', 'opponent_id']].to_numpy().ravel()))
        place = {team: k for k, team in enumerate(teams)}
        design = np.zeros((len(part), 2 * len(teams)))
        design[np.arange(len(part)), part.team_id.map(place)] = 1
        design[np.arange(len(part)), part.opponent_id.map(place) + len(teams)] = 1
        league = dict(part[[f'off_{name}' for name in COUNTS]].sum())
        found = {team: dict(season=season, team_id=team) for team in teams}
        for name, (_, bottom) in RATES.items():
            weight = part[f'off_{bottom}'].to_numpy(dtype=float)
            keep = weight > 0
            value = (rate(part[keep], 'off', name) - rate(league, 'off', name)).to_numpy()
            per_unit = np.average(value ** 2 * weight[keep], weights=np.ones(keep.sum()))
            prior = np.repeat([1 / spread[f'offence_{name}'] ** 2, 1 / spread[f'defence_{name}'] ** 2], len(teams))
            w = weight[keep] / per_unit
            covariance = np.linalg.inv(design[keep].T @ (design[keep] * w[:, None]) + np.diag(prior))
            mean = covariance @ (design[keep].T @ (w * value))
            sd = np.sqrt(np.diag(covariance))
            for team, k in place.items():
                for side, at in [('offence', k), ('defence', k + len(teams))]:
                    found[team].update({f'{side}_{name}_adjusted': mean[at], f'{side}_{name}_adjusted_low': mean[at] - 1.96 * sd[at],
                                        f'{side}_{name}_adjusted_high': mean[at] + 1.96 * sd[at]})
        rows += list(found.values())
    return pd.DataFrame(rows)


def repeatability(games):
    """Correlation of each measure between alternating games of the same team season."""
    columns = [f'{side}_{name}' for side in ('off', 'def') for name in COUNTS]
    ordered = games.sort_values(['season', 'team_id', 'game_id'])
    ordered['half'] = ordered.groupby(['season', 'team_id']).cumcount() % 2
    league = games.groupby('season')[columns].sum()
    rows = {name: [] for name in LABELS}
    for (season, team), mine in ordered.groupby(['season', 'team_id']):
        whole = dict(mine[columns].sum())
        rest = {key: league.loc[season, key] - whole[key] for key in columns}
        halves = []
        for half in (0, 1):
            sums = dict(mine[mine.half.eq(half)][columns].sum())
            halves.append({f'{label}_{name}': rate(sums, side, name) - rate(rest, side, name) for side, label in [('off', 'offence'), ('def', 'defence')] for name in RATES})
        for name in LABELS:
            rows[name].append((halves[0][name], halves[1][name]))
    rng = np.random.default_rng(SEED)
    result = []
    for name, pairs in rows.items():
        a, b = np.array(pairs).T
        picks = rng.integers(0, len(a), size=(2000, len(a)))
        draws = [np.corrcoef(a[i], b[i])[0, 1] for i in picks]
        result.append(dict(measure=name, label=LABELS[name], team_seasons=len(a), split_half=float(np.corrcoef(a, b)[0, 1]),
                           split_half_low=float(np.quantile(draws, .025)), split_half_high=float(np.quantile(draws, .975))))
    return pd.DataFrame(result)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    games = game_counts()
    table, spread = pooled(team_seasons(games))
    names = pd.read_csv(OUT / 'team_seasons.csv', usecols=['season', 'team_id', 'team'])
    table = table.merge(names, on=['season', 'team_id'], how='left')
    table['team'] = table.team.fillna('Team ' + table.team_id.astype(str))
    table = table.merge(adjusted(games, spread), on=['season', 'team_id'], validate='one_to_one')
    table['net'] = table.offence_points_adjusted - table.defence_points_adjusted
    closest = min(float(np.corrcoef(table[f'{name}_estimate'], table[f'{name}_adjusted'])[0, 1]) for name in LABELS)
    largest = max(float((table[f'{name}_adjusted'] - table[f'{name}_estimate']).abs().max()) for name in ('offence_points', 'defence_points'))
    repeats = repeatability(games)
    table.to_csv(OUT / 'possession_factors.csv', index=False)
    repeats.to_csv(OUT / 'possession_repeatability.csv', index=False)

    lines = ['# Whole possessions: what each team does and allows', '',
             f"Across {len(table)} team seasons from 2016 to 2026 and {int(table.possessions.sum()):,} complete regular season possessions, these are the correlations between alternating games of the same team season. "
             'A value near 1 means the tendency repeated across alternating games. A value near zero means the two halves showed little agreement.', '',
             '| Measure | Same season, alternating games | 95% interval | Spread between teams |', '| --- | ---: | --- | ---: |']
    lines += [f'| {r.label} | {r.split_half:.2f} | {r.split_half_low:.2f} to {r.split_half_high:.2f} | {spread[r.measure]:.1f} |' for r in repeats.itertuples()]
    lines += ['', 'Possessions come from the play by play reconstruction, which keeps only possessions whose start, events and end could be confirmed. Points include free throws. '
              'A turnover is a possession that ended with one. Offensive rebounds are counted per missed field goal that had an identifiable rebound. Free throw points are possession points minus field goal points.', '',
              f'Each team is compared with the rest of the league in the same season. Noise comes from drawing its games again {DRAWS:,} times, and each gap is pulled toward zero in proportion to that noise. '
              'The values on the site are adjusted for opponents by estimating every offence and defence together from single games. '
              f'The adjusted and unadjusted values correlate at {closest:.2f} or more, and the largest change in points per 100 possessions for any team season is {largest:.1f}. '
              'These are descriptions of past seasons.', '',
              '[Team seasons](possession_factors.csv) · [Repeatability](possession_repeatability.csv)', '']
    (OUT / 'POSSESSIONS.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

    def record(row):
        item = dict(id=int(row.team_id), name=row.team, games=int(row.games), possessions=int(row.possessions), net=round(float(row.net), 2))
        for name in LABELS:
            item[name] = dict(value=round(float(row[name]), 1), league=round(float(row[f'{name}_league']), 1), estimate=round(float(row[f'{name}_adjusted']), 2),
                              low=round(float(row[f'{name}_adjusted_low']), 2), high=round(float(row[f'{name}_adjusted_high']), 2))
        return item
    site = dict(manifestSha256=manifest_digest(), labels=LABELS, spread={k: round(v, 3) for k, v in spread.items()},
                repeatability=json.loads(repeats.to_json(orient='records')),
                seasons={str(year): [record(row) for _, row in frame.sort_values('net', ascending=False).iterrows()] for year, frame in table.groupby('season')})
    write_json(SITE / 'team-possessions.json', site)
    print(repeats[['label', 'split_half', 'split_half_low', 'split_half_high']].round(3).to_string(index=False), flush=True)
    print('TEAM_POSSESSIONS', len(table), 'team seasons', int(table.possessions.sum()), 'possessions', flush=True)


if __name__ == '__main__':
    main()
