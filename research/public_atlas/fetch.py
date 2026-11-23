"""Restore the pinned wehoop season files or take an explicit new snapshot."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / 'research/data/public_wnba'
RAW = CACHE / 'raw'
PIN = HERE / 'source_manifest.json'
YEARS = tuple(range(1997, 2027))
REPO = 'sportsdataverse/sportsdataverse-data'


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'wnba-shot-atlas'})
    with urllib.request.urlopen(request, timeout=60) as stream:
        return stream.read()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest_digest():
    return digest(PIN.read_text(encoding='utf-8').encode('utf-8'))


def file_matches(path, source):
    return (path.is_file() and path.stat().st_size == source['bytes']
            and file_digest(path) == source['sha256'])


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
    inventories = {}
    for source in json.loads(PIN.read_bytes()):
        tag = source['release']
        if tag not in inventories:
            release = json.loads(download(f'https://api.github.com/repos/{REPO}/releases/tags/{tag}'))
            inventories[tag] = {asset['name']: asset for asset in release['assets']}
        upstream = unquote(Path(urlparse(source['url']).path).name)
        asset = inventories[tag][upstream]
        url = asset['browser_download_url']
        raw = download(url)
        sha = digest(raw)
        assert len(raw) == asset['size'], upstream
        assert not asset.get('digest') or asset['digest'] == f'sha256:{sha}', upstream
        target = CACHE / 'refresh' / source['filename']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        sources.append(dict(source, asset_id=asset['id'], url=url, sha256=sha,
                            bytes=len(raw), updated_at=asset['updated_at']))
    for source in sources:
        name = source['filename']
        (CACHE / 'refresh' / name).replace(RAW / name)
    temporary = PIN.with_suffix('.tmp')
    temporary.write_text(json.dumps(sorted(sources, key=lambda row: (row['season'], row['kind'])), indent=2) + '\n', encoding='utf-8')
    temporary.replace(PIN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Replace the pins with a new upstream snapshot')
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        snapshot()
    sources = json.loads(PIN.read_bytes())
    assert len({row['filename'] for row in sources}) == len(sources)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(restore, sources))
    print(f'Verified {len(sources)} pinned wehoop files')


if __name__ == '__main__':
    main()
