"""Exercise the explorer in a fresh, isolated desktop Chrome session."""
import argparse
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.request

import websocket

from fetch import CACHE, ROOT


class Browser:
    def __init__(self, profile):
        self.profile = profile
        self.socket = None
        self.count = 0
        self.errors = []
        chrome = Path(os.environ['ProgramFiles']) / 'Google/Chrome/Application/chrome.exe'
        self.proc = subprocess.Popen([str(chrome), '--headless=new', '--disable-gpu', '--remote-debugging-port=0',
                                      f'--user-data-dir={profile}', '--window-size=1440,1000', 'about:blank'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def connect(self):
        port_path = Path(self.profile) / 'DevToolsActivePort'
        for _ in range(60):
            if port_path.exists() and port_path.stat().st_size:
                port = port_path.read_text().splitlines()[0]
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=5) as response:
                    tabs = json.load(response)
                endpoint = next(tab['webSocketDebuggerUrl'] for tab in tabs if tab['type'] == 'page')
                self.socket = websocket.create_connection(endpoint, timeout=20, suppress_origin=True)
                break
            time.sleep(.1)
        if not self.socket:
            raise RuntimeError('Chrome did not open')
        for enable in ['Runtime.enable','Page.enable','Log.enable','Network.enable']:
            self.call(enable)
        self.call('Network.setCacheDisabled', {'cacheDisabled':True})

    def call(self, method, params=None):
        self.count += 1
        self.socket.send(json.dumps({'id':self.count,'method':method,'params':params or {}}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get('id') == self.count:
                assert 'error' not in message, message
                return message.get('result', {})
            if message.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(message['params'])
            if message.get('method') == 'Log.entryAdded':
                entry = message['params']['entry']
                if entry['level'] == 'error' and 'favicon' not in (entry.get('url','') + entry.get('text','')):
                    self.errors.append(entry)

    def js(self, js):
        result = self.call('Runtime.evaluate', {'expression':js,'returnByValue':True,'awaitPromise':True})
        assert 'exceptionDetails' not in result, result
        return result['result'].get('value')

    def wait(self, expression):
        for _ in range(200):
            if self.js(expression):
                return
            time.sleep(.15)
        raise AssertionError(expression)

    def select(self, ident, value):
        self.js(f"(()=>{{const select=document.getElementById({json.dumps(ident)});select.value={json.dumps(str(value))};select.dispatchEvent(new Event('change'));}})()")
        self.wait("document.querySelector('#load-state').textContent==='' && !document.querySelector('#atlas-content').hidden")

    def save_image(self, filename, beyond=False):
        shot = self.call('Page.captureScreenshot', {'format':'png', 'captureBeyondViewport':beyond})
        (CACHE / filename).write_bytes(base64.b64decode(shot['data']))

    def close(self):
        if self.socket:
            try:
                self.call('Browser.close')
            except (OSError, websocket.WebSocketException):
                pass
            self.socket.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)


def verify_comparison_units(browser):
    """Recount two seasons of different sizes, including shots outside the map."""
    js = browser.js
    years = (2020, 2026)
    packs = {year: json.loads((ROOT / f'explore/data/{year}.json').read_bytes())['rows']
             for year in years}
    assert js("document.getElementById('compare-units').hidden")
    browser.select('season', years[0])
    browser.select('compare', years[1])
    assert js("document.getElementById('phase').selectedIndex === 0")
    assert js("!document.getElementById('compare-units').hidden && document.getElementById('normalize-shots').checked")
    browser.select('zone', 3)
    toggle = "document.getElementById('normalize-shots').click()"

    def check(filters, normalized):
        browser.wait("document.getElementById('history-rows').rows.length > 0 && !document.getElementById('history-status').textContent")
        legend = js("document.getElementById('legend-high').textContent")
        expected_max = 1
        samples = []
        for panel, year in zip(('primary', 'secondary'), years):
            rows = [r for r in packs[year] if all(r[i] == v for i, v in filters.items())]
            attempts = sum(r[5] for r in rows)
            points = sum(r[7] for r in rows)
            area = [r for r in rows if r[4] == 3]
            n, makes, zone_points = (sum(r[i] for r in area) for i in (5, 6, 7))
            samples.append((year, n, attempts))
            cells = {}
            for r in rows:
                if r[3] >= 0:
                    cells[r[3]] = cells.get(r[3], 0) + r[5]
            peak = max(cells.values(), default=0)
            expected_max = max(expected_max, 100 * peak / attempts if normalized and attempts else peak)
            card = f"document.getElementById('court-{panel}')"
            assert js(f"{card}.querySelector('[data-total=n]').textContent") == f'{attempts:,}'
            card_points = js(f"{card}.querySelector('[data-total=points]').textContent")
            stats = js(f"""Object.fromEntries([...document.querySelectorAll('.area-result[data-season="{year}"] dt')]
                .map(dt => [dt.textContent, dt.nextElementSibling.textContent]))""")
            hist = js(f"""[...document.getElementById('history-rows').rows]
                .find(r => r.cells[0].textContent === '{year}').cells[2].textContent""")
            if normalized:
                for label, value in [('Attempts', n), ('Makes', makes), ('Points', zone_points)]:
                    shown = stats[f'{label} per 100 shots']
                    if attempts:
                        assert abs(float(shown) - 100 * value / attempts) <= .00500001, (year, label, shown)
                    else:
                        assert shown == 'Unavailable'
                assert hist == stats['Attempts per 100 shots']
                if attempts:
                    assert abs(float(card_points) - 100 * points / attempts) <= .00500001
                else:
                    assert card_points == 'Unavailable'
            else:
                assert stats['Made / attempts'] == f'{makes:,} / {n:,}'
                assert stats['Field goal points'] == f'{zone_points:,}'
                assert card_points == f'{points:,}' and hist == f'{n:,}'
        if normalized:
            assert legend.endswith(' per 100') and abs(float(legend.split()[0]) - expected_max) <= .00500001
        else:
            assert legend == f'{expected_max:,}'
        return samples

    samples = check({}, True)
    assert samples[0][2] != samples[1][2]
    for year, shots, total in samples:
        print(f'{year} corner three area: {shots:,} of {total:,} attempts, {100 * shots / total:.2f} per 100', flush=True)
    js("window.normalizedCourts = [...document.querySelectorAll('.court-panel canvas')].map(c => c.toDataURL())")
    js(toggle)
    check({}, False)
    assert js("[...document.querySelectorAll('.court-panel canvas')].some((c,i) => c.toDataURL() !== window.normalizedCourts[i])")
    for metric in ('rate', 'points'):
        js(f"document.querySelector('[data-metric={metric}]').click()")
        js("window.rateCourt = document.querySelector('#court-primary canvas').toDataURL()")
        js(toggle)
        assert js("document.querySelector('#court-primary canvas').toDataURL() === window.rateCourt")
    js("document.querySelector('[data-metric=share]').click()")
    js(toggle)
    browser.select('phase', 0)
    browser.select('shot-type', 0)
    check({0: 0, 8: 0}, True)
    players_2020 = {r[2] for r in packs[2020]}
    player = next(r[2] for r in packs[2026] if r[0] == 0 and r[8] == 0 and r[2] and r[2] not in players_2020)
    browser.select('player', player)
    check({0: 0, 2: player, 8: 0}, True)
    js(toggle)
    check({0: 0, 2: player, 8: 0}, False)
    js(toggle)
    for control, value in [('player', 'all'), ('shot-type', 'all'), ('phase', 'all'), ('compare', 'off'), ('zone', 'cell')]:
        browser.select(control, value)
    assert js("document.getElementById('compare-units').hidden")


def verify_shot_timing(browser):
    data = json.loads((ROOT / 'explore/data/shot-timing.json').read_bytes())
    js = browser.js
    assert js("document.getElementById('timing-games').selectedIndex === 0 && document.getElementById('timing-games').value === 'both'")
    assert js("document.getElementById('timing-seconds').value") == '6'
    for phase, block in data['scopes'].items():
        browser.select('timing-games', phase)
        for t in range(data['maxSeconds'] + 1):
            js(f"(()=>{{ const time=document.getElementById('timing-seconds'); time.value={t}; time.dispatchEvent(new Event('input')); }})()")
            cards = js("""[...document.querySelectorAll('.timing-card')].map(c => ({
                name: c.dataset.situation, rate: c.querySelector('strong').textContent,
                sources: c.querySelector('small').textContent, points: c.querySelector('small:last-child').textContent,
                filled: c.querySelectorAll('.attempted').length, dots: c.querySelectorAll('i').length}))""")
            assert len(cards) == 2
            for card in cards:
                g = block['groups'][card['name']]
                rate = 100*g['shots'][t]/g['starts']
                assert card['rate'] == f'{rate:.1f}%' and card['filled'] == int(rate + .5) and card['dots'] == 100
                assert card['sources'] == f"{g['shots'][t]:,} of {g['starts']:,} possessions"
                assert card['points'] == f"{100*g['points'][t]/g['starts']:.1f} points from first shots per 100 possessions"
            displayed = js("[...document.querySelector('#shot-timing table tbody').rows].map(r => [...r.cells].map(c => c.textContent))")
            assert len(displayed) == len(block['groups'])
            for cells, g in zip(displayed, block['groups'].values()):
                assert cells[1:] == [f"{g['starts']:,}", f"{g['shots'][t]:,}", f"{g['makes'][t]:,}", f"{100*g['points'][t]/g['starts']:.1f}"]
    forecasts = sorted(data['forecasts'], key=lambda r: (r['season'], r['scope'] != 'regular'))
    displayed = js("[...document.querySelectorAll('#shot-timing table')[1].tBodies[0].rows].map(r => [...r.cells].map(c => c.textContent))")
    for cells, row in zip(displayed, forecasts, strict=True):
        assert cells[1:4] == [f"{row['starts']:,}", f"{row['baseline']:.5f}", f"{row['model']:.5f}"]
    browser.select('timing-games', 'both')
    js("document.getElementById('timing-seconds').value=6;document.getElementById('timing-seconds').focus()")
    for event in ['keyDown', 'keyUp']:
        browser.call('Input.dispatchKeyEvent', {'type': event, 'key': 'ArrowRight', 'code': 'ArrowRight', 'windowsVirtualKeyCode': 39})
    assert js("document.getElementById('timing-seconds').value") == '7'
    js("document.getElementById('timing-seconds').value=6;document.getElementById('timing-seconds').dispatchEvent(new Event('input'))")
    js("document.getElementById('shot-timing').scrollIntoView({block:'start'})")
    browser.save_image('atlas_shot_timing_desktop.png')
    print('SHOT_TIMING_BROWSER_VERIFIED', data['scopes']['both']['eligible'], 'possessions, all clock settings and game types', flush=True)


def verify(browser, url):
    index = json.loads((ROOT / 'explore/data/index.json').read_bytes())
    seasons = {row['season']: row for row in index['coverage']}
    all_pack = json.loads((ROOT / 'explore/data/all.json').read_bytes())
    study = json.loads((ROOT / 'explore/data/study.json').read_bytes())
    js = browser.js
    attempts = "document.querySelector('#court-primary [data-total=n]').textContent"
    points = "document.querySelector('#court-primary [data-total=points]').textContent"
    arc = "document.querySelector('#court-primary canvas').dataset.arc"
    ready = "document.body?.dataset.ready==='true' && !document.querySelector('#public-study').hidden"
    fmt = lambda n: f'{n:,}'
    browser.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'dark'}]})
    browser.call('Page.navigate', {'url': url})
    browser.wait(ready)
    assert js("document.documentElement.dataset.theme") == 'light'
    assert js("document.querySelector('#season').value") == 'all'
    combined_first = "document.getElementById('phase').selectedIndex === 0 && document.getElementById('phase').options[0].value === 'all'"
    assert js(combined_first)
    assert js(attempts) == fmt(sum(row[5] for row in all_pack['rows']))
    assert js(points) == fmt(sum(row[7] for row in all_pack['rows']))
    assert js(arc) == ','.join(str(r['arc_radius']) for r in index['court']['eras'])
    assert js("document.querySelectorAll('#court-primary [data-era-key] span').length") == 3
    browser.save_image('atlas_all_desktop.png')
    verify_comparison_units(browser)
    for year, row in seasons.items():
        browser.select('season', year)
        assert js(attempts) == fmt(row['regular']['attempts'] + row['playoffs']['attempts']), year
        era = next(r for r in index['court']['eras'] if r['first_season'] <= year <= r['last_season'])
        assert abs(float(js(arc)) - era['arc_radius']) < 1e-10
    for phase, scope in [(0, 'regular'), (1, 'playoffs')]:
        browser.select('phase', phase)
        assert js(attempts) == fmt(seasons[2026][scope]['attempts'])

    browser.select('season', 'all')
    browser.select('phase', 'all')
    for kind in range(len(index['shotTypes'])):
        browser.select('shot-type', kind)
        assert js(attempts) == fmt(sum(row[5] for row in all_pack['rows'] if row[8] == kind))
    browser.select('shot-type', 'all')
    js("document.querySelector('#compare-rule').click()")
    browser.wait("document.querySelector('#court-secondary [data-year]').textContent==='2013'")
    assert js(attempts) == fmt(seasons[2012]['regular']['attempts'])
    assert js("document.querySelector('#court-secondary [data-total=n]').textContent") == fmt(seasons[2013]['regular']['attempts'])
    assert js("document.querySelector('#court-primary [data-arc]').textContent.includes('20 ft 6¼ in') && document.querySelector('#court-secondary [data-arc]').textContent.includes('22 ft 1¾ in')")
    before = js("document.querySelector('#area-position').textContent")
    js("document.querySelector('#court-primary canvas').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true,cancelable:true}))")
    assert js("document.querySelector('#area-position').textContent") != before
    browser.wait(f"document.querySelector('#history-rows').rows.length==={len(seasons)}")
    assert js("document.querySelector('#court-primary canvas').dataset.selected===document.querySelector('#court-secondary canvas').dataset.selected")
    browser.select('zone', 3)
    assert js("document.querySelector('#area-title').textContent") == 'Corner three area'
    for metric in ('share', 'rate', 'points'):
        js(f"document.querySelector('[data-metric={metric}]').click()")
        assert js(f"document.querySelector('[data-metric={metric}]').getAttribute('aria-pressed')") == 'true'

    browser.select('season', 2026)
    browser.select('compare', 'off')
    browser.select('phase', 0)
    browser.select('team', 5)
    player = int(js("document.querySelector('#player').options[1].value"))
    browser.select('player', player)
    browser.select('shot-type', 1)
    browser.wait(f"document.querySelector('#history-rows').rows.length==={len(seasons)}")
    pack = json.loads((ROOT / 'explore/data/2026.json').read_bytes())
    expected = sum(row[5] for row in pack['rows'] if row[:3] == [0, 5, player] and row[8] == 1)
    assert js(attempts) == fmt(expected)
    assert 'Layup' in js("document.querySelector('#history-context').textContent")
    assert js("document.querySelector('#type-rows').rows.length") == len(index['shotTypes'])

    verify_shot_timing(browser)
    plays=json.loads((ROOT/'explore/data/plays.json').read_bytes())
    forms=json.loads((ROOT/'explore/data/shot-form.json').read_bytes())
    assert js("document.querySelector('#miss-scope').value")=='both'
    assert not js("document.querySelector('#comparison-callout').open")
    for r in plays['misses']:
        choice={'both':'both','regular':'regular','playoffs':'post'}[r['scope']]
        browser.select('miss-scope',choice)
        total=sum(x['misses'] for x in r['flow'])
        assert fmt(total) in js("document.querySelector('.miss-flow h3').textContent")
        assert fmt(r['games']) in js("document.getElementById('miss-title').parentElement.textContent")
    for r in plays['situations']:
        browser.select('play-situation',r['situation'])
        assert js("document.querySelector('.play-rates strong').textContent")==f"{100*r['next_shots']/r['states']:.1f}%"
        assert js("document.querySelector('.play-rates > div:nth-child(2) strong').textContent")==f"{100*r['scoring_turns']/r['states']:.1f}%"
        assert js("document.querySelector('.play-rates > div:nth-child(3) strong').textContent")==f"{r['points']/r['states']:.2f}"
    for group in plays['histories']:
        browser.select('history-length',group['length'])
        assert js("document.querySelectorAll('.play-trail li').length")==group['length']+1
        assert js("document.querySelector('.play-trail li:last-child').textContent")=='Shot attempted'
    for i,r in enumerate(plays['forecasts']):
        browser.select('play-forecast-history',i)
        assert fmt(r['states']) in js("document.getElementById('play-forecast-history').parentNode.nextSibling.textContent")
    for scope in ('both','regular','playoffs'):
        browser.select('location-model-phase',scope)
        area=next(r for r in plays['shotValue'] if r['scope']==scope)
        assert fmt(area['attempts']) in js("document.getElementById('location-model-phase').closest('details').textContent")
    for band in forms['diagram']:
        browser.select('form-distance',band['feet'])
        if js("document.getElementById('form-match').checked"):
            js("document.getElementById('form-match').click()")
        for row in [r for r in band['rows'] if r['name'] in ('Jump shot','Layup')]:
            selector=f".form-card[data-family='{row['name']}']"
            actual=js(f'document.querySelector("{selector} strong").textContent')
            assert actual==f"{100*row['makes']/row['attempts']:.1f}%"
            assert js(f'document.querySelectorAll("{selector} .form-dots i").length')==100
        if band['sameSpots']:
            js("document.getElementById('form-match').click()")
            assert js("document.querySelector('.form-card strong').textContent")==f"{100*band['sameSpots']['layup_rate']:.1f}%"
        else:
            assert js("document.getElementById('form-match').disabled")
    assert '511,169' in js("document.querySelector('#source-explanation').textContent")
    assert '902,729' in js("document.querySelector('#source-explanation').textContent")
    browser.select('form-distance',4)
    browser.select('miss-scope','both')
    for section in ('prediction-title', 'miss-title'):
        prefix = f"document.getElementById('{section}').parentElement"
        for split in ('test', 'playoffs', 'validation'):
            js(f"""(()=>{{const select={prefix}.querySelector('.study-picker select');
            select.value='{split}';select.dispatchEvent(new Event('change'));}})()""")
            if section == 'miss-title':
                r = next(r for r in study['flow'] if r['split'] == split and r['rebound'])
                total = sum(a['misses'] for a in study['flow'] if a['split'] == split)
                assert fmt(total) in js(f"{prefix}.querySelector('.miss-flow h3').textContent")
                assert f"{100 * r['misses'] / total:.1f}%" in js(f"{prefix}.querySelector('.miss-outcome.rebound').textContent")
            else:
                n = next(r['attempts'] for r in study['shots'] if r['split'] == split)
                assert fmt(n) in js(f"{prefix}.querySelector('.finding-body').textContent")
    js("for(let n=document.querySelector('.posterior-view');n;n=n.parentElement){if(n.tagName==='DETAILS') n.open=true;}")
    browser.wait("document.querySelector('.posterior-numbers strong')?.textContent.includes('estimated make chance')")
    before = js("document.querySelector('.posterior-numbers').textContent")
    js("document.querySelector('.posterior-court canvas').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true,cancelable:true}))")
    assert js("document.querySelector('.posterior-numbers').textContent") != before
    js("""document.querySelectorAll('.posterior-controls select').forEach((node,i)=>{
        node.value=i ? 'spread' : 'spde'; node.dispatchEvent(new Event('change',{bubbles:true}));})""")
    assert 'wider intervals' in js("document.querySelector('.posterior-aside .caption').textContent")
    js("document.querySelector('.posterior-view').scrollIntoView({block:'center'})")
    browser.save_image('atlas_bayesian_desktop.png')

    before_colours = js("getComputedStyle(document.documentElement).getPropertyValue('--colour-mid').trim()")
    js("document.querySelector('#theme-toggle').click()")
    assert js("getComputedStyle(document.documentElement).getPropertyValue('--colour-mid').trim()") != before_colours
    assert js("document.documentElement.dataset.theme") == 'dark'
    browser.call('Page.reload', {'ignoreCache': True})
    browser.wait(ready)
    assert js("document.documentElement.dataset.theme") == 'dark'
    js("document.querySelector('#theme-toggle').click()")
    for width in [390, 320]:
        browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
        time.sleep(.2)
        js("document.querySelectorAll('details').forEach(node=>node.open=true)")
        assert js(f"innerWidth==={width} && document.documentElement.scrollWidth<=innerWidth && document.querySelector('#court-primary canvas').clientWidth>220")
        js("document.querySelectorAll('details').forEach(node=>node.open=false);window.scrollTo(0,0)")
        browser.save_image(f'atlas_mobile_{width}.png')
        assert js("[...document.querySelectorAll('.timing-card')].every(c => c.offsetWidth > 0 && c.getBoundingClientRect().right <= innerWidth)")
        if width == 390:
            js("document.getElementById('shot-timing').scrollIntoView({block:'start'})")
            browser.save_image('atlas_shot_timing_mobile.png')
        browser.select('compare', 2026)
        assert js("document.getElementById('normalize-shots').getBoundingClientRect().width > 0 && document.documentElement.scrollWidth <= innerWidth")
        browser.select('compare', 'off')

    from urllib.parse import urljoin
    browser.call('Page.navigate', {'url': urljoin(url, 'explore/#shot-timing')})
    browser.wait("location.pathname.endsWith('/explore/') && " + ready)
    assert js(combined_first)
    browser.wait("document.getElementById('shot-timing')?.getBoundingClientRect().top < innerHeight && document.getElementById('shot-timing').getBoundingClientRect().bottom > 0")
    assert js(attempts) == fmt(sum(row[5] for row in all_pack['rows']))
    browser.call('Page.navigate', {'url': urljoin(url, 'study/')})
    browser.wait("location.pathname.endsWith('/study/') && document.body?.dataset.ready==='true' && document.body.dataset.recoveryReady==='true'")
    assert js("window.wnbaCheck.shownAttempts") == 38441
    browser.call('Page.navigate', {'url': urljoin(url, 'meeting/')})
    browser.wait("location.pathname.endsWith('/meeting/') && document.body?.dataset.recoveryReady==='true' && [...document.images].every(i=>i.complete && i.naturalWidth>0)")
    assert not browser.errors, browser.errors[:3]
    print('ATLAS_BROWSER_VERIFIED', len(seasons), 'seasons, pooled totals, phases, shot types, spatial and event findings, posterior, themes, mobile, original study', flush=True)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    args = parser.parse_args()
    server = None
    if not args.url:
        server = ThreadingHTTPServer(('127.0.0.1',0), partial(QuietHandler,directory=ROOT))
        threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='wnba-atlas-') as profile:
            browser = Browser(profile)
            try:
                browser.connect()
                verify(browser, args.url or f'http://127.0.0.1:{server.server_port}/')
            finally:
                browser.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
