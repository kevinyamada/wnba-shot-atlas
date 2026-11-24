"""Check the points by start study by counting again from the raw league event rows.

The study joins saved shot and rebound tables. This check ignores those tables.
It places every raw event inside a possession by its position between the
possession's first and last event, then counts points, layups and second
chances from the raw rows.
"""
import json

import numpy as np
import pandas as pd

from build import DERIVED, RESULTS, SITE
from fetch import YEARS
from play_sources import DIRECTORY

TURNS = DERIVED / 'league_turns'
OUT = RESULTS / 'plays' / 'starts'
KEY = ['game_id', 'period', 'turn']
PARTS = ['rim', 'other_two', 'three', 'free_throw', 'second']


def recount(year):
    turns = pd.read_csv(TURNS / f'turns_{year}.csv.gz')
    entry = pd.read_csv(TURNS / f'states_{year}.csv.gz', usecols=KEY + ['situation', 'history_length'])
    turns = turns.merge(entry[entry.history_length.eq(1)].drop(columns='history_length'), on=KEY, validate='one_to_one')
    events = pd.read_csv(DIRECTORY / f'wnba_play_by_play_{year}.csv.gz', low_memory=False,
                         usecols=['game_id', 'order_index', 'period', 'team_id', 'person_id', 'action_type', 'sub_type', 'description', 'is_field_goal', 'shot_result', 'shot_value'])
    events = events[events.game_id.isin(turns.game_id.unique())].sort_values(['game_id', 'order_index'])
    action = events.action_type.fillna('').str.lower()
    text = events.sub_type.fillna('') + ' ' + events.description.fillna('')
    shot = events.is_field_goal.eq(1) & events.shot_result.isin(['Made', 'Missed'])
    free_throw, rebound = action.eq('free throw'), action.eq('rebound')
    series = text.str.extract(r'\b([1-3])\s+of\s+([1-3])\b')
    missed = events.description.fillna('').str.match(r'^\s*miss', case=False)
    events = events.assign(shot=shot, rebound=rebound, early_miss=free_throw & missed & series[0].lt(series[1]),
                           value=np.where(shot, np.where(events.shot_result.eq('Made'), events.shot_value, 0), np.where(free_throw & ~missed, 1, 0)))
    events = events[shot | free_throw | rebound].copy()
    events['after_early_miss'] = events.groupby('game_id').early_miss.shift(fill_value=False)
    teams = set(turns.team)
    events['team'] = events.team_id.where(events.team_id.isin(teams), events.person_id)

    placed = pd.merge_asof(events.sort_values('order_index'), turns.sort_values('turn')[KEY + ['team', 'end_order', 'situation']].rename(columns={'team': 'turn_team', 'period': 'turn_period'}),
                           left_on='order_index', right_on='turn', by='game_id', allow_exact_matches=False)
    placed = placed[placed.order_index.le(placed.end_order) & placed.period.eq(placed.turn_period) & placed.team.eq(placed.turn_team)]
    key = ['game_id', 'turn_period', 'turn']
    board = placed[placed.rebound & ~placed.after_early_miss].groupby(key).order_index.min().rename('board')
    placed = placed.join(board, on=key)
    late = placed.board.notna() & placed.order_index.gt(placed.board)
    rim = placed.sub_type.fillna('').str.lower().str.contains('layup|dunk|tip')
    kind = np.select([late, placed.shot & rim, placed.shot & placed.shot_value.eq(3), placed.shot], ['second', 'rim', 'three', 'other_two'], 'free_throw')
    placed = placed.assign(kind=kind, first_rim=placed.shot & rim & ~late, made=placed.value.gt(0))

    points = placed.groupby(key).value.sum().reindex(pd.MultiIndex.from_frame(turns[KEY].rename(columns={'period': 'turn_period'})), fill_value=0).to_numpy()
    assert (points == turns.points.to_numpy()).all(), f'{year}: raw rows inside a possession do not add up to its recorded points'
    sums = placed.groupby(['situation', 'kind']).value.sum().unstack(fill_value=0)
    sums['rim_attempts'] = placed[placed.first_rim].groupby('situation').size()
    sums['rim_makes'] = placed[placed.first_rim & placed.made].groupby('situation').size()
    sums['possessions'] = turns.groupby('situation').size()
    sums['points'] = turns.groupby('situation').points.sum()
    return sums


def main():
    total = sum(recount(year) for year in YEARS)
    saved = pd.read_csv(OUT / 'by_start.csv')
    saved = saved[saved.scope.eq('all')].set_index('start')
    assert set(saved.index) == set(total.index)
    for start, row in total.iterrows():
        mine = saved.loc[start]
        assert row.possessions == mine.possessions and abs(100 * row.points / row.possessions - mine.points) < 1e-9, start
        for part in PARTS:
            assert abs(100 * row[part] / row.possessions - mine[part]) < 1e-9, (start, part, 100 * row[part] / row.possessions, mine[part])
        assert abs(100 * row.rim_attempts / row.possessions - mine.rim_attempts) < 1e-9 and abs(row.rim_makes / row.rim_attempts - mine.rim_make_rate) < 1e-12, start
        assert abs(sum(mine[part] for part in PARTS) - mine.points) < 1e-9, start

    earlier = pd.read_csv(RESULTS / 'plays/situations_by_season.csv')
    earlier = earlier[earlier.situation.ne('Offensive rebound')].groupby('situation')[['states', 'points']].sum()
    assert (earlier.states == total.possessions).all() and (earlier.points == total.points).all(), 'the possession study and this study should count the same possessions'

    gaps = pd.read_csv(OUT / 'steal_gap.csv')
    for scope, gap in gaps.groupby('scope'):
        gap = gap.set_index('part')
        assert abs(gap.loc[PARTS, 'gap'].sum() - gap.loc['total', 'gap']) < 1e-9, scope
        assert abs(gap.loc['rim_volume', 'gap'] + gap.loc['rim_finishing', 'gap'] - gap.loc['rim', 'gap']) < 1e-9, scope
        assert (gap.low <= gap.gap).all() and (gap.gap <= gap.high).all(), scope
    whole = gaps[gaps.scope.eq('all')].set_index('part').gap
    steal, basket = saved.loc['Steal'], saved.loc['Opponent basket']
    assert abs(whole['total'] - (steal.points - basket.points)) < 1e-9

    site = json.loads((SITE / 'start-points.json').read_bytes())
    shown = {row['start']: row for row in site['scopes']['all']['starts']}
    assert all(abs(shown[start]['points'] - saved.loc[start, 'points']) < 1e-4 and shown[start]['possessions'] == saved.loc[start, 'possessions'] for start in saved.index)
    result = dict(possessions=int(total.possessions.sum()), steal_points=round(float(steal.points), 2), basket_points=round(float(basket.points), 2), gap=round(float(whole['total']), 2),
                  rim_gap=round(float(whole['rim']), 2), rim_volume=round(float(whole['rim_volume']), 2), rim_finishing=round(float(whole['rim_finishing']), 2))
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('START_POINTS_VERIFIED', json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
