"""Where the points come from after each way of getting the ball.

Every complete possession in the play by play reconstruction is labelled by how
the team got the ball. Its points are split into first chance layups and dunks,
other two point shots, three point shots, free throws, and everything scored
after an offensive rebound. Possessions that end without a shot stay in the
count, so each part is in points per 100 possessions and the parts add up to
the total.
"""
import json

import numpy as np
import pandas as pd

from build import DERIVED, RESULTS, SITE, write_json
from fetch import YEARS, manifest_digest
from play_sources import DIRECTORY

TURNS = DERIVED / 'league_turns'
OUT = RESULTS / 'plays' / 'starts'
KEY = ['game_id', 'period', 'turn']
STARTS = ('Steal', 'Opponent turnover', 'Defensive rebound', 'Opponent basket', 'Opponent free throw')
PARTS = {'rim': 'Layups and dunks', 'other_two': 'Other two point shots', 'three': 'Three point shots',
         'free_throw': 'Free throws', 'second': 'Second chances'}
SHOTS = ('rim', 'other_two', 'three')
SCOPES = {'all': (YEARS[0], YEARS[-1]), 'recent': (2022, YEARS[-1])}
COMPARE = ('Steal', 'Opponent basket')
SEED = 20261125
DRAWS = 2000
COUNTS = ['possessions', 'points', 'turnovers', 'no_shot', 'scored', 'second_points', 'free_throw_points'] + [
    f'{kind}_{what}' for kind in SHOTS for what in ('attempts', 'makes', 'points')]


def shot_kind(sub_type, value):
    """Layups, dunks and tips count as shots at the rim. Everything else is split by its point value."""
    rim = sub_type.fillna('').str.contains(r'layup|dunk|tip', case=False, regex=True)
    return np.where(rim, 'rim', np.where(value.eq(3), 'three', 'other_two'))


def season_games(year):
    """One row for each game and kind of start, with possession counts and points by source."""
    turns = pd.read_csv(TURNS / f'turns_{year}.csv.gz')
    entry = pd.read_csv(TURNS / f'states_{year}.csv.gz', usecols=KEY + ['situation', 'history_length'])
    entry = entry[entry.history_length.eq(1)].set_index(KEY).situation
    assert entry.index.is_unique and len(entry) == len(turns)
    turns = turns.join(entry.rename('start'), on=KEY)

    boards = pd.read_csv(TURNS / f'boards_{year}.csv.gz').sort_values('order').drop_duplicates(KEY)
    boards = boards.set_index(KEY)[['order', 'remaining']].rename(columns={'order': 'board_order', 'remaining': 'second_points'})
    turns = turns.join(boards, on=KEY).fillna({'second_points': 0})

    events = pd.read_csv(DIRECTORY / f'wnba_play_by_play_{year}.csv.gz', usecols=['game_id', 'order_index', 'is_field_goal', 'sub_type', 'shot_value'], low_memory=False)
    events = events[events.is_field_goal.eq(1)].rename(columns={'order_index': 'order'})
    shots = pd.read_csv(TURNS / f'shots_{year}.csv.gz', usecols=KEY + ['order', 'points'])
    shots = shots.merge(events, on=['game_id', 'order'], how='left', validate='one_to_one').join(boards.board_order, on=KEY)
    assert shots.shot_value.notna().all() and (shots.points.eq(0) | shots.points.eq(shots.shot_value)).all()
    shots = shots.assign(kind=shot_kind(shots.sub_type, shots.shot_value), attempts=1, makes=shots.points.gt(0).astype(int))
    shots = shots[shots.board_order.isna() | shots.order.lt(shots.board_order)]
    first = shots.pivot_table(index=KEY, columns='kind', values=['attempts', 'makes', 'points'], aggfunc='sum', fill_value=0)
    first.columns = [f'{kind}_{what}' for what, kind in first.columns]
    names = [f'{kind}_{what}' for kind in SHOTS for what in ('attempts', 'makes', 'points')]
    turns = turns.join(first.reindex(columns=names, fill_value=0), on=KEY).fillna(dict.fromkeys(names, 0))

    turns['free_throw_points'] = turns.points - turns.second_points - sum(turns[f'{kind}_points'] for kind in SHOTS)
    assert turns.free_throw_points.ge(0).all()
    every = pd.read_csv(TURNS / f'shots_{year}.csv.gz', usecols=KEY).value_counts().rename('all_shots')
    turns = turns.join(every, on=KEY).fillna({'all_shots': 0})
    turns = turns.assign(possessions=1, turnovers=turns.end_reason.eq('turnover').astype(int), no_shot=turns.all_shots.eq(0).astype(int),
                         scored=turns.points.gt(0).astype(int))
    return turns.groupby(['season', 'game_id', 'start'], as_index=False)[COUNTS].sum()


def per_100(sums):
    """Rates for one kind of start from its summed counts."""
    n = sums['possessions']
    row = dict(possessions=int(n), points=100 * sums['points'] / n, turnovers=100 * sums['turnovers'] / n, no_shot=100 * sums['no_shot'] / n,
               scored=100 * sums['scored'] / n, second=100 * sums['second_points'] / n, free_throw=100 * sums['free_throw_points'] / n)
    for kind in SHOTS:
        row[kind] = 100 * sums[f'{kind}_points'] / n
        row[f'{kind}_attempts'] = 100 * sums[f'{kind}_attempts'] / n
        row[f'{kind}_make_rate'] = sums[f'{kind}_makes'] / sums[f'{kind}_attempts']
    return row


def gap_parts(first, second):
    """The gap in points per 100 possessions between two kinds of start, part by part, with layups split into volume and finishing."""
    a, b = per_100(first), per_100(second)
    gap = {'total': a['points'] - b['points'], **{part: a[part] - b[part] for part in PARTS}}
    value = lambda row: row['rim'] / row['rim_attempts']
    gap['rim_volume'] = (a['rim_attempts'] - b['rim_attempts']) * (value(a) + value(b)) / 2
    gap['rim_finishing'] = (a['rim_attempts'] + b['rim_attempts']) / 2 * (value(a) - value(b))
    return gap


def steal_gap(games):
    """Each part of the gap with a 95% interval from drawing whole games again."""
    sides = [games[games.start.eq(name)].set_index('game_id')[COUNTS] for name in COMPARE]
    index = sides[0].index.union(sides[1].index)
    sides = [side.reindex(index, fill_value=0).to_numpy(float) for side in sides]
    observed = gap_parts(*[dict(zip(COUNTS, side.sum(axis=0))) for side in sides])
    rng = np.random.default_rng(SEED)
    weights = rng.multinomial(len(index), np.full(len(index), 1 / len(index)), size=DRAWS)
    drawn = [weights @ side for side in sides]
    draws = pd.DataFrame([gap_parts(dict(zip(COUNTS, x)), dict(zip(COUNTS, y))) for x, y in zip(*drawn)])
    low, high = draws.quantile(.025), draws.quantile(.975)
    return pd.DataFrame([dict(part=part, gap=observed[part], low=low[part], high=high[part]) for part in observed]), len(index)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    games = pd.concat([season_games(year) for year in YEARS], ignore_index=True)
    assert set(games.start) == set(STARTS)
    by_season = pd.DataFrame([dict(season=year, start=start, **per_100(frame[COUNTS].sum())) for (year, start), frame in games.groupby(['season', 'start'])])
    by_season.to_csv(OUT / 'by_season.csv', index=False)

    tables, gaps, site = [], [], dict(manifestSha256=manifest_digest(), parts=PARTS, compare=list(COMPARE), scopes={})
    for scope, (first, last) in SCOPES.items():
        chosen = games[games.season.between(first, last)]
        table = pd.DataFrame([dict(scope=scope, start=start, **per_100(chosen[chosen.start.eq(start)][COUNTS].sum())) for start in STARTS])
        table = table.sort_values('points', ascending=False)
        gap, used = steal_gap(chosen)
        tables.append(table)
        gaps.append(gap.assign(scope=scope))
        site['scopes'][scope] = dict(first=int(first), last=int(last), games=int(used), starts=json.loads(table.drop(columns='scope').round(4).to_json(orient='records')),
                                     gap=json.loads(gap.round(4).to_json(orient='records')))
    table, gap = pd.concat(tables, ignore_index=True), pd.concat(gaps, ignore_index=True)
    table.to_csv(OUT / 'by_start.csv', index=False)
    gap.to_csv(OUT / 'steal_gap.csv', index=False)
    write_json(SITE / 'start-points.json', site)

    whole = table[table.scope.eq('all')].set_index('start')
    steal, basket = whole.loc[COMPARE[0]], whole.loc[COMPARE[1]]
    g = gap[gap.scope.eq('all')].set_index('part')
    span = lambda part: f"{g.loc[part, 'gap']:+.1f} ({g.loc[part, 'low']:+.1f} to {g.loc[part, 'high']:+.1f})"
    lines = ['# Where the points come from after each way of getting the ball', '',
             f"From {SCOPES['all'][0]} to {SCOPES['all'][1]}, teams scored {steal.points:.1f} points per 100 possessions after a steal and {basket.points:.1f} after an opponent's basket, a gap of {g.loc['total', 'gap']:.1f}. "
             'Every possession counts, including those that ended without a shot.', '',
             '| How the team got the ball | Possessions | Points per 100 | ' + ' | '.join(PARTS.values()) + ' | No shot per 100 |', '| --- | ---: | ---: | ' + '---: | ' * len(PARTS) + '---: |']
    lines += [f"| {r.start} | {r.possessions:,} | {r.points:.1f} | " + ' | '.join(f'{getattr(r, part):.1f}' for part in PARTS) + f' | {r.no_shot:.1f} |' for r in whole.reset_index().itertuples()]
    lines += ['', '## The gap between a steal and an opponent\'s basket', '',
              '| Part | Gap in points per 100 possessions | 95% range |', '| --- | ---: | --- |']
    lines += [f"| {PARTS[part]} | {g.loc[part, 'gap']:+.1f} | {g.loc[part, 'low']:+.1f} to {g.loc[part, 'high']:+.1f} |" for part in PARTS]
    lines += ['', f"After a steal teams took {steal.rim_attempts:.1f} first chance layups and dunks per 100 possessions and made {100 * steal.rim_make_rate:.1f}% of them. "
              f"After an opponent's basket they took {basket.rim_attempts:.1f} and made {100 * basket.rim_make_rate:.1f}%. "
              f"Of the gap from layups and dunks, taking more of them accounts for {span('rim_volume')} points per 100 possessions and making more of them for {span('rim_finishing')}.", '',
              f"For {SCOPES['recent'][0]} to {SCOPES['recent'][1]} alone the total gap is {gap[gap.scope.eq('recent')].set_index('part').loc['total', 'gap']:.1f}.", '',
              '## How it is counted', '',
              'Possessions come from the play by play reconstruction, which keeps only possessions whose start, events and end could be confirmed, in regular season and playoff games. '
              'A shot is a layup or dunk when the league event file describes it as a layup, dunk or tip. First chance means before any offensive rebound in the possession. '
              'Second chances are all points after the first offensive rebound, from any shot or free throw. Free throws are the remaining first chance points. '
              f'Ranges come from drawing whole games again {DRAWS:,} times. The split of the layup gap into volume and finishing averages the two orders of the comparison. These are descriptions of what happened and do not show that forcing more steals would add the same points.', '',
              '[By start](by_start.csv) · [Gap between a steal and an opponent\'s basket](steal_gap.csv) · [By season](by_season.csv)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(whole[['possessions', 'points', *PARTS, 'no_shot', 'rim_attempts', 'rim_make_rate']].round(3).to_string(), flush=True)
    print(g.round(2).to_string(), flush=True)
    print('START_POINTS', int(table[table.scope.eq('all')].possessions.sum()), 'possessions', flush=True)


if __name__ == '__main__':
    main()
