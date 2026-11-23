"""Compare ESPN shot totals with the WNBA Stats shot feed on game IDs joined by wehoop."""
import argparse
import json

import pandas as pd

from build import DERIVED, RESULTS, write_json
from fetch import CACHE, HERE, download, file_digest, file_matches

REFERENCE = CACHE / 'official_reference'
PIN = HERE / 'reference_manifest.json'
BASE = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/'
FIELDS = ['attempts', 'makes', 'points']


def reference_sources(snapshot):
    REFERENCE.mkdir(parents=True, exist_ok=True)
    if snapshot:
        rows = []
        for year in (2025, 2026):
            for tag, name in [('wnba_stats_shots', f'shots_{year}.csv'),
                              ('wnba_crosswalk', f'wnba_schedule_crosswalk_{year}.csv')]:
                url = BASE + f'{tag}/{name}'
                target = REFERENCE / name
                target.write_bytes(download(url))
                rows.append(dict(season=year, filename=name, url=url, sha256=file_digest(target),
                                 bytes=target.stat().st_size))
        write_json(PIN, rows)
    for row in json.loads(PIN.read_bytes()):
        target = REFERENCE / row['filename']
        if not target.exists():
            raw = download(row['url'])
            temporary = target.with_suffix('.part')
            temporary.write_bytes(raw)
            assert file_matches(temporary, row), row['filename']
            temporary.replace(target)
        assert file_matches(target, row), row['filename']


def compare(year):
    stats = pd.read_csv(REFERENCE / f'shots_{year}.csv')
    assert stats.season.eq(year).all()
    stats = stats[stats.shot_result.isin(['Made', 'Missed']) & stats.shot_value.isin([2, 3])].copy()
    stats['scope'] = stats.game_id.astype(str).str[2].map({'2': 'regular', '4': 'playoffs'})
    stats['makes'] = stats.shot_result.eq('Made').astype(int)
    stats['points'] = stats.makes * stats.shot_value
    stats['attempts'] = 1
    espn = pd.read_csv(DERIVED / f'shots_{year}.csv.gz',
                       usecols=['game_id', 'scope', 'attempts', 'made', 'points']).rename(columns={'made': 'makes'})
    xwalk = pd.read_csv(REFERENCE / f'wnba_schedule_crosswalk_{year}.csv')
    xwalk = xwalk[xwalk.match_confidence.eq(1)].dropna(subset=['espn_game_id', 'wnba_game_id'])
    assert xwalk.espn_game_id.is_unique and xwalk.wnba_game_id.is_unique
    groups = []
    summaries = []
    for phase in ('regular', 'playoffs'):
        e = espn[espn.scope.eq(phase)].groupby('game_id')[FIELDS].sum()
        w = stats[stats.scope.eq(phase)].groupby('game_id')[FIELDS].sum()
        match = xwalk[['espn_game_id', 'wnba_game_id']].merge(e, left_on='espn_game_id', right_index=True)
        match = match.merge(w, left_on='wnba_game_id', right_index=True, suffixes=('_espn', '_wnba'))
        for name in FIELDS:
            match[name + '_difference'] = match[name + '_espn'] - match[name + '_wnba']
        all_equal = match[[name + '_difference' for name in FIELDS]].eq(0).all(axis=1)
        match['all_counts_match'] = all_equal
        groups.append(match.assign(season=year, phase=phase))
        summary = dict(season=year, phase=phase, espn_games=len(e), wnba_games=len(w),
                       matched_games=len(match), all_counts_match=int(all_equal.sum()))
        for source in ('espn', 'wnba'):
            for name in FIELDS:
                summary[f'{source}_{name}'] = int(match[f'{name}_{source}'].sum())
        summaries.append(summary)
    return groups, summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true', help='Pin the currently available WNBA reference files')
    args = parser.parse_args()
    reference_sources(args.snapshot)
    groups, results = [], []
    for year in (2025, 2026):
        games, summary = compare(year)
        groups.extend(games)
        results.extend(summary)
    pd.concat(groups).to_csv(RESULTS / 'official_reference_games.csv', index=False)
    pd.DataFrame(results).to_csv(RESULTS / 'official_reference_summary.csv', index=False)
    print('LEAGUE_REFERENCE_CHECK', results, flush=True)


if __name__ == '__main__':
    main()
