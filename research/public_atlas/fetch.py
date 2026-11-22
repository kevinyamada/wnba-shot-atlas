"""Restore the pinned wehoop season files or take an explicit new snapshot."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / 'research/data/public_wnba'
RAW = CACHE / 'raw'
PIN = HERE / 'source_manifest.json'
YEARS = tuple(range(2011, 2027))
TAGS = {
    'shots': 'espn_wnba_shots',
    'wnba_schedule': 'espn_wnba_schedules',
    'team_box': 'espn_wnba_team_boxscores',
    'player_box': 'espn_wnba_player_boxscores',
}
REPO = 'sportsdataverse/sportsdataverse-data'


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'wnba-shot-atlas'})
    with urllib.request.urlopen(request, timeout=60) as stream:
        return stream.read()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def manifest_digest():
    return digest(PIN.read_bytes().replace(b'\r\n', b'\n'))

def file_matches(path, source):
    return (path.is_file() and path.stat().st_size == source['bytes']
            and digest(path.read_bytes()) == source['sha256'])


def restore(source):
    path = RAW / source['filename']
    if file_matches(path, source):
        return
    raw = download(source['url'])
    if len(raw) != source['bytes'] or digest(raw) != source['sha256']:
        raise ValueError(f"Upstream asset differs from the pinned snapshot: {path.name}")
    temporary = path.with_suffix('.part')
    temporary.write_bytes(raw)
    temporary.replace(path)


def snapshot():
    sources = []
    for kind, tag in TAGS.items():
        release = json.loads(download(f'https://api.github.com/repos/{REPO}/releases/tags/{tag}'))
        assets = {item['name']: item for item in release['assets']}
        for season in YEARS:
            filename = f'{kind}_{season}.csv'
            asset = assets[filename]
            url = asset['browser_download_url']
            raw = download(url)
            sha = digest(raw)
            assert len(raw) == asset['size'], filename
            assert not asset.get('digest') or asset['digest'] == f'sha256:{sha}', filename
            # Preserve the pinned files until the new snapshot has downloaded in full.
            target = CACHE / 'refresh' / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            sources.append(dict(season=season, kind=kind, filename=filename, release=tag,
                                asset_id=asset['id'], url=url, sha256=sha, bytes=len(raw),
                                updated_at=asset['updated_at']))
    for source in sources:
        name = source['filename']
        (CACHE / 'refresh' / name).replace(RAW / name)
    temporary = PIN.with_suffix('.tmp')
    temporary.write_text(json.dumps(sorted(sources, key=lambda row: (row['season'], row['kind'])), indent=2) + '\n', encoding='utf-8', newline='')
    temporary.replace(PIN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Replace the pins with a new upstream snapshot')
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        snapshot()
    sources = json.loads(PIN.read_bytes())
    assert {(row['season'], row['kind']) for row in sources} == {(y, k) for y in YEARS for k in TAGS}
    assert len(sources) == len(YEARS) * len(TAGS)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(restore, sources))
    print(f'Verified {len(sources)} pinned wehoop files')


if __name__ == '__main__':
    main()
