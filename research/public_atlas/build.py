"""Create traceable shot tables, audit reports, and small season files for the explorer."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from fetch import CACHE, HERE, PIN, RAW, ROOT, YEARS, file_matches, manifest_digest
from geometry import BASELINE, CELL_FT, COLS, MIDCOURT, ROWS, RULES, ZONES, era_for, locations

RESULTS = ROOT / 'research/results/public_atlas'
SITE = ROOT / 'explore/data'
DERIVED = CACHE / 'derived'
PHASE = {'regular': 0, 'playoffs': 1}
SHOOTING = r'jump|shot|lay.?up|dunk|tip|hook|alley|pointer|heave'
OTHER_TYPE = r'noshot|turnover|notavailable|foul|violation'
BOX_FIELDS = ['field_goals_attempted', 'field_goals_made', 'three_point_field_goals_made', 'three_point_field_goals_attempted']
COUNTS = ['attempts', 'makes', 'points']
# Two exhibition games have an incomplete description in this provider snapshot.
SPECIAL_GAMES = {401353913: '2021 Commissioner’s Cup final', 401558893: '2023 All Star Game'}
DUPLICATE_2011 = (310604005, 400182104)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8', newline='')
    temp.replace(path)


def source(kind, year):
    rows = pd.read_csv(RAW / f'{kind}_{year}.csv', low_memory=False)
    assert rows.season.eq(year).all(), (kind, year)
    return rows


def games_for(year):
    games = source('wnba_schedule', year)
    assert games.game_id.is_unique and games[['home_id', 'away_id', 'game_id', 'game_date']].notna().all().all()
    assert games.home_id.ne(games.away_id).all()
    notes = games.notes_headline.fillna('').str.lower()
    special = (notes.str.contains(r'all\W*star|cup championship|cup final|exhibition', regex=True)
               | games.game_id.isin(SPECIAL_GAMES))
    listed = games.season_type.isin([2, 3])
    final = games.status_type_name.eq('STATUS_FINAL') & games.status_type_completed.eq(True)
    games['scope'] = np.select([~final, special, listed & games.season_type.eq(2), listed & games.season_type.eq(3)],
                               ['not played', 'special', 'regular', 'playoffs'], default='other')
    if year == 2011 and set(DUPLICATE_2011).issubset(games.game_id):
        original, duplicate = games.set_index('game_id').loc[list(DUPLICATE_2011)].itertuples()
        for attr in ('game_date', 'home_id', 'away_id', 'home_score', 'away_score'):
            assert getattr(original, attr) == getattr(duplicate, attr), attr
        assert original.PBP and not duplicate.PBP
        games.loc[games.game_id.eq(DUPLICATE_2011[1]), 'scope'] = 'duplicate schedule'
    return games


def field_goals(raw, games, year):
    compact = raw.type_text.fillna('').str.lower().str.replace(r'[^a-z]', '', regex=True)
    points = pd.to_numeric(raw.score_value, errors='coerce')
    free_throw = compact.str.contains('freethrow')
    shot_type = compact.str.contains(SHOOTING) & ~compact.str.contains(OTHER_TYPE)
    valid_reward = points.isin([0, 2, 3])
    field_goal = ~free_throw & shot_type & valid_reward
    raw['record_kind'] = np.select([free_throw, field_goal], ['free throw', 'field goal'], default='ambiguous')
    attempts = raw.loc[field_goal].copy()
    attempts['points'] = points.loc[field_goal].astype('int8')
    attempts['made'] = attempts.points.gt(0).astype('int8')
    attempts['scoring_flag_disagrees'] = ~attempts.scoring_play.eq(attempts.made.eq(1))
    attempts['attempt_value'] = pd.Series(pd.NA, index=attempts.index, dtype='Int8')
    attempts['attempt_value_evidence'] = 'unknown'
    two = compact.loc[field_goal].str.contains('twopoint')
    three = compact.loc[field_goal].str.contains('threepoint|threepointer')
    attempts.loc[two, 'attempt_value'] = 2
    attempts.loc[three, 'attempt_value'] = 3
    attempts.loc[two | three, 'attempt_value_evidence'] = 'type text'
    attempts['type_value_disagrees'] = attempts.made.eq(1) & attempts.attempt_value.notna() & attempts.attempt_value.ne(attempts.points)
    made = attempts.made.eq(1)
    attempts.loc[made, 'attempt_value'] = attempts.loc[made, 'points']
    attempts.loc[made, 'attempt_value_evidence'] = 'points scored'
    attempts['player_id'] = pd.to_numeric(attempts.athlete_id_1, errors='coerce').fillna(0).astype('int64')
    attempts['source_row'] = attempts.index + 2
    attempts['repeated_record'] = raw.drop(columns='record_kind').duplicated(keep=False).loc[field_goal]
    attempts = attempts.merge(games[['game_id', 'game_date', 'scope', 'home_id', 'away_id']], on='game_id', how='left', validate='many_to_one')
    attempts['scope'] = attempts.scope.fillna('unknown game')
    attempts['attempts'] = 1
    attempts = locations(attempts, era_for(year))
    return attempts


def expected_counts(boxes, ids):
    assert not boxes.duplicated(ids).any(), ids
    expected = boxes[ids + BOX_FIELDS].copy()
    expected[BOX_FIELDS] = expected[BOX_FIELDS].apply(pd.to_numeric, errors='coerce')
    expected['box_attempts'] = expected.field_goals_attempted
    expected['box_makes'] = expected.field_goals_made
    expected['box_points'] = 2 * expected.field_goals_made + expected.three_point_field_goals_made
    expected['box_three_attempts'] = expected.three_point_field_goals_attempted
    return expected.drop(columns=BOX_FIELDS)


def reconcile(observed, boxes, ids):
    observed = observed.groupby(ids, as_index=False)[['attempts', 'made', 'points']].sum().rename(columns={'made': 'makes'})
    audit = observed.merge(expected_counts(boxes, ids), how='outer', on=ids, validate='one_to_one', indicator=True)
    differs = pd.Series(False, index=audit.index)
    for metric in COUNTS:
        audit[f'{metric}_difference'] = audit[metric].fillna(0) - audit[f'box_{metric}']
        differs |= audit[f'{metric}_difference'].ne(0)
    valid_box = audit[[f'box_{metric}' for metric in COUNTS]].notna().all(axis=1)
    audit['status'] = np.select([~valid_box, audit._merge.eq('right_only') & differs, differs],
                                ['box unavailable', 'no recorded attempts', 'counts differ'], default='matches')
    return audit.drop(columns='_merge')


def choose_names(frame, key, column):
    names = frame[[key, column]].dropna().copy()
    names[column] = names[column].astype(str).str.strip()
    counts = names[names[column].ne('')].value_counts([key, column]).rename('n').reset_index()
    counts = counts.sort_values(['n', column], ascending=[False, True]).drop_duplicates(key)
    return {str(int(row[0])): row[1] for row in counts[[key, column]].itertuples(index=False, name=None)}


def phase_coverage(games, shots, team_audit, player_audit, phase):
    official = games[games.scope.eq(phase)]
    seen = shots[shots.scope.eq(phase)]
    selected_teams = team_audit[team_audit.game_id.isin(official.game_id)]
    selected_players = player_audit[player_audit.game_id.isin(official.game_id)]
    complete_boxes = selected_teams[selected_teams.status.eq('matches')].groupby('game_id').size()
    matched = int(complete_boxes.eq(2).sum())
    return dict(scheduled_games=len(official), recorded_games=int(seen.game_id.nunique()),
                through=str(official.game_date.max()) if len(official) else None,
                matched_team_games=matched, matched_team_boxes=int(selected_teams.status.eq('matches').sum()),
                checked_team_boxes=int(selected_teams.box_attempts.notna().sum()),
                player_disagreements=int(selected_players.status.isin(['counts differ', 'no recorded attempts']).sum()),
                attempts=len(seen), makes=int(seen.made.sum()), points=int(seen.points.sum()),
                mapped=int(seen.cell.ge(0).sum()), other_half=int(seen.cell.eq(-2).sum()),
                unknown=int(seen.cell.eq(-1).sum()),
                near_line=int(seen.near_three_line.sum()), line_disagreements=int(seen.shot_location_disagrees.sum()))


def compare_archive(path, public):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    receipt = json.loads((ROOT / 'research/results/archive_audit.json').read_bytes())
    if path.name != 'Data (1).zip' or digest != receipt['source_sha256']:
        raise ValueError('Expected the verified Data (1).zip in Downloads')
    with zipfile.ZipFile(path) as archive:
        key, = (name for name in archive.namelist() if name.endswith('/original/wehoop_wnba_pbp.csv'))
        with archive.open(key) as stream:
            events = pd.read_csv(stream, low_memory=False)
    original = events[events.shooting_play.eq(True) & ~events.type_text.str.contains(r'free\s*throw', case=False, na=False)]
    columns = ['game_id', 'period_number', 'clock_display_value', 'team_id', 'athlete_id_1',
               'type_id', 'score_value', 'coordinate_x', 'coordinate_y', 'scoring_play']
    def counts(frame):
        values = frame[columns].copy()
        for name in ['coordinate_x', 'coordinate_y']:
            values[name] = values[name].round(6)
        return Counter(values.fillna('').itertuples(index=False, name=None))
    left, right = counts(original), counts(public)
    a = original.groupby(['game_id', 'team_id']).score_value.agg(attempts='size', points='sum')
    b = public.groupby(['game_id', 'team_id']).score_value.agg(attempts='size', points='sum')
    group = a.join(b, how='outer', lsuffix='_archive', rsuffix='_public')
    mismatch = group.attempts_archive.ne(group.attempts_public) | group.points_archive.ne(group.points_public)
    group.loc[mismatch].to_csv(RESULTS / '2025_archive_game_differences.csv')
    return dict(archive_sha256=digest, archive_attempts=len(original), public_attempts=len(public),
                shared_games=len(set(original.game_id) & set(public.game_id)), exact_shots=sum((left & right).values()),
                archive_only=sum((left - right).values()), public_only=sum((right - left).values()),
                different_game_team=int(mismatch.sum()))


def export_season(year, archive):
    raw = source('shots', year)
    games = games_for(year)
    teams = source('team_box', year)
    players = source('player_box', year).rename(columns={'athlete_id': 'player_id'})
    assert raw.game_id.notna().all() and raw.team_id.notna().all()
    shots = field_goals(raw, games, year)
    teams_check = reconcile(shots, teams, ['game_id', 'team_id'])
    players_check = reconcile(shots[shots.player_id.ne(0)], players, ['game_id', 'team_id', 'player_id'])
    missing_schedule = sorted(set(raw.game_id) - set(games.game_id))
    audit = {'season': year, 'source_rows': len(raw), 'candidate_attempts': len(shots),
             'free_throws': int(raw.record_kind.eq('free throw').sum()), 'ambiguous_rows': int(raw.record_kind.eq('ambiguous').sum()),
             'repeated_rows': int(shots.repeated_record.sum()), 'scoring_flag_conflicts': int(shots.scoring_flag_disagrees.sum()),
             'missing_player': int(shots.player_id.eq(0).sum()), 'unknown_game_ids': missing_schedule,
             'recorded_scope_counts': {str(k):int(v) for k,v in shots.scope.value_counts().items()},
             'schedule_scope_counts': {str(k):int(v) for k,v in games.scope.value_counts().items()}}
    for phase in PHASE:
        audit[phase] = phase_coverage(games, shots, teams_check, players_check, phase)
    assert audit['source_rows'] == sum(audit[k] for k in ['free_throws','candidate_attempts','ambiguous_rows'])

    data = shots[shots.scope.isin(PHASE)].copy()
    data['phase'] = data.scope.map(PHASE)
    names = choose_names(shots, 'player_id', 'athlete_name_1')
    for key, value in choose_names(players, 'player_id', 'athlete_display_name').items():
        names.setdefault(key, value)
    teams_names = choose_names(teams, 'team_id', 'team_display_name')
    for key, value in choose_names(shots, 'team_id', 'team_name').items():
        teams_names.setdefault(key, value)
    groups = data.groupby(['phase','team_id','player_id','cell','zone'], as_index=False)[['attempts','made','points']].sum()
    assert groups.attempts.sum() == len(data) and groups.made.sum() == data.made.sum() and groups.points.sum() == data.points.sum()
    summary = groups.groupby(['phase', 'zone'], as_index=False)[['attempts','made','points']].sum()
    summary['season'] = year
    summary['zone_name'] = summary.zone.map(dict(enumerate(ZONES)))
    summary['fg_pct'] = summary.made / summary.attempts
    summary['points_per_attempt'] = summary.points / summary.attempts
    players_summary = groups.groupby(['phase', 'team_id','player_id','zone'], as_index=False)[['attempts','made','points']].sum()
    players_summary['season'] = year
    players_summary['fg_pct'] = players_summary.made / players_summary.attempts
    players_summary['points_per_attempt'] = players_summary.points / players_summary.attempts
    teams_check = teams_check.merge(games[['game_id','scope']], on='game_id', how='left', validate='many_to_one')
    players_check = players_check.merge(games[['game_id','scope']], on='game_id', how='left', validate='many_to_one')
    games[['game_id','season','game_date','home_id','away_id','status_type_name','notes_headline','scope']].to_csv(DERIVED / f'games_{year}.csv', index=False)
    shots.drop(columns=['athlete_name_2','team_mascot']).to_csv(DERIVED / f'shots_{year}.csv.gz', index=False)
    raw[raw.record_kind.ne('field goal')].to_csv(DERIVED / f'other_records_{year}.csv.gz', index_label='source_index')
    players_summary.to_csv(DERIVED / f'player_zones_{year}.csv.gz', index=False)
    players_check.assign(season=year).to_csv(DERIVED / f'player_game_audit_{year}.csv.gz', index=False)
    write_json(SITE / f'{year}.json', dict(season=year, court=era_for(year)['id'], coverage=audit,
                                          players={str(i):names.get(str(i), 'Unknown shooter') for i in sorted(data.player_id.unique())},
                                          teams={str(i):teams_names.get(str(i), str(i)) for i in sorted(data.team_id.unique())},
                                          rows=groups.to_numpy(dtype=int).tolist()))
    print(f"{year}: {audit['regular']['recorded_games']}/{audit['regular']['scheduled_games']} regular games with shots, "
          f"{audit['regular']['attempts']:,} attempts, {audit['regular']['matched_team_games']} games match both team boxes", flush=True)
    crosscheck = compare_archive(archive, shots) if archive and year == 2025 else None
    league = groups.groupby(['phase', 'cell', 'zone'], as_index=False)[['attempts', 'made', 'points']].sum()
    league.insert(1, 'team_id', 0)
    league.insert(2, 'player_id', 0)
    return audit, summary, teams_check.assign(season=year), crosscheck, league.to_numpy(dtype=int).tolist()


def build(years, archive):
    sources = json.loads(PIN.read_bytes())
    for row in sources:
        if row['season'] in years and not file_matches(RAW / row['filename'], row):
            raise ValueError(f"Input missing or changed: {row['filename']}. Restore the pinned files with fetch.py.")
    assert len([row for row in sources if row['season'] in years]) == 4 * len(years)
    for path in (RESULTS, DERIVED):
        path.mkdir(parents=True, exist_ok=True)
    batches = [export_season(year, archive) for year in years]
    coverage = [batch[0] for batch in batches]
    pd.concat([batch[1] for batch in batches]).to_csv(RESULTS / 'season_zones.csv', index=False)
    team_audit = pd.concat([batch[2] for batch in batches])
    team_audit.to_csv(RESULTS / 'team_game_audit.csv', index=False)
    pd.DataFrame([{'season': row['season'], 'phase': phase, **row[phase]} for row in coverage for phase in PHASE]).to_csv(RESULTS / 'season_coverage.csv', index=False)
    crosscheck = next((batch[3] for batch in batches if batch[3] is not None), None)
    if crosscheck:
        write_json(RESULTS / '2025_archive_comparison.json', crosscheck)
    write_json(SITE / 'index.json', dict(seasons=years, court=RULES, zones=ZONES, coverage=coverage,
                                       grid=dict(baseline=BASELINE, midcourt=MIDCOURT, size=CELL_FT, cols=COLS, rows=ROWS),
                                       source='wehoop / ESPN', files=4 * len(years), archiveComparison=crosscheck,
                                       leagueHistory={str(year): batch[4] for year, batch in zip(years, batches)},
                                       manifestSha256=manifest_digest()))
    print('PUBLIC_ATLAS_BUILT', len(years), 'seasons', sum(row['source_rows'] for row in coverage), 'shot release rows', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seasons', nargs='+', type=int, choices=YEARS, default=YEARS)
    parser.add_argument('--archive', type=Path, required=True, help='Path to the original Data (1).zip for the 2025 comparison')
    args = parser.parse_args()
    build(sorted(set(args.seasons)), args.archive)
