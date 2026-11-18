"""Trace the next rebound and subsequent scoring for eligible missed shots."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'research/data/data1/possession'
SPLITS = ('validation', 'test', 'playoffs')


def read_reconstruction(name):
    with gzip.open(PRIVATE / f'{name}.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def read_original_events(archive):
    with zipfile.ZipFile(archive) as source:
        name = next(name for name in source.namelist() if name.endswith('/original/wehoop_wnba_pbp.csv'))
        with io.TextIOWrapper(source.open(name), encoding='utf-8-sig', newline='') as stream:
            return dict(enumerate(csv.DictReader(stream), start=2))


def checked_ledger(original):
    ledger = read_reconstruction('event_ledger')
    positions = {int(event['source_row']): i for i, event in enumerate(ledger)}
    assert len(ledger) == len(positions) == len(original) and positions.keys() == original.keys()
    previous = None
    for event in ledger:
        row = int(event['source_row'])
        record = original[row]
        for field in ('game_id', 'period_number', 'type_id'):
            assert int(record[field]) == int(event[field]), (row, field)
        assert int(float(record['score_value'])) == int(event['points']), row
        if event['team_id']:
            assert float(record['team_id']) == float(event['team_id']), row
        order = (int(record['game_id']), int(record['period_number']), int(record['game_play_number']), row)
        assert previous is None or previous < order, row
        previous = order
    return ledger, positions


def rebound_branch(events, miss):
    for event in events:
        if event['type_id'] == '155':
            assert int(float(event['team_id'])) == int(miss['defense_team_id'])
            return 'defense'
        if event['type_id'] == '156' and event['reward_lane'] != 'dead_ball_rebound':
            assert event['episode_id'] == miss['episode_id']
            assert int(float(event['team_id'])) == int(miss['offense_team_id'])
            return 'offense'
        if event['reward_lane'] == 'ordinary':
            break  # A shot or free throw intervened before a rebound.
    return 'other'


def summarize(archive, site):
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    expected = site['possessionValue']['audit']['archive_sha256']
    assert archive.name == 'Data (1).zip' and digest == expected == site['selection']['source_archive_sha256']
    original = read_original_events(archive)
    ledger, positions = checked_ledger(original)
    episodes = {row['episode_id']: row for row in read_reconstruction('all_episodes')}
    splits = {split: dict(misses=0, offense=0, defense=0, other=0, offense_scored=0, points=0) for split in SPLITS}
    seen = set()
    for miss in read_reconstruction('model_states'):
        if miss['split'] not in splits or miss['stage'] != 'after_miss':
            continue
        row = int(miss['source_row'])
        assert row not in seen
        seen.add(row)
        start = positions[row]
        event, record = ledger[start], original[row]
        assert event['episode_id'] == miss['episode_id'] and event['reward_lane'] == 'ordinary'
        assert record['shooting_play'].lower() == 'true' and 'free throw' not in record['type_text'].lower()
        assert float(event['team_id']) == int(miss['offense_team_id']) and int(event['points']) == 0
        episode = episodes[miss['episode_id']]
        assert episode['eligible'] == 'True' and float(miss['seconds_remaining']) > 2
        end = positions[int(episode['end_source_row'])]
        assert start <= end and event['game_id'] == ledger[end]['game_id']
        assert event['period_number'] == ledger[end]['period_number']
        following = ledger[start + 1:end + 1]
        branch = rebound_branch(following, miss)
        points = sum(int(play['points']) for play in following
                     if play['episode_id'] == miss['episode_id'] and play['reward_lane'] == 'ordinary')
        assert points == int(miss['remaining_points']) and (branch != 'defense' or points == 0)
        counts = splits[miss['split']]
        counts['misses'] += 1
        counts[branch] += 1
        counts['offense_scored'] += int(branch == 'offense' and points > 0)
        counts['points'] += points
    for split, counts in splits.items():
        summary = [row for row in site['possessionValue']['summary']
                   if row['split'] == split and row['stage'] == 'after_miss']
        assert counts['misses'] == counts['offense'] + counts['defense'] + counts['other']
        assert counts['misses'] == sum(row['states'] for row in summary)
        assert math.isclose(counts['points'], sum(row['states'] * row['mean_observed'] for row in summary))
        print(split, counts)
    return {'source': {'only_data_source': 'Data (1).zip', 'archive_sha256': digest}, 'splits': splits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--check', action='store_true', help='Verify the published aggregate without rewriting it')
    args = parser.parse_args()
    site = json.loads((ROOT / 'assets/data.json').read_bytes())
    result = summarize(args.source, site)
    output = ROOT / 'assets/miss_outcomes.json'
    if args.check:
        assert json.loads(output.read_bytes()) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='')
    print('Miss outcomes and total points agree with the original archive and verified sample.')


if __name__ == '__main__':
    main()
