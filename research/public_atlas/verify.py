"""Reconcile released season aggregates to their pinned input rows."""
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

from fetch import HERE, PIN, RAW, ROOT, TAGS, YEARS, file_matches

SITE = ROOT / 'explore/data'
RESULTS = ROOT / 'research/results/public_atlas'
DERIVED = ROOT / 'research/data/public_wnba/derived'


def check_geometry(index):
    old, new = index['court']['eras']
    assert old['last_season'] == 2012 and new['first_season'] == 2013
    assert old['arc_radius'] < 21 < new['arc_radius']
    assert old['corner_distance'] < 21 < new['corner_distance']
    for era in (old, new):
        join = math.sqrt(era['arc_radius'] ** 2 - era['corner_distance'] ** 2)
        assert math.isclose(math.hypot(join, era['corner_distance']), era['arc_radius'])
    assert index['grid']['baseline'] == -5.25 and index['grid']['midcourt'] == 41.75


def counter_add(table, key, n, makes, points):
    result = table[key]
    result[0] += n
    result[1] += makes
    result[2] += points


def number(text):
    return float(text) if text else math.nan


def shot_region(row, rules, grid, scope):
    n, m, points = int(row['attempts']), int(row['made']), int(row['points'])
    assert n == 1 and points in (0, 2, 3) and m == int(points > 0)
    assert row['scope'] == scope
    cell, zone = int(row['cell']), int(row['zone'])
    x, y = number(row['depth_ft']), number(row['lateral_ft'])
    if not (math.isfinite(x) and math.isfinite(y)):
        assert (cell, zone) == (-1, 6)
        return n, m, points
    assert math.isclose(x, float(row['coordinate_y_raw']), abs_tol=1e-8)
    assert math.isclose(y, 25 - float(row['coordinate_x_raw']), abs_tol=1e-8)
    assert -5.25 <= x <= 88.75 and abs(y) <= 25
    radius, corner = rules['arc_radius'], rules['corner_distance']
    rim_distance = math.hypot(x,y)
    assert math.isclose(rim_distance, float(row['distance_ft']), abs_tol=1e-8)
    join = math.sqrt((radius - corner) * (radius + corner))
    line = float(row['line_offset_ft'])
    outer = abs(y) > corner if x <= join else rim_distance > radius
    if abs(line) > 1e-8:
        assert outer == (line > 0)
    if x > 41.75:
        assert (cell, zone) == (-2, 5)
    else:
        assert cell == min(grid['rows'] - 1, int((x + 5.25) / 2.5)) * grid['cols'] + min(grid['cols'] - 1, int((y + 25) / 2.5))
        expected_zone = (3 if x <= join else 4) if outer and abs(line) > 1e-8 else (0 if rim_distance < 4 else 1 if rim_distance < 10 else 2)
        if abs(line) > 1e-8 or not outer:
            assert zone == expected_zone
    return n, m, points


def verify_season(year, index):
    season = json.loads((SITE / f'{year}.json').read_bytes())
    coverage = next(row for row in index['coverage'] if row['season'] == year)
    rule, = (era for era in index['court']['eras'] if era['first_season'] <= year <= era['last_season'])
    assert season['coverage'] == coverage and season['court'] == rule['id']
    with (DERIVED / f'games_{year}.csv').open('r', encoding='utf-8', newline='') as stream:
        schedule = {row['game_id']: row['scope'] for row in csv.DictReader(stream)}
    with (RAW / f'shots_{year}.csv').open('r', encoding='utf-8-sig', newline='') as stream:
        inputs = dict(enumerate(csv.DictReader(stream), start=2))
    all_rows = set()
    counts = defaultdict(lambda: [0,0,0])
    groups = defaultdict(lambda: [0,0,0])
    league = defaultdict(lambda: [0,0,0])
    scopes = Counter()
    game_teams = defaultdict(lambda: [0,0,0])
    game_sets = defaultdict(set)
    with gzip.open(DERIVED / f'shots_{year}.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            source_row = int(row['source_row'])
            assert source_row not in all_rows
            all_rows.add(source_row)
            original = inputs[source_row]
            for key in ('game_id','team_id','type_text','clock_display_value'):
                assert row[key] == original[key], (year, source_row, key)
            for key in ('coordinate_x','coordinate_y'):
                a, b = number(row[key]), number(original[key])
                assert (math.isnan(a) and math.isnan(b)) or math.isclose(a,b,abs_tol=1e-8)
            assert int(row['points']) == int(float(original['score_value']))
            scope = schedule.get(row['game_id'], 'unknown game')
            n, m, pts = shot_region(row, rule, index['grid'], scope)
            assert row['court_id'] == rule['id']
            scopes[scope] += 1
            counter_add(game_teams, (row['game_id'],row['team_id']), n, m, pts)
            if scope not in ('regular', 'playoffs'):
                continue
            phase = int(scope == 'playoffs')
            team, player = int(row['team_id']), int(row['player_id'])
            cell, zone = int(row['cell']), int(row['zone'])
            original_player = original['athlete_id_1']
            assert player == (int(float(original_player)) if original_player else 0)
            game_sets[scope].add(row['game_id'])
            counter_add(counts, scope, n, m, pts)
            counter_add(groups, (phase,team,player,cell,zone), n, m, pts)
            counter_add(league, (phase,0,0,cell,zone), n, m, pts)
    remaining = Counter()
    with gzip.open(DERIVED / f'other_records_{year}.csv.gz','rt',encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            source_row = int(row['source_index']) + 2
            assert source_row not in all_rows and row['game_id'] == inputs[source_row]['game_id']
            all_rows.add(source_row)
            remaining[row['record_kind']] += 1
    assert all_rows == inputs.keys()
    assert len(inputs) == coverage['source_rows']
    assert scopes == coverage['recorded_scope_counts']
    assert remaining['free throw'] == coverage['free_throws'] and remaining['ambiguous'] == coverage['ambiguous_rows']
    assert season['rows'] == [list(key) + groups[key] for key in sorted(groups)]
    assert index['leagueHistory'][str(year)] == [list(key) + league[key] for key in sorted(league)]
    for phase in ('regular', 'playoffs'):
        c = coverage[phase]
        assert counts[phase] == [c['attempts'],c['makes'],c['points']]
        assert len(game_sets[phase]) == c['recorded_games']
        assert list(schedule.values()).count(phase) == c['scheduled_games']
        observed = [row for row in season['rows'] if row[0] == int(phase=='playoffs')]
        assert sum(row[5] for row in observed if row[3] >= 0) == c['mapped']
        assert sum(row[5] for row in observed if row[3] == -1) == c['unknown']
        assert sum(row[5] for row in observed if row[3] == -2) == c['other_half']
    return game_teams


def verify_team_audit(actual, index):
    matches = Counter()
    with (RESULTS / 'team_game_audit.csv').open('r', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            key = (row['game_id'], row['team_id'])
            observed = [int(float(row[name] or 0)) for name in ('attempts','makes','points')]
            assert actual.get(key, [0,0,0]) == observed
            expected = [number(row[f'box_{name}']) for name in ('attempts','makes','points')]
            assert (observed == expected) == (row['status'] == 'matches')
            if row['status'] == 'matches':
                matches[int(row['season']),row['scope'],row['game_id']] += 1
    for year in index['coverage']:
        for phase in ('regular','playoffs'):
            total = sum(n == 2 for (season, scope, _), n in matches.items() if season == year['season'] and scope == phase)
            assert total == year[phase]['matched_team_games']


def main():
    index = json.loads((SITE / 'index.json').read_bytes())
    pins = json.loads(PIN.read_bytes())
    assert len(pins) == index['files'] == len(YEARS) * len(TAGS)
    assert {(row['season'],row['kind']) for row in pins} == {(year, kind) for year in YEARS for kind in TAGS}
    assert hashlib.sha256(PIN.read_bytes()).hexdigest() == index['manifestSha256']
    for row in pins:
        assert file_matches(RAW / row['filename'], row), row['filename']
    assert index['seasons'] == list(YEARS)
    check_geometry(index)
    all_games = {}
    for year in YEARS:
        game_rows = verify_season(year, index)
        assert not (all_games.keys() & game_rows.keys())
        all_games.update(game_rows)
        print('Checked source rows, court bins and all browser totals for', year, flush=True)
    verify_team_audit(all_games, index)
    cross = index['archiveComparison']
    assert cross['exact_shots'] == cross['archive_attempts'] == cross['public_attempts'] == 42193
    assert cross['archive_only'] == cross['public_only'] == cross['different_game_team'] == 0
    assert cross['shared_games'] == 312
    prior = {'assets/data.json':'86db4f8b91dff9178ff91639f7d21c23f98bac0c48e4d1ef1442485c4ae6d8c3',
             'assets/recovery.json':'e49211482a1b1b4226a14538da71f28e8276d1faea9cb6ecf61fc61e06022077'}
    for name, expected in prior.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    print('PUBLIC_ATLAS_SOURCE_CHECKS_PASS', len(YEARS), len(pins), flush=True)


if __name__ == '__main__':
    main()
