"""Pin or restore the WNBA Stats full event file and final game scores for every season."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json

from build import write_json
from fetch import CACHE, HERE, YEARS, download, file_matches

DIRECTORY = CACHE/'league_plays'
MANIFEST = HERE/'play_manifest.json'
RELEASES = {'wnba_stats_pbp':'wnba_play_by_play', 'wnba_stats_schedules':'wnba_schedule'}


def restore(row):
    path = DIRECTORY/row['filename']
    if not file_matches(path,row):
        part = path.with_suffix('.part')
        part.write_bytes(download(row['url']))
        if not file_matches(part,row):
            raise ValueError(f"Release file differs from source pin {path.name}")
        part.replace(path)


def main(snapshot=False):
    DIRECTORY.mkdir(parents=True,exist_ok=True)
    if snapshot:
        rows=[]
        for tag,stem in RELEASES.items():
            release=json.loads(download(f'https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/{tag}'))
            assets={a['name']:a for a in release['assets']}
            for year in YEARS:
                a=assets[f'{stem}_{year}.csv.gz']
                assert a['digest'].startswith('sha256:')
                rows.append(dict(season=year,release=tag,filename=a['name'],sha256=a['digest'][7:],
                    bytes=a['size'],url=a['browser_download_url']))
    else:
        rows=json.loads(MANIFEST.read_bytes())
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(restore,rows))
    if snapshot:
        write_json(MANIFEST,rows)
    print('WNBA_EVENTS_VERIFIED',len(rows),'files',sum(r['bytes'] for r in rows),'bytes',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',action='store_true')
    main(parser.parse_args().snapshot)
