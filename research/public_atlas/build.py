"""Create traceable shot tables, audit reports, and small season files for the explorer."""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from fetch import CACHE, PIN, RAW, ROOT, YEARS, file_matches, manifest_digest
from geometry import BASELINE, CELL_FT, COLS, MIDCOURT, ROWS, RULES, ZONES, era_for, locate, locations

RESULTS = ROOT / 'research/results/public_atlas'
SITE = ROOT / 'explore/data'
DERIVED = CACHE / 'derived'
PHASE = {'regular': 0, 'playoffs': 1}
SHOOTING = r'jump|shot|lay.?up|dunk|tip|hook|alley|pointer|heave'
OTHER_TYPE = r'noshot|turnover|notavailable|foul|violation'
BOX_FIELDS = ['field_goals_attempted', 'field_goals_made', 'three_point_field_goals_made', 'three_point_field_goals_attempted']
COUNTS = ['attempts', 'makes', 'points']
SHOT_TYPES = ('Jump shot', 'Layup', 'Hook shot', 'Floater or runner', 'Tip shot', 'Dunk', 'Other field goal')
GROUP_COLUMNS = ['phase', 'team_id', 'player_id', 'cell', 'zone']
PACK_COLUMNS = [*GROUP_COLUMNS, 'attempts', 'made', 'points', 'shot_type']
# Two exhibition games have an incomplete description in this provider snapshot.
SPECIAL_GAMES = {401353913: '2021 Commissioner’s Cup final', 401558893: '2023 All Star Game'}
DUPLICATE_2011 = (310604005, 400182104)
# The 2002 schedule lists the Portland Fire as team 12. The shot and player files use 132052.
SCHEDULE_TEAM_IDS = {2002: {12: 132052}}


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
    for listed, recorded in SCHEDULE_TEAM_IDS.get(year, {}).items():
        sides = games[['home_id', 'away_id']]
        assert sides.eq(listed).any().any() and not sides.eq(recorded).any().any()
        games[['home_id', 'away_id']] = sides.replace(listed, recorded)
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


def shot_family(labels):
    compact = labels.fillna('').str.lower().str.replace(r'[^a-z]', '', regex=True)
    return np.select([compact.str.contains('dunk'), compact.str.contains(r'layup|fingerroll'),
                      compact.str.contains('hook'), compact.str.contains(r'float|runner|runningbank'),
                      compact.str.contains(r'tipshot|tipin|putback'), compact.str.contains(r'jump|threepoint')],
                     [5, 1, 2, 3, 4, 0], default=6).astype('int8')


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
    attempts['shot_type'] = shot_family(attempts.type_text)
    attempts = locations(attempts, era_for(year), zero_is_missing=year <= 2010)
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


def crosswalk(kind, input_id, output_id, label):
    paths = [RAW / row['filename'] for row in json.loads(PIN.read_bytes())
             if row['filename'].startswith(f'wnba_{kind}_crosswalk_')]
    need = [input_id, output_id, label, 'match_confidence']
    rows = pd.concat([pd.read_csv(path, usecols=need, low_memory=False) for path in paths])
    rows = rows.dropna(subset=[input_id, output_id])
    rows = rows[rows.match_confidence.ge(.99)]
    stable = rows.groupby(input_id)[output_id].nunique().eq(1)
    rows = rows[rows[input_id].isin(stable[stable].index)].drop_duplicates(input_id)
    return rows.set_index(input_id)[[output_id, label]]


def official_field_goals(raw, year, identities):
    """Keep the official shot value and observed result separate from geometry."""
    raw['record_kind'] = np.where(raw.shot_value.isin([2, 3]) & raw.shot_result.isin(['Made', 'Missed']),
                                  'field goal', 'ambiguous')
    frame = raw[raw.record_kind.eq('field goal')].copy()
    frame['source_row'] = frame.index + 2
    frame['season'] = year
    game_code = frame.game_id.astype(str).str[2]
    assert game_code.isin(['2', '4']).all(), game_code.unique()
    frame['scope'] = game_code.map({'2': 'regular', '4': 'playoffs'})
    players, teams = identities
    frame['player_id'] = frame.person_id.map(players.espn_athlete_id).fillna(frame.person_id).astype('int64')
    frame['athlete_name_1'] = frame.person_id.map(players.espn_full_name).fillna(frame.player_name)
    frame['team_name'] = frame.team_id.map(teams.espn_display_name).fillna(frame.team_tricode)
    frame['team_id'] = frame.team_id.map(teams.espn_team_id).fillna(frame.team_id).astype('int64')
    frame['attempt_value'] = frame.shot_value.astype('Int8')
    frame['attempt_value_evidence'] = 'WNBA Stats shot value'
    frame['made'] = frame.shot_result.eq('Made').astype('int8')
    frame['points'] = frame.made * frame.shot_value
    frame['attempts'] = 1
    frame['shot_type'] = shot_family(frame.sub_type)
    frame['repeated_record'] = raw.drop(columns='record_kind').duplicated(keep=False).loc[frame.index]
    frame['scoring_flag_disagrees'] = False
    frame['period_number'] = frame.period
    frame['clock_display_value'] = frame.clock
    depth, lateral = frame.y_legacy.to_numpy(dtype=float) / 10, frame.x_legacy.to_numpy(dtype=float) / 10
    return locate(frame, era_for(year), depth, lateral, np.ones(len(frame), dtype=bool), True)


def export_season(year, identities):
    early = year < 2002
    raw = source('official_shots' if early else 'shots', year)
    assert raw.game_id.notna().all()
    if early:
        assert raw.team_id.notna().all()
        shots = official_field_goals(raw, year, identities)
        games = shots[['game_id', 'season', 'scope']].drop_duplicates()
        for name in ('game_date', 'home_id', 'away_id', 'status_type_name', 'notes_headline'):
            games[name] = None
        players = pd.DataFrame(columns=['game_id', 'team_id', 'player_id', 'athlete_display_name', *BOX_FIELDS])
    else:
        games = games_for(year)
        for listed, recorded in SCHEDULE_TEAM_IDS.get(year, {}).items():
            assert raw.team_id.eq(recorded).any() and not raw.team_id.eq(listed).any()
        shots = field_goals(raw, games, year)
        players = source('player_box', year).rename(columns={'athlete_id': 'player_id'})
    teams = (source('team_box', year) if year >= 2003 else
             pd.DataFrame(columns=['game_id', 'team_id', 'team_display_name', *BOX_FIELDS]))
    shots['team_id'] = shots.team_id.fillna(0).astype('int64')
    teams_check = reconcile(shots, teams, ['game_id', 'team_id'])
    players_check = reconcile(shots[shots.player_id.ne(0)], players, ['game_id', 'team_id', 'player_id'])
    missing_schedule = sorted(set(raw.game_id) - set(games.game_id))
    audit = {'season': year, 'source_rows': len(raw), 'candidate_attempts': len(shots),
             'free_throws': int(raw.record_kind.eq('free throw').sum()), 'ambiguous_rows': int(raw.record_kind.eq('ambiguous').sum()),
             'repeated_rows': int(shots.repeated_record.sum()), 'scoring_flag_conflicts': int(shots.scoring_flag_disagrees.sum()),
             'missing_player': int(shots.player_id.eq(0).sum()),
             'missing_team': int(shots.team_id.eq(0).sum()), 'unknown_game_ids': missing_schedule,
             'recorded_scope_counts': {str(k):int(v) for k,v in shots.scope.value_counts().items()},
             'schedule_scope_counts': {str(k):int(v) for k,v in games.scope.value_counts().items()},
             'source': 'WNBA Stats' if early else 'ESPN',
             'origin_placeholders': int(shots.location_status.eq('provider_origin_placeholder').sum())}
    for phase in PHASE:
        audit[phase] = phase_coverage(games, shots, teams_check, players_check, phase)
        if early:
            audit[phase]['scheduled_games'] = None
            audit[phase]['through'] = None
    assert audit['source_rows'] == sum(audit[k] for k in ['free_throws','candidate_attempts','ambiguous_rows'])

    data = shots[shots.scope.isin(PHASE)].copy()
    data['phase'] = data.scope.map(PHASE)
    names = choose_names(shots, 'player_id', 'athlete_name_1')
    for key, value in choose_names(players, 'player_id', 'athlete_display_name').items():
        names.setdefault(key, value)
    teams_names = choose_names(teams, 'team_id', 'team_display_name')
    for key, value in choose_names(shots, 'team_id', 'team_name').items():
        teams_names.setdefault(key, value)
    groups = data.groupby([*GROUP_COLUMNS, 'shot_type'], as_index=False)[['attempts','made','points']].sum()
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
    shots.drop(columns=['athlete_name_2','team_mascot'], errors='ignore').to_csv(DERIVED / f'shots_{year}.csv.gz', index=False)
    raw[raw.record_kind.ne('field goal')].to_csv(DERIVED / f'other_records_{year}.csv.gz', index_label='source_index')
    players_summary.to_csv(DERIVED / f'player_zones_{year}.csv.gz', index=False)
    players_check.assign(season=year).to_csv(DERIVED / f'player_game_audit_{year}.csv.gz', index=False)
    pack = dict(season=year, court=era_for(year)['id'], coverage=audit,
                players={str(i):names.get(str(i), 'Unknown shooter') for i in sorted(data.player_id.unique())},
                teams={str(i):teams_names.get(str(i), 'Unknown team' if i == 0 else str(i)) for i in sorted(data.team_id.unique())},
                rows=groups[PACK_COLUMNS].to_numpy(dtype=int).tolist())
    write_json(SITE / f'{year}.json', pack)
    print(f"{year}: {len(data):,} attempts, {data.cell.ge(0).sum():,} mapped", flush=True)
    league = groups.groupby(['phase', 'cell', 'zone'], as_index=False)[['attempts', 'made', 'points']].sum()
    league.insert(1, 'team_id', 0)
    league.insert(2, 'player_id', 0)
    return audit, summary, teams_check.assign(season=year), league.to_numpy(dtype=int).tolist(), groups, pack


def build(years):
    sources = json.loads(PIN.read_bytes())
    for row in sources:
        if (row['season'] in years or 'crosswalk' in row['filename']) and not file_matches(RAW / row['filename'], row):
            raise ValueError(f"Input missing or changed: {row['filename']}. Restore the pinned files with fetch.py.")
    for path in (RESULTS, DERIVED):
        path.mkdir(parents=True, exist_ok=True)
    identities = (crosswalk('player', 'wnba_player_id', 'espn_athlete_id', 'espn_full_name'),
                  crosswalk('team', 'wnba_team_id', 'espn_team_id', 'espn_display_name'))
    batches = [export_season(year, identities) for year in years]
    coverage = [batch[0] for batch in batches]
    pd.concat([batch[1] for batch in batches]).to_csv(RESULTS / 'season_zones.csv', index=False)
    pd.concat([batch[2] for batch in batches]).to_csv(RESULTS / 'team_game_audit.csv', index=False)
    pd.DataFrame([{'season': row['season'], 'phase': phase, **row[phase]} for row in coverage for phase in PHASE]).to_csv(
        RESULTS / 'season_coverage.csv', index=False)
    all_rows = pd.concat([batch[4] for batch in batches]).groupby(
        [*GROUP_COLUMNS, 'shot_type'], as_index=False)[['attempts', 'made', 'points']].sum()
    players, team_history = {}, {}
    for batch in batches:
        pack = batch[5]
        players.update(pack['players'])
        for team, name in pack['teams'].items():
            team_history.setdefault(team, {})[name] = None
    # Names in this view reflect the provider team IDs and their name history.
    team_labels = {team: ' / '.join(names) for team, names in team_history.items()}
    pooled = {phase: {metric: sum(row[phase][metric] or 0 for row in coverage)
              for metric in ('recorded_games', 'matched_team_games', 'attempts', 'unknown')} for phase in PHASE}
    write_json(SITE / 'all.json', dict(season='all', court='all', coverage=pooled,
                                          teams=team_labels, players=players,
                                          rows=all_rows[PACK_COLUMNS].to_numpy(dtype=int).tolist()))
    write_json(SITE / 'index.json', dict(seasons=years, court=RULES, zones=ZONES, shotTypes=SHOT_TYPES, coverage=coverage,
                                       grid=dict(baseline=BASELINE, midcourt=MIDCOURT, size=CELL_FT, cols=COLS, rows=ROWS),
                                       source='wehoop / ESPN and WNBA Stats', files=len(sources),
                                       leagueHistory={str(year): batch[3] for year, batch in zip(years, batches)},
                                       manifestSha256=manifest_digest()))
    print('PUBLIC_ATLAS_BUILT', len(years), 'seasons', int(all_rows.attempts.sum()), 'attempts', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seasons', nargs='+', type=int, choices=YEARS, default=YEARS)
    args = parser.parse_args()
    build(sorted(set(args.seasons)))
