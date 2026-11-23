"""Independently reconcile the shipped numbers to pinned shot and event rows."""
from collections import Counter, defaultdict
import csv
import gzip
import json
import math

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from benchmark import TEST, VALIDATION, paired_games
from build import DERIVED, RESULTS, SITE, write_json
from fetch import PIN, RAW, YEARS, file_matches, manifest_digest


def add(table, key, metrics):
    counts = table[key]
    for index, number in enumerate(metrics):
        counts[index] += number


def integer(value):
    return int(float(value)) if value else 0


def verify_position(row, source, year, rule, grid):
    cell, zone = int(row['cell']), int(row['zone'])
    if row['location_status'] == 'provider_origin_placeholder':
        assert year <= 2010
        assert (cell, zone) == (-1, 6)
        raw = ['y_legacy', 'x_legacy'] if year < 2002 else ['coordinate_y_raw', 'coordinate_x_raw']
        assert float(source[raw[0]]) == 0 and float(source[raw[1]]) == (0 if year < 2002 else 25)
    if not row['depth_ft'] or not row['lateral_ft']:
        assert (cell, zone) == (-1, 6)
        return
    x, y = float(row['depth_ft']), float(row['lateral_ft'])
    assert -5.25 <= x <= 88.75 and abs(y) <= 25
    raw_x = float(source['y_legacy']) / 10 if year < 2002 else float(source['coordinate_y_raw'])
    raw_y = float(source['x_legacy']) / 10 if year < 2002 else 25 - float(source['coordinate_x_raw'])
    assert math.isclose(x, raw_x, abs_tol=1e-8) and math.isclose(y, raw_y, abs_tol=1e-8), (year, x, y, raw_x, raw_y)
    distance = math.hypot(x, y)
    assert math.isclose(distance, float(row['distance_ft']), abs_tol=1e-8)
    radius, corner = rule['arc_radius'], rule['corner_distance']
    join = math.sqrt((radius - corner) * (radius + corner))
    outer = abs(y) > corner if x <= join else distance > radius
    line = float(row['line_offset_ft'])
    if abs(line) > 1e-8:
        assert outer == (line > 0)
    if x > 41.75:
        assert (cell, zone) == (-2, 5)
    else:
        col = min(grid['cols'] - 1, math.floor((y + 25) / grid['size']))
        depth = min(grid['rows'] - 1, math.floor((x + 5.25) / grid['size']))
        assert cell == depth * grid['cols'] + col
        if abs(line) > 1e-8 or not outer:
            assert zone == ((3 if x <= join else 4) if outer else (0 if distance < 4 else 1 if distance < 10 else 2))


def verify_season(year, index, all_shots):
    season = json.loads((SITE / f'{year}.json').read_bytes())
    coverage = next(row for row in index['coverage'] if row['season'] == year)
    rule, = (era for era in index['court']['eras'] if era['first_season'] <= year <= era['last_season'])
    assert season['coverage'] == coverage and season['court'] == rule['id']
    early = year < 2002
    with (DERIVED / f'games_{year}.csv').open(encoding='utf-8', newline='') as stream:
        schedule = {row['game_id']: row['scope'] for row in csv.DictReader(stream)}
    kind = 'official_shots' if early else 'shots'
    with (RAW / f'{kind}_{year}.csv').open(encoding='utf-8-sig', newline='') as stream:
        inputs = dict(enumerate(csv.DictReader(stream), start=2))
    keys = set()
    groups, league, counts, game_teams = (defaultdict(lambda: [0, 0, 0]) for _ in range(4))
    games = defaultdict(set)
    scopes = Counter()
    with gzip.open(DERIVED / f'shots_{year}.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            line = int(row['source_row'])
            assert line not in keys
            keys.add(line)
            raw = inputs[line]
            assert row['game_id'] == raw['game_id']
            m, pts = int(row['made']), int(row['points'])
            assert pts in (0, 2, 3) and m == int(pts > 0) and row['attempts'] == '1'
            if early:
                scope = {'2': 'regular', '4': 'playoffs'}[raw['game_id'][2]]
                assert m == int(raw['shot_result'] == 'Made') and pts == m * integer(raw['shot_value'])
                assert row['clock_display_value'] == raw['clock']
            else:
                assert integer(raw['team_id']) == integer(row['team_id'])
                assert pts == integer(raw['score_value'])
                assert row['type_text'] == raw['type_text']
                assert row['clock_display_value'] == raw['clock_display_value']
                assert int(row['player_id']) == integer(raw['athlete_id_1'])
                scope = schedule.get(row['game_id'], 'unknown game')
                assert 'freethrow' not in ''.join(c for c in raw['type_text'].lower() if c.isalpha())
            assert row['scope'] == scope and row['court_id'] == rule['id']
            verify_position(row, raw, year, rule, index['grid'])
            scopes[scope] += 1
            metrics = [1, m, pts]
            team, player = int(row['team_id']), int(row['player_id'])
            add(game_teams, (row['game_id'], team), metrics)
            if scope not in ('regular', 'playoffs'):
                continue
            phase = int(scope == 'playoffs')
            cell, zone, family = [int(row[k]) for k in ('cell', 'zone', 'shot_type')]
            assert 0 <= family < len(index['shotTypes'])
            games[scope].add(row['game_id'])
            add(counts, scope, metrics)
            group = (phase, team, player, cell, zone, family)
            add(groups, group, metrics)
            add(all_shots, group, metrics)
            add(league, (phase, 0, 0, cell, zone), metrics)
    remaining = Counter()
    with gzip.open(DERIVED / f'other_records_{year}.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            line = int(row['source_index']) + 2
            assert line not in keys and row['game_id'] == inputs[line]['game_id']
            keys.add(line)
            remaining[row['record_kind']] += 1
    assert keys == inputs.keys() and len(inputs) == coverage['source_rows']
    assert scopes == coverage['recorded_scope_counts']
    assert remaining['free throw'] == coverage['free_throws'] and remaining['ambiguous'] == coverage['ambiguous_rows']
    assert season['rows'] == [list(k[:-1]) + groups[k] + [k[-1]] for k in sorted(groups)]
    assert index['leagueHistory'][str(year)] == [list(k) + league[k] for k in sorted(league)]
    for phase, scope in enumerate(('regular', 'playoffs')):
        c = coverage[scope]
        assert counts[scope] == [c['attempts'], c['makes'], c['points']]
        assert len(games[scope]) == c['recorded_games']
        assert c['scheduled_games'] is None if early else list(schedule.values()).count(scope) == c['scheduled_games']
        selected = [row for row in season['rows'] if row[0] == phase]
        for status, predicate in [('mapped', lambda cell: cell >= 0), ('unknown', lambda cell: cell == -1),
                                  ('other_half', lambda cell: cell == -2)]:
            assert sum(row[5] for row in selected if predicate(row[3])) == c[status]
    print('SOURCE_ROWS_CHECKED', year, len(inputs), flush=True)
    return game_teams


def verify_boxes(observed, index):
    expected = {}
    for year in YEARS:
        if year < 2003:
            continue
        with (RAW / f'team_box_{year}.csv').open(encoding='utf-8-sig', newline='') as stream:
            for r in csv.DictReader(stream):
                key = (year, r['game_id'], integer(r['team_id']))
                fields = [r['field_goals_attempted'], r['field_goals_made'], r['three_point_field_goals_made']]
                if all(fields):
                    a, m, three = map(integer, fields)
                    expected[key] = [a, m, 2 * m + three]
    matches = Counter()
    with (RESULTS / 'team_game_audit.csv').open(encoding='utf-8', newline='') as stream:
        for r in csv.DictReader(stream):
            year, team = int(r['season']), integer(r['team_id'])
            metrics = [integer(r[k]) for k in ('attempts', 'makes', 'points')]
            assert metrics == observed.get((year, r['game_id'], team), [0, 0, 0])
            assert (metrics == expected.get((year, r['game_id'], team))) == (r['status'] == 'matches')
            if r['status'] == 'matches':
                matches[(year, r['scope'], r['game_id'])] += 1
    for row in index['coverage']:
        for scope in ('regular', 'playoffs'):
            actual = sum(n == 2 for (yr, s, _), n in matches.items() if yr == row['season'] and s == scope)
            assert actual == row[scope]['matched_team_games']


def verify_forecasts(study, cert):
    shots = pd.read_csv(DERIVED / 'shot_predictions.csv.gz')
    source = pd.concat([pd.read_csv(DERIVED / f'shots_{year}.csv.gz',
                         usecols=['season', 'game_id', 'source_row', 'made', 'points', 'scope'])
                         for year in (VALIDATION, TEST)])
    join = shots.merge(source, on=['season', 'game_id', 'source_row'], how='left',
                       suffixes=('', '_source'), validate='one_to_one')
    assert join.made.eq(join.made_source).all() and join.points.eq(join.points_source).all()
    assert join[join.split.eq('validation')].season.eq(VALIDATION).all()
    assert join[join.split.ne('validation')].season.eq(TEST).all()
    assert join.scope.eq(np.where(join.split.eq('playoffs'), 'playoffs', 'regular')).all()
    groups = {key: a for key, a in join.groupby('split')}
    for row in study['shots']:
        a = groups[row['split']]
        prediction = a[row['model']]
        assert row['attempts'] == len(a)
        assert np.isclose(row['brier'], np.mean((prediction - a.made) ** 2), atol=1e-10)
        assert np.isclose(row['log_loss'], log_loss(a.made, prediction), atol=1e-10)
    for row in study['pointModels']:
        a = groups[row['split']]
        model = row['model']
        p = a[[f'Pr({value}) {model}' for value in (0, 2, 3)]]
        assert (p >= 0).all().all() and np.allclose(p.sum(axis=1), 1)
        assert np.allclose(a[f'points {model}'], p.to_numpy() @ [0, 2, 3])
        assert np.isclose(row['rmse'], np.sqrt(np.mean((a[f'points {model}'] - a.points) ** 2)), atol=1e-10)
        assert np.isclose(row['mae'], np.mean(abs(a[f'points {model}'] - a.points)), atol=1e-10)
    for row in study['shotIntervals']:
        a = groups[row['split']]
        if row['metric'] == 'Brier':
            y, p, base = a.made, a[row['model']], a['Distance baseline']
        else:
            y, p, base = a.points, a[f"points {row['model']}"], a['points Distance outcomes']
        result = paired_games(a.game_id, (p - y) ** 2 - (base - y) ** 2)
        assert all(np.isclose(row[key], result[key], atol=1e-10) for key in ('difference', 'lower', 'upper'))
    odds = json.loads((SITE / 'bayesian.json').read_bytes())
    for name, grid in odds.items():
        expected = pd.read_csv(RESULTS / f'shot_models/{name}_surface.csv').round(6).to_numpy()
        assert np.array_equal(np.array(grid), expected) and expected.shape == (2397, 5)
        assert np.all((expected[:, 2:] >= 0) & (expected[:, 2:] <= 1))
    cert['predicted_shots'] = len(join)

    forecasts = pd.read_csv(DERIVED / 'possession_predictions.csv.gz')
    states = pd.concat([pd.read_csv(DERIVED / f'states_{year}.csv.gz',
                        usecols=['state_id', 'remaining_points', 'eligible'])
                        for year in (VALIDATION, TEST)])
    proof = forecasts.merge(states, on='state_id', how='left', validate='one_to_one', suffixes=('', '_source'))
    assert proof.eligible.eq(True).all() and proof.remaining_points.eq(proof.remaining_points_source).all()
    assert forecasts.season.eq(np.where(forecasts.split.eq('validation'), VALIDATION, TEST)).all()
    for row in study['possession']:
        a = forecasts[forecasts.split.eq(row['split'])]
        if row['stage'] != 'all':
            a = a[a.stage.eq(row['stage'])]
        error = a[row['model']] - a.remaining_points
        assert row['states'] == len(a) and np.isclose(row['rmse'], np.sqrt(np.mean(error ** 2)), atol=1e-10)
        assert np.isclose(row['mae'], np.mean(abs(error)), atol=1e-10)
    for row in study['flow']:
        frame = pd.read_csv(DERIVED / f"miss_flow_{row['year']}.csv.gz")
        a = frame[frame.split.eq(row['split']) & frame.retained_by_rebound.eq(row['rebound'])]
        assert len(a) == row['misses'] and a.remaining_points.sum() == row['later_points']
        assert a.remaining_points.gt(0).sum() == row['scored_after']
    cert['predicted_possession_states'] = len(proof)


def main():
    index = json.loads((SITE / 'index.json').read_bytes())
    pins = json.loads(PIN.read_bytes())
    assert len(pins) == index['files'] == len({row['filename'] for row in pins})
    assert manifest_digest() == index['manifestSha256']
    assert all(file_matches(RAW / row['filename'], row) for row in pins)
    assert index['seasons'] == list(YEARS)
    assert [r['first_season'] for r in index['court']['eras']] == [1997, 2004, 2013]
    aggregate, game_teams = defaultdict(lambda: [0, 0, 0]), {}
    for year in YEARS:
        game_teams.update({(year, *key): metrics for key, metrics in verify_season(year, index, aggregate).items()})
    verify_boxes(game_teams, index)
    combined = json.loads((SITE / 'all.json').read_bytes())
    assert combined['rows'] == [list(k[:-1]) + aggregate[k] + [k[-1]] for k in sorted(aggregate)]
    totals = [sum(row[i] for row in combined['rows']) for i in (5, 6, 7)]
    findings = json.loads((SITE / 'findings.json').read_bytes())
    assert totals == [findings['totals'][key] for key in ('attempts', 'makes', 'points')]
    current = findings['currentArc']
    locations = pd.read_csv(DERIVED / f'shots_{TEST}.csv.gz')
    offsets = locations.loc[locations.scope.eq('regular') & locations.cell.ge(0), 'line_offset_ft']
    assert current['inside'] == (offsets.ge(-2) & offsets.lt(0)).sum()
    assert current['outside'] == (offsets.gt(0) & offsets.le(2)).sum()
    assert math.isclose(current['ratio'], current['outside'] * current['area_inside'] /
                        (current['inside'] * current['area_outside']))
    certificate = dict(pinned_sources=len(pins), manifest_sha256=manifest_digest(), seasons=len(YEARS),
                       totals=dict(zip(('attempts', 'makes', 'points'), totals)))
    study = json.loads((SITE / 'study.json').read_bytes())
    assert study['manifestSha256'] == index['manifestSha256']
    verify_forecasts(study, certificate)
    write_json(RESULTS / 'verification.json', certificate)
    print('PUBLIC_ATLAS_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
