"""Recount games, attempts, makes and points from the pinned raw files.

This script reads the raw CSV files directly and shares no code with build.py.
It then compares the recount with the saved reports, the site data and,
with --live, the files served by the public page.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'research/data/public_wnba/raw'
RESULTS = ROOT / 'research/results/public_atlas'
OUT = RESULTS / 'recount'
SITE = ROOT / 'explore/data'
LIVE = 'https://kevinyamada.github.io/wnba-shot-atlas/explore/data/'
YEARS = range(1997, 2027)
PHASES = ['regular', 'playoffs']
ZONES = ['At the rim', 'Short two area', 'Midrange area', 'Corner three area',
         'Above the break', 'Other half', 'Unknown location']
SPECIAL_IDS = {401353913: '2021 Commissioner’s Cup final', 401558893: '2023 All Star Game'}
DUPLICATE_SCHEDULE_ROW = 400182104
RIM_FROM_BASELINE, HALF_COURT, HALF_WIDTH, COURT_LENGTH = 5.25, 41.75, 25, 94
COUNTS = ['attempts', 'makes', 'points']


def check_pins():
    pins = json.loads((ROOT / 'research/public_atlas/source_manifest.json').read_bytes())
    bad = [pin['filename'] for pin in pins
           if hashlib.sha256((RAW / pin['filename']).read_bytes()).hexdigest() != pin['sha256']]
    return len(pins), bad


def arc_for(year):
    if year <= 2003:
        return 19.75, 19.75
    if year <= 2012:
        return 20 + 6.25 / 12, 20.5
    return 22 + 1.75 / 12, 22.0


def add_location(shots, year, depth, lateral, trusted):
    radius, corner = arc_for(year)
    join = np.sqrt(radius ** 2 - corner ** 2)
    distance = np.hypot(depth, lateral)
    finite = np.isfinite(depth) & np.isfinite(lateral)
    on_court = (depth >= -RIM_FROM_BASELINE) & (depth <= COURT_LENGTH - RIM_FROM_BASELINE) & (np.abs(lateral) <= HALF_WIDTH)
    at_basket = (depth == 0) & (lateral == 0)
    reason = np.select([~finite, at_basket & (year <= 2010), ~trusted, ~on_court],
                       ['missing coordinates', 'exactly at the basket through 2010',
                        'coordinate pairs disagree', 'outside the court'], default='')
    known = reason == ''
    outside_line = np.where(depth <= join, np.abs(lateral) > corner, distance > radius)
    shots['location'] = np.select([~known, depth > HALF_COURT], ['unknown', 'other half'], default='mapped half')
    shots['unknown_reason'] = reason
    shots['pairs_agree'] = trusted
    shots['zone'] = np.select([~known, depth > HALF_COURT, outside_line & (depth <= join), outside_line,
                               distance < 4, distance < 10], [6, 5, 3, 4, 0, 1], default=2)
    return shots


def early_season(year):
    raw = pd.read_csv(RAW / f'official_shots_{year}.csv', low_memory=False)
    field_goal = raw.shot_value.isin([2, 3]) & raw.shot_result.isin(['Made', 'Missed'])
    shots = raw[field_goal].copy()
    shots['phase'] = shots.game_id.astype(str).str[2].map({'2': 'regular', '4': 'playoffs'}).fillna('other')
    shots['makes'] = shots.shot_result.eq('Made').astype(int)
    shots['points'] = shots.makes * shots.shot_value
    shots['value'] = shots.shot_value.astype(float)
    depth, lateral = shots.y_legacy.to_numpy(float) / 10, shots.x_legacy.to_numpy(float) / 10
    shots = add_location(shots, year, depth, lateral, np.ones(len(shots), bool))
    shots['team_in_game'] = True
    rows = dict(season=year, feed='WNBA Stats', source_rows=len(raw), free_throws=0,
                field_goal_rows=len(shots), other_rows=int((~field_goal).sum()),
                scored_rows_without_shot_label=0, points_on_those_rows=0, counted_as_makes_with_box_support=0,
                unscored_rows_without_shot_label=0)
    return shots, rows, None


def espn_schedule(year):
    games = pd.read_csv(RAW / f'wnba_schedule_{year}.csv', low_memory=False)
    notes = games.notes_headline.fillna('').str.lower()
    special = notes.str.contains(r'all\W*star|cup championship|cup final|exhibition') | games.game_id.isin(SPECIAL_IDS)
    played = games.status_type_name.eq('STATUS_FINAL') & games.status_type_completed.astype(str).str.lower().eq('true')
    games['phase'] = np.select([~played, special, games.season_type.eq(2), games.season_type.eq(3)],
                               ['not played', 'special', 'regular', 'playoffs'], default='other')
    if year == 2011:
        games.loc[games.game_id.eq(DUPLICATE_SCHEDULE_ROW), 'phase'] = 'duplicate schedule row'
    if year == 2002:
        # The schedule calls the Portland Fire team 12. The shot file calls the same team 132052.
        games[['home_id', 'away_id']] = games[['home_id', 'away_id']].replace(12, 132052)
    return games[['game_id', 'phase', 'home_id', 'away_id', 'notes_headline', 'game_date']]


def espn_season(year):
    raw = pd.read_csv(RAW / f'shots_{year}.csv', low_memory=False)
    games = espn_schedule(year)
    raw['label'] = raw.type_text.fillna('').str.lower().str.replace(r'[^a-z]', '', regex=True)
    score = pd.to_numeric(raw.score_value, errors='coerce')
    free_throw = raw.label.str.contains('freethrow')
    not_a_shot = raw.label.str.contains('turnover|foul|violation|notavailable|noshot')
    labelled = ~free_throw & ~not_a_shot & score.isin([0, 2, 3])
    confirmed = box_supported(year, raw, labelled, ~free_throw & not_a_shot & score.isin([2, 3]))
    field_goal = labelled | confirmed
    shots = raw[field_goal].merge(games, on='game_id', how='left', validate='many_to_one')
    shots['phase'] = shots.phase.fillna('game not in schedule')
    shots['points'] = pd.to_numeric(shots.score_value).astype(int)
    shots['makes'] = shots.points.gt(0).astype(int)
    shots['value'] = np.select([shots.makes.eq(1), shots.label.str.contains('threepoint'), shots.label.str.contains('twopoint')],
                               [shots.points, 3, 2], default=np.nan)
    depth = shots.coordinate_y_raw.to_numpy(float)
    lateral = HALF_WIDTH - shots.coordinate_x_raw.to_numpy(float)
    side = np.select([shots.team_id.eq(shots.home_id), shots.team_id.eq(shots.away_id)], [1, -1], default=0)
    trusted = ((side != 0) & np.isclose(HALF_COURT - shots.coordinate_x.to_numpy(float) * side, depth, atol=1e-8, rtol=0)
               & np.isclose(shots.coordinate_y.to_numpy(float) * side, lateral, atol=1e-8, rtol=0))
    shots = add_location(shots, year, depth, lateral, trusted)
    shots['team_in_game'] = side != 0
    in_scope = raw.game_id.isin(games[games.phase.isin(PHASES)].game_id)
    odd = in_scope & ~free_throw & not_a_shot & score.isin([2, 3])
    rows = dict(season=year, feed='ESPN', source_rows=len(raw), free_throws=int(free_throw.sum()),
                field_goal_rows=len(shots), other_rows=int((~free_throw & ~field_goal).sum()),
                scored_rows_without_shot_label=int(odd.sum()), points_on_those_rows=int(raw[odd].score_value.sum()),
                counted_as_makes_with_box_support=int((odd & confirmed).sum()),
                unscored_rows_without_shot_label=int((in_scope & ~free_throw & not_a_shot & score.eq(0)).sum()))
    return shots, rows, games


def box_supported(year, raw, labelled, stray):
    """A scored row without a shot label is a made basket when the team box still has makes to account for."""
    keep = pd.Series(False, index=raw.index)
    if year < 2003 or not stray.any():
        return keep
    box = pd.read_csv(RAW / f'team_box_{year}.csv', low_memory=False)
    box = pd.to_numeric(box.set_index(['game_id', 'team_id']).field_goals_made, errors='coerce').dropna()
    made = raw[labelled & raw.score_value.gt(0)].groupby(['game_id', 'team_id']).size()
    for key, rows in raw[stray].groupby(['game_id', 'team_id']):
        if key in box.index and made.get(key, 0) + len(rows) <= box[key]:
            keep[rows.index] = True
    return keep


def box_check(year, shots, games):
    """Compare the shot feed with ESPN team boxes on games where both teams have a box."""
    if year < 2003:
        return {}
    box = pd.read_csv(RAW / f'team_box_{year}.csv', low_memory=False)
    need = ['field_goals_attempted', 'field_goals_made', 'three_point_field_goals_made', 'three_point_field_goals_attempted']
    box[need] = box[need].apply(pd.to_numeric, errors='coerce')
    scope = games[games.phase.isin(PHASES)].game_id
    box = box[box.game_id.isin(scope)].dropna(subset=need)
    complete = box.groupby('game_id').size().eq(2)
    box = box[box.game_id.isin(complete[complete].index)]
    feed = shots[shots.game_id.isin(box.game_id) & shots.phase.isin(PHASES)]
    return dict(box_games=int(box.game_id.nunique()),
                box_attempts=int(box.field_goals_attempted.sum()), feed_attempts_same_games=len(feed),
                box_makes=int(box.field_goals_made.sum()), feed_makes_same_games=int(feed.makes.sum()),
                box_points=int((2 * box.field_goals_made + box.three_point_field_goals_made).sum()),
                feed_points_same_games=int(feed.points.sum()),
                box_three_attempts=int(box.three_point_field_goals_attempted.sum()),
                box_three_makes=int(box.three_point_field_goals_made.sum()),
                feed_three_makes_same_games=int(feed.points.eq(3).sum()))


def season_rows(year, shots, games):
    rows = []
    for phase in PHASES:
        a = shots[shots.phase.eq(phase)]
        played = None if games is None else int(games.phase.eq(phase).sum())
        rows.append(dict(season=year, phase=phase, completed_games_in_schedule=played,
                         games_with_shots=int(a.game_id.nunique()),
                         attempts=len(a), makes=int(a.makes.sum()), points=int(a.points.sum()),
                         two_attempts=int(a.value.eq(2).sum()), two_makes=int(a.points.eq(2).sum()),
                         three_attempts=int(a.value.eq(3).sum()), three_makes=int(a.points.eq(3).sum()),
                         unknown_value_attempts=int(a.value.isna().sum()),
                         mapped_half=int(a.location.eq('mapped half').sum()),
                         other_half=int(a.location.eq('other half').sum()),
                         unknown_location=int(a.location.eq('unknown').sum()),
                         at_basket_through_2010=int(a.unknown_reason.eq('exactly at the basket through 2010').sum()),
                         coordinate_pairs_disagree=int(a.unknown_reason.eq('coordinate pairs disagree').sum()),
                         outside_court=int(a.unknown_reason.eq('outside the court').sum()),
                         missing_coordinates=int(a.unknown_reason.eq('missing coordinates').sum()),
                         team_not_in_game=int((~a.team_in_game).sum()),
                         team_not_in_game_at_basket=int((~a.team_in_game & a.unknown_reason.eq('exactly at the basket through 2010')).sum())))
    return rows


def recount():
    seasons, zones, feeds, boxes, excluded, special_games = [], [], [], [], [], []
    for year in YEARS:
        shots, feed, games = early_season(year) if year < 2002 else espn_season(year)
        seasons += season_rows(year, shots, games)
        feeds.append(feed)
        kept = shots[shots.phase.isin(PHASES)]
        zone = kept.groupby(['phase', 'zone'])[COUNTS[1:]].sum().join(kept.groupby(['phase', 'zone']).size().rename('attempts'))
        zones.append(zone.reset_index().assign(season=year))
        out = shots[~shots.phase.isin(PHASES)].groupby('phase').agg(
            games=('game_id', 'nunique'), attempts=('makes', 'size'), makes=('makes', 'sum'), points=('points', 'sum'))
        excluded.append(out.reset_index().assign(season=year))
        if games is not None:
            boxes.append(dict(season=year, **box_check(year, shots, games)))
            special = games[games.phase.eq('special')].merge(
                shots.groupby('game_id').size().rename('attempts'), on='game_id', how='left')
            special_games.append(special.assign(season=year))
        print(f'{year}: {len(kept):,} regular season and playoff attempts', flush=True)
    return (pd.DataFrame(seasons), pd.concat(zones), pd.DataFrame(feeds), pd.DataFrame(boxes),
            pd.concat(excluded), pd.concat(special_games))


def pack_totals(pack):
    rows = pd.DataFrame(pack['rows'], columns=['phase', 'team', 'player', 'cell', 'zone', 'attempts', 'makes', 'points', 'shot_type'])
    return rows.groupby(['phase', 'zone'])[COUNTS].sum()


def compare(seasons, zones, live):
    """List every published number that can be traced, next to the recount."""
    checks = []

    def note(item, counted, published):
        checks.append(dict(item=item, recount=counted, published=published, difference=counted - published))

    total = seasons[COUNTS].sum()
    places = seasons[['mapped_half', 'other_half', 'unknown_location']].sum()
    findings = json.loads((SITE / 'findings.json').read_bytes())['totals']
    for mine, saved in [('mapped_half', 'mapped'), ('other_half', 'other_half'), ('unknown_location', 'unknown')]:
        note(f'findings.json {saved}', int(places[mine]), findings[saved])
    certificate = json.loads((RESULTS / 'verification.json').read_bytes())['totals']
    for metric in COUNTS:
        note(f'findings.json {metric}', int(total[metric]), findings[metric])
        note(f'verification.json {metric}', int(total[metric]), certificate[metric])
    for band in json.loads((SITE / 'plays.json').read_bytes())['sources']['bands']:
        span = seasons.season.between(band['start'], band['end'])
        note(f"plays.json attempts, {band['source']} {band['start']} to {band['end']}", int(seasons[span].attempts.sum()), band['attempts'])

    coverage = pd.read_csv(RESULTS / 'season_coverage.csv')
    merged = seasons.merge(coverage, on=['season', 'phase'], suffixes=('', '_saved'))
    assert len(merged) == len(seasons) == len(coverage)
    pairs = [('attempts', 'attempts_saved'), ('makes', 'makes_saved'), ('points', 'points_saved'), ('mapped_half', 'mapped'),
             ('other_half', 'other_half_saved'), ('unknown_location', 'unknown'), ('games_with_shots', 'recorded_games')]
    for mine, saved in pairs:
        note(f'season_coverage.csv {mine}, season rows that differ', int(merged[mine].ne(merged[saved]).sum()), 0)

    zones = zones.assign(phase=zones.phase.map({'regular': 0, 'playoffs': 1})).set_index(['season', 'phase', 'zone'])[COUNTS]
    saved = pd.read_csv(RESULTS / 'season_zones.csv').rename(columns={'made': 'makes'}).set_index(['season', 'phase', 'zone'])[COUNTS]
    both = zones.join(saved, how='outer', rsuffix='_saved').fillna(0)
    differs = sum(both[m].ne(both[f'{m}_saved']) for m in COUNTS).gt(0)
    note('season_zones.csv, area rows that differ', int(differs.sum()), 0)
    note('season_zones.csv attempts', int(zones.attempts.sum()), int(saved.attempts.sum()))

    def pack_checks(name, read):
        differing = 0
        for year in YEARS:
            shown = pack_totals(read(f'{year}.json'))
            mine = zones.loc[year]
            joined = mine.join(shown, how='outer', rsuffix='_shown').fillna(0)
            differing += int(sum(joined[m].ne(joined[f'{m}_shown']) for m in COUNTS).gt(0).sum())
        note(f'{name} season files, area rows that differ', differing, 0)
        shown = pack_totals(read('all.json'))
        mine = zones.groupby(['phase', 'zone']).sum()
        joined = mine.join(shown, how='outer', rsuffix='_shown').fillna(0)
        note(f'{name} all.json, area rows that differ', int(sum(joined[m].ne(joined[f"{m}_shown"]) for m in COUNTS).gt(0).sum()), 0)
        for metric in COUNTS:
            note(f'{name} all.json {metric}', int(mine[metric].sum()), int(shown[metric].sum()))
        for phase, label in enumerate(PHASES):
            note(f'{name} all.json attempts, {label}', int(mine.loc[phase].attempts.sum()), int(shown.loc[phase].attempts.sum()))

    pack_checks('local site', lambda name: json.loads((SITE / name).read_bytes()))
    if live:
        cache = {}

        def fetch(name):
            if name not in cache:
                request = urllib.request.Request(LIVE + name, headers={'User-Agent': 'wnba-shot-atlas-recount'})
                with urllib.request.urlopen(request, timeout=60) as stream:
                    cache[name] = stream.read()
            return cache[name]

        pack_checks('live site', lambda name: json.loads(fetch(name)))
        names = ['all.json', 'index.json', 'findings.json', *[f'{year}.json' for year in YEARS]]
        head = sum(fetch(name).replace(b'\r\n', b'\n') != subprocess.check_output(
            ['git', 'show', f'HEAD:explore/data/{name}'], cwd=ROOT).replace(b'\r\n', b'\n') for name in names)
        note('live data files that differ from the committed revision', head, 0)
    return pd.DataFrame(checks)


def table(frame):
    cells = frame.map(lambda v: f'{v:,}' if isinstance(v, (int, np.integer)) else str(v))
    head = '| ' + ' | '.join(frame.columns) + ' |\n| ' + ' | '.join('---' for _ in frame.columns) + ' |\n'
    return head + '\n'.join('| ' + ' | '.join(row) + ' |' for row in cells.itertuples(index=False)) + '\n'


def report(seasons, feeds, boxes, excluded, special_games, checks, pins, live):
    total = seasons[COUNTS + ['two_attempts', 'two_makes', 'three_attempts', 'three_makes', 'unknown_value_attempts',
                              'mapped_half', 'other_half', 'unknown_location', 'at_basket_through_2010',
                              'coordinate_pairs_disagree', 'outside_court', 'missing_coordinates', 'games_with_shots',
                              'team_not_in_game', 'team_not_in_game_at_basket']].sum()
    by_phase = seasons.groupby('phase')[['games_with_shots', *COUNTS]].sum().loc[PHASES].reset_index()
    span = pd.cut(seasons.season, [1996, 2001, 2010, 2026], labels=['WNBA Stats 1997 to 2001', 'ESPN 2002 to 2010', 'ESPN 2011 to 2026'])
    by_feed = seasons.groupby(span, observed=True)[['games_with_shots', *COUNTS, 'mapped_half', 'other_half', 'unknown_location']].sum().reset_index(names='feed')
    special = excluded[excluded.phase.eq('special')]
    lines = ['# Recount from the raw files', '',
             f'All {pins[0]} pinned raw files were hashed. {len(pins[1])} differ from the source manifest.', '',
             f"The raw shot files hold {int(total.attempts):,} regular season and playoff field goal attempts, "
             f"{int(total.makes):,} makes and {int(total.points):,} field goal points in {int(total.games_with_shots):,} games with shot records.", '',
             table(by_phase), '## By shot feed', '', table(by_feed), '## Location', '',
             f"{int(total.mapped_half):,} attempts are on the mapped half, {int(total.other_half):,} on the other half and "
             f"{int(total.unknown_location):,} have an unknown location. The unknown group is {int(total.at_basket_through_2010):,} recorded exactly at the basket through 2010, "
             f"{int(total.coordinate_pairs_disagree):,} where the two coordinate pairs disagree, {int(total.outside_court):,} outside the court "
             f"and {int(total.missing_coordinates):,} with missing coordinates.", '',
             f"{int(total.team_not_in_game):,} attempts carry a team ID that is neither the home nor the away team in the schedule, so the two coordinate pairs cannot be matched. "
             f"{int(total.team_not_in_game_at_basket):,} of them sit exactly at the basket in the raw pair and are counted in the first group here. "
             "The published build tests the signed pair first and files all of them under disagreeing pairs. Both routes give the same unknown total.", '',
             table(seasons[seasons.team_not_in_game.gt(0)][['season', 'phase', 'attempts', 'team_not_in_game', 'unknown_location']]),
             '## Attempt value', '',
             f"The source identifies {int(total.two_attempts):,} two point attempts ({int(total.two_makes):,} made) and "
             f"{int(total.three_attempts):,} three point attempts ({int(total.three_makes):,} made). "
             f"{int(total.unknown_value_attempts):,} misses have no recorded value. "
             f"Points check: 2 × {int(total.two_makes):,} + 3 × {int(total.three_makes):,} = {int(2 * total.two_makes + 3 * total.three_makes):,}.", '',
             '## Rows left out of the total', '',
             f"Free throws: {int(feeds.free_throws.sum()):,} rows. Other rows that are not field goals: {int(feeds.other_rows.sum()):,}. "
             f"Special games: {int(special.attempts.sum()):,} attempts in {int(special.games.sum())} games "
             f"({int(special[special.season.ge(2011)].attempts.sum()):,} of them from 2011 on).", '',
             table(excluded.groupby('phase')[['games', 'attempts', 'makes', 'points']].sum().reset_index()),
             '## Scored rows without a shot label', '',
             f"In regular season and playoff games, {int(feeds.scored_rows_without_shot_label.sum())} ESPN rows carry a score value of 2 or 3 "
             f"({int(feeds.points_on_those_rows.sum())} points) under a turnover, foul, not available or no shot label. "
             f"{int(feeds.counted_as_makes_with_box_support.sum())} of them are counted as made baskets in the totals above, because the team box for that game still has that many makes to account for. "
             f"The rest stay out because the box is missing or already matches the labelled makes. "
             f"A further {int(feeds.unscored_rows_without_shot_label.sum())} rows with those labels have a score value of 0 and stay out.", '',
             table(feeds[feeds.scored_rows_without_shot_label.gt(0)][['season', 'scored_rows_without_shot_label', 'points_on_those_rows',
                                                                       'counted_as_makes_with_box_support']].astype(int)),
             '## ESPN team boxes on identical games', '',
             'Games from 2003 on where both teams have a complete box.', '']
    box = boxes.dropna(subset=['box_games']).drop(columns='season').sum().astype(int)
    lines += [table(pd.DataFrame([dict(measure=m, team_boxes=box[f'box_{m}'], shot_feed=box[f'feed_{m}_same_games'],
                                       difference=box[f'feed_{m}_same_games'] - box[f'box_{m}']) for m in COUNTS])),
              f"Box three point makes {box.box_three_makes:,}, shot feed three point makes on the same games {box.feed_three_makes_same_games:,}.", '',
              '## Comparison with published numbers', '',
              'Live site files were ' + ('fetched for this run.' if live else 'not fetched in this run.'), '',
              table(checks)]
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='also compare with the files served by the public page')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    pins = check_pins()
    print(f'{pins[0]} pinned files hashed, {len(pins[1])} differ', flush=True)
    if pins[1]:
        raise SystemExit('Sources differ from their pins: ' + ', '.join(pins[1]))
    seasons, zones, feeds, boxes, excluded, special_games = recount()
    checks = compare(seasons, zones, args.live)
    differences = checks[checks.difference.ne(0)]
    if not differences.empty:
        raise SystemExit('Publication comparison failed:\n' + differences.to_string(index=False))
    seasons.to_csv(OUT / 'season_recount.csv', index=False)
    zones.assign(zone_name=zones.zone.map(dict(enumerate(ZONES))))[['season', 'phase', 'zone', 'zone_name', *COUNTS]].to_csv(OUT / 'zone_recount.csv', index=False)
    feeds.to_csv(OUT / 'feed_rows.csv', index=False)
    boxes.to_csv(OUT / 'team_box_check.csv', index=False)
    excluded.to_csv(OUT / 'excluded_attempts.csv', index=False)
    special_games.to_csv(OUT / 'special_games.csv', index=False)
    checks.to_csv(OUT / 'published_comparison.csv', index=False)
    report(seasons, feeds, boxes, excluded, special_games, checks, pins, args.live)
    total = seasons[COUNTS].sum()
    print(f"RECOUNT {int(total.attempts):,} attempts, {int(total.makes):,} makes, {int(total.points):,} points, "
          f"{int(seasons.games_with_shots.sum()):,} games", flush=True)
    print(f"PUBLISHED_COMPARISON {int(checks.difference.ne(0).sum())} of {len(checks)} checks differ", flush=True)
    print(checks[checks.difference.ne(0)].to_string(index=False) if checks.difference.ne(0).any() else 'No differences', flush=True)


if __name__ == '__main__':
    main()
