"""Exercise the explorer in a fresh, isolated desktop Chrome session."""
import argparse
import base64
import csv
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


def pick_area(browser, zone):
    """Select a court area from the overview, or return to the selected square with None."""
    pressed = browser.js("document.querySelector('#area-rows button[aria-pressed=true]')?.dataset.zone ?? null")
    target = pressed if zone is None else str(zone)
    if target is not None and (zone is None or pressed != target):
        browser.js(f"document.querySelector('#area-rows button[data-zone=\"{target}\"]').click()")
    expected = 'null' if zone is None else f"'{zone}'"
    assert browser.js(f"(document.querySelector('#area-rows button[aria-pressed=true]')?.dataset.zone ?? null) === {expected}")


def expected_leaders(pack, filters, key, value):
    """Rank shooters by observed field goal points with the player filter left open."""
    totals = {}
    for row in pack['rows']:
        if row[2] and row[key] == value and all(row[i] == v for i, v in filters.items()):
            entry = totals.setdefault(row[2], [0, 0, 0])
            for i in range(3):
                entry[i] += row[5 + i]
    ranked = sorted(totals.items(), key=lambda item: (-item[1][2], -item[1][1], item[1][0], pack['players'][str(item[0])]))
    return [(pack['players'][str(player)], f'{points:,} points', f'{makes:,} of {n:,} made')
            for player, (n, makes, points) in ranked[:3] if points]


def shown_leaders(browser, season):
    return [tuple(item) for item in browser.js(f"""[...document.querySelectorAll('.area-result[data-season="{season}"] .leaders li')]
        .map(li => [li.querySelector('span').textContent, li.querySelector('strong').textContent, li.querySelector('small').textContent])""")]


def verify_area_selection(browser):
    """Select areas by click and keyboard, then recount makes, points and leaders."""
    js = browser.js
    pack = json.loads((ROOT / 'explore/data/2026.json').read_bytes())
    zones = json.loads((ROOT / 'explore/data/index.json').read_bytes())['zones']
    browser.select('season', 2026)
    square = int(js("document.querySelector('#court-primary canvas').dataset.selected"))
    assert shown_leaders(browser, 2026) == expected_leaders(pack, {}, 3, square)
    for zone, name in enumerate(zones):
        pick_area(browser, zone)
        rows = [row for row in pack['rows'] if row[4] == zone]
        n, makes, points = (sum(row[i] for row in rows) for i in (5, 6, 7))
        stats = js("""Object.fromEntries([...document.querySelectorAll('.area-result dt')]
            .map(dt => [dt.textContent, dt.nextElementSibling.textContent]))""")
        assert js("document.getElementById('area-title').textContent") == name
        assert stats['Made / attempts'] == f'{makes:,} / {n:,}' and stats['Field goal points'] == f'{points:,}', (name, stats)
        assert js("document.querySelector('#court-primary canvas').dataset.area") == (str(zone) if zone < 5 else '')
        assert js("document.querySelector('#court-primary canvas').dataset.selected") == ''
        assert js("document.querySelectorAll('#area-rows tr.selected').length") == 1
        assert shown_leaders(browser, 2026) == expected_leaders(pack, {}, 4, zone), name
    browser.select('team', 5)
    player = int(js("document.querySelector('#player').options[1].value"))
    browser.select('player', player)
    pick_area(browser, 0)
    team_leaders = expected_leaders(pack, {1: 5}, 4, 0)
    shown = shown_leaders(browser, 2026)
    assert shown[:len(team_leaders)] == team_leaders and len(shown) <= len(team_leaders) + 1
    chosen = js("[...document.querySelectorAll('.leaders li.chosen span')].map(node => node.textContent)")
    assert chosen in ([], [pack['players'][str(player)]])
    browser.select('player', 'all')
    browser.select('team', 'all')
    js("document.querySelector('#area-rows button[data-zone=\"2\"]').focus()")
    for event in ['keyDown', 'keyUp']:
        browser.call('Input.dispatchKeyEvent', {'type': event, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13, 'text': '\r'})
    assert js("document.activeElement.dataset.zone === '2' && document.activeElement.getAttribute('aria-pressed') === 'true'")
    assert js("document.querySelector('#court-primary canvas').dataset.area") == '2'
    js("document.querySelector('#court-primary canvas').toDataURL()")
    browser.save_image('atlas_court_area_selected_desktop.png')
    pick_area(browser, None)
    assert js("document.querySelector('#court-primary canvas').dataset.selected") == str(square)
    browser.select('season', 'all')
    print('COURT_AREA_SELECTION_VERIFIED', len(zones), 'areas, leaders by field goal points, keyboard', flush=True)


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
    pick_area(browser, 3)
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
            table = js(f"""[...document.querySelectorAll('#area-rows tr[data-zone="3"]')]
                .map(r => [...r.querySelectorAll('td')].map(c => c.textContent)).find(cells => cells[0] === '{year}')""")
            if normalized and attempts:
                assert abs(float(table[1]) - 100 * n / attempts) <= .00500001, (year, table)
            elif not normalized:
                assert table[1] == f'{n:,}', (year, table)
            if n:
                assert abs(float(table[2].rstrip('%')) - 100 * makes / n) <= .0500001 and abs(float(table[3]) - zone_points / n) <= .00500001
            else:
                assert table[2:] == ['Unavailable', 'Unavailable']
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
    for control, value in [('player', 'all'), ('shot-type', 'all'), ('phase', 'all'), ('compare', 'off')]:
        browser.select(control, value)
    pick_area(browser, None)
    assert js("document.getElementById('compare-units').hidden")


def zone_totals(rows, zones):
    totals = [[0, 0, 0] for _ in zones]
    for row in rows:
        for i in range(3):
            totals[row[4]][i] += row[5 + i]
    return totals


def check_area_table(browser, zones, expected, label):
    shown = browser.js("""[...document.querySelectorAll('#area-table tr')].slice(1)
        .map(r => [...r.cells].map(c => c.textContent))""")
    attempts = sum(n for n, _, _ in expected)
    assert len(shown) == len(zones) + 1, label
    assert browser.js("document.querySelector('#court-primary [data-total=n]').textContent") == f'{attempts:,}', label
    for cells, name, (n, made, points) in zip(shown, [*zones, 'All attempts'], [*expected, (attempts,
            sum(m for _, m, _ in expected), sum(p for _, _, p in expected))]):
        assert cells[:2] == [name, f'{n:,}'], (label, cells)
        values = [(cells[2], 100 * n / attempts if attempts else None, .05),
                  (cells[3], 100 * made / n if n else None, .05),
                  (cells[4], points / n if n else None, .005)]
        for text, value, step in values:
            if value is None:
                assert text == 'Unavailable', (label, cells)
            else:
                assert abs(float(text.rstrip('%').replace(',', '')) - value) <= step + 1e-9, (label, cells)
    assert shown[-1][2] == ('100%' if attempts else 'Unavailable'), label
    located = [(n, i) for i, (n, _, _) in enumerate(expected[:-1]) if n]
    summary = browser.js("document.getElementById('area-summary').textContent")
    if located:
        share = max(n for n, _ in located)
        assert any(summary.startswith(f'{zones[i]} had the most shots') for n, i in located if n == share), (label, summary)
    return attempts


def verify_court_areas(browser):
    """Match the court area table with the published season zone totals."""
    index = json.loads((ROOT / 'explore/data/index.json').read_bytes())
    zones = index['zones']
    published = {}
    with open(ROOT / 'research/results/public_atlas/season_zones.csv', newline='') as file:
        for row in csv.DictReader(file):
            key = (int(row['season']), int(row['phase']))
            published.setdefault(key, [[0, 0, 0] for _ in zones])
            assert zones[int(row['zone'])] == row['zone_name']
            published[key][int(row['zone'])] = [int(row['attempts']), int(row['made']), int(row['points'])]
    empty = [[0, 0, 0] for _ in zones]

    def league(seasons, phases):
        return [[sum(published.get((s, p), empty)[z][i] for s in seasons for p in phases) for i in range(3)]
                for z in range(len(zones))]

    all_rows = json.loads((ROOT / 'explore/data/all.json').read_bytes())['rows']
    assert zone_totals(all_rows, zones) == league(index['seasons'], (0, 1))
    assert browser.js("document.getElementById('phase').value") == 'all'
    checked = 0
    for phase, phases in [('all', (0, 1)), (0, (0,)), (1, (1,))]:
        browser.select('phase', phase)
        for season in ['all', *index['seasons']]:
            browser.select('season', season)
            seasons = index['seasons'] if season == 'all' else [season]
            total = check_area_table(browser, zones, league(seasons, phases), (season, phase))
            if season == 'all':
                print(f'Court areas, all seasons, phase {phase}: {total:,} attempts match season_zones.csv', flush=True)
            checked += 1
    browser.select('season', 'all')
    browser.select('phase', 'all')
    browser.select('compare', 2026)
    assert 'All seasons and 2026' in browser.js("document.getElementById('area-context').textContent")
    heads = browser.js("[...document.querySelectorAll('#area-head th')].map(th => th.textContent)")
    assert heads == ['Area', 'Season', 'Attempts per 100 shots', 'Make rate', 'Points per shot'], heads
    shown = browser.js("[...document.querySelectorAll('#area-table tbody tr, #area-table tfoot tr')].map(r => [...r.querySelectorAll('td')].map(c => c.textContent))")
    assert len(shown) == 2 * (len(zones) + 1)
    for label, counts in [('All seasons', league(index['seasons'], (0, 1))), ('2026', league([2026], (0, 1)))]:
        attempts = sum(n for n, _, _ in counts)
        rows = [cells for cells in shown if cells[0] == label]
        assert len(rows) == len(zones) + 1
        for cells, (n, made, points) in zip(rows, counts):
            assert abs(float(cells[1].lstrip('<')) - 100 * n / attempts) <= .0100001, (label, cells)
            if n:
                assert abs(float(cells[2].rstrip('%')) - 100 * made / n) <= .0500001 and abs(float(cells[3]) - points / n) <= .00500001, (label, cells)
            else:
                assert cells[2:] == ['Unavailable', 'Unavailable'], (label, cells)
        assert float(rows[-1][1]) == 100
    browser.select('compare', 'off')
    print('COURT_AREAS_VERIFIED', checked, 'season and game selections against season_zones.csv', flush=True)


def verify_shot_mix(browser):
    """Match the shot mix section with the saved study values."""
    data = json.loads((ROOT / 'explore/data/shot-mix.json').read_bytes())
    js = browser.js
    browser.wait("!document.getElementById('shot-mix').hidden")
    signed = lambda value: ('−' if value < 0 else '+') + f'{abs(value):.3f}'
    lead = js("document.querySelector('#shot-mix > p').textContent")
    whole, recent = data['comparisons'][0], data['comparisons'][5]
    assert f"{round(100 * whole['mix_share'])}% of that rise" in lead and f"{round(100 * recent['mix_share'])}% of the rise" in lead
    shown = js("[...document.querySelector('#shot-mix details table').tBodies[0].rows].map(r => [...r.cells].map(c => c.textContent))")
    assert len(shown) == 30
    for cells, row in zip(shown, data['seasons']):
        assert cells == [str(row['season']), f"{row['attempts']:,}", f"{row['actual']:.3f}", f"{row['fixed_mix']:.3f}", f"{row['fixed_conversion']:.3f}"]
    assert sum(row['attempts'] for row in data['seasons']) == sum(row[5] for row in json.loads((ROOT / 'explore/data/all.json').read_bytes())['rows'])
    for i, row in enumerate(data['comparisons']):
        browser.select('mix-comparison', i)
        cards = js("[...document.querySelectorAll('.mix-part strong')].map(node => node.textContent)")
        assert cards == [signed(row['change']), signed(row['mix']), signed(row['conversion'])], (row['comparison'], cards)
        areas = js("[...document.querySelectorAll('#shot-mix > div > .table-scroll tbody tr')].map(r => [...r.cells].map(c => c.textContent))")
        expected = [a for a in data['comparisonAreas'] if a['comparison'] == row['comparison']]
        assert [cells[0] for cells in areas] == data['areas'] and len(expected) == len(areas)
        for cells, area in zip(areas, expected):
            assert cells[1:3] == [f"{100 * area['share_before']:.1f}%", f"{100 * area['share_after']:.1f}%"]
    browser.select('mix-comparison', 0)
    assert js("(() => { const c = document.getElementById('mix-chart'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; return d.some(v => v > 0); })()")
    js("document.getElementById('shot-mix').scrollIntoView({block:'start'})")
    browser.save_image('atlas_shot_mix_desktop.png')
    print('SHOT_MIX_BROWSER_VERIFIED', len(data['comparisons']), 'comparisons and 30 seasons', flush=True)


def verify_shots_allowed(browser):
    """Switch the court to shots allowed and recount a defending team's total."""
    js = browser.js
    attempts = "document.querySelector('#court-primary [data-total=n]').textContent"
    league = js(attempts)
    js("document.querySelector('[data-side=allowed]').click()")
    browser.wait("document.getElementById('player').disabled && document.querySelector('#load-state').textContent === ''")
    assert js(attempts) == league and 'shots allowed' in js("document.getElementById('area-context').textContent")
    browser.select('season', 2026)
    pack = json.loads((ROOT / 'explore/data/against-2026.json').read_bytes())
    team = next(int(key) for key in pack['teams'] if key != '0')
    browser.select('team', team)
    assert js(attempts) == f"{sum(row[5] for row in pack['rows'] if row[1] == team):,}"
    assert js("document.querySelectorAll('.area-result .leaders').length") == 0
    browser.wait(f"document.querySelector('#history-rows').rows.length === 30 && !document.getElementById('history-status').textContent")
    browser.save_image('atlas_shots_allowed_desktop.png')
    browser.select('team', 'all')
    js("document.querySelector('[data-side=taken]').click()")
    browser.wait("!document.getElementById('player').disabled && document.querySelector('#load-state').textContent === ''")
    browser.select('season', 'all')
    assert js(attempts) == league and js("document.querySelectorAll('.area-result .leaders').length") == 1
    print('SHOTS_ALLOWED_BROWSER_VERIFIED', flush=True)


def verify_overview(browser):
    """Match the main visual, the shooter comparison and the information ladder with their saved values."""
    js = browser.js
    mix = json.loads((ROOT / 'explore/data/shot-mix.json').read_bytes())
    timing = json.loads((ROOT / 'explore/data/shot-timing.json').read_bytes())
    browser.wait("!document.getElementById('headline').hidden && !document.getElementById('more-shooters').hidden && !document.getElementById('more-ladder').hidden")
    change = mix['comparisons'][0]
    areas = [a for a in mix['comparisonAreas'] if a['comparison'] == change['comparison']][:3]
    bars = js("[...document.querySelectorAll('.diet-row')].map(r => [...r.querySelectorAll('.diet-bar > div')].map(d => [d.querySelector('strong').textContent, d.querySelector('small').textContent]))")
    for row, share, rate in zip(bars, ('share_before', 'share_after'), ('points_per_shot_before', 'points_per_shot_after'), strict=True):
        assert row == [[f"{round(100 * a[share])}%", f"{a[rate]:.2f} a shot"] for a in areas], row
    points = js("[...document.querySelectorAll('#headline .takeaways strong')].map(node => node.textContent)")
    groups = timing['scopes']['both']['groups']
    steal = round(100 * groups['Steal']['shots'][timing['mainSeconds']] / groups['Steal']['starts'])
    assert points[:3] == [f"{round(100 * areas[2]['share_after'])}%", f"{change['after']:.2f}", f'{steal}%'], points
    js("document.getElementById('headline').scrollIntoView({block:'start'})")
    browser.save_image('atlas_headline_desktop.png')

    data = json.loads((ROOT / 'explore/data/shooters.json').read_bytes())
    signed = lambda value: f"{abs(value):.1f} {'fewer' if value < 0 else 'more'}"
    rows = "[...document.querySelectorAll('#shooter-chart .relative-row')].map(r => [r.querySelector('span').textContent, r.querySelector('em').textContent])"
    for choice, players in [('career', data['career']), ('2026', data['seasons']['2026']), ('2016', data['seasons']['2016'])]:
        browser.select('shooter-season', choice)
        assert js(rows) == [[p['name'], f"{signed(p['estimate'])} · {p['attempts']:,} shots"] for p in players[:10]], choice
        assert all(p['low'] <= p['estimate'] <= p['high'] and abs(p['estimate']) <= abs(p['raw']) + .006 for p in players)
    browser.select('shooter-season', 'career')
    outside = data['career'][40]
    browser.select('shooter-player', outside['id'])
    assert js(rows)[-1] == [outside['name'], f"{signed(outside['estimate'])} · {outside['attempts']:,} shots"] and len(js(rows)) == 11
    assert js("document.querySelectorAll('#shooter-chart .relative-row.chosen').length") == 1
    areas = json.loads((ROOT / 'explore/data/shooter-areas.json').read_bytes())
    browser.wait("!document.getElementById('shooter-areas').hidden")
    shown_areas = js("[...document.querySelectorAll('#shooter-areas .area-line')].map(r => [Number(r.dataset.zone), Number(r.dataset.value)])")
    assert shown_areas == [[row[0], row[3]] for row in areas['career'][str(outside['id'])]], shown_areas
    assert outside['name'] in js("document.querySelector('#shooter-areas h3').textContent")
    browser.wait("(() => { const c = document.querySelector('#shooter-areas canvas'); return c.width > 50 && c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some(v => v > 0); })()")
    js("document.getElementById('shooter-areas').scrollIntoView({block:'center'})")
    browser.save_image('atlas_shooter_areas_desktop.png')
    browser.select('shooter-player', '')
    assert js("document.getElementById('shooter-areas').hidden")
    assert js("[...document.querySelectorAll('.footer-links a')].some(a => a.textContent === 'Research report' && a.href.endsWith('/wnba-shot-atlas/blob/main/REPORT.md'))")

    steps = json.loads((ROOT / 'explore/data/model-ladder.json').read_bytes())
    shown = js("[...document.querySelector('#model-ladder table').tBodies[0].rows].map(r => [...r.cells].map(c => c.textContent))")
    assert [cells[1] for cells in shown] == [f"{step['brier']:.5f}" for step in steps['steps']]
    summary = steps['summary']
    parts = js("[...document.querySelectorAll('.ladder-bar strong')].map(node => node.textContent)")
    removed = 1 - summary['distance_brier'] / summary['league_brier']
    extra = (summary['distance_brier'] - summary['full_brier']) / summary['league_brier']
    assert parts == [f'{100 * removed:.1f}%', f'{100 * extra:.1f}%', f'{100 * (1 - removed - extra):.1f}%'], parts
    js("document.getElementById('more-shooters').scrollIntoView({block:'start'})")
    browser.save_image('atlas_shooters_desktop.png')
    print('OVERVIEW_BROWSER_VERIFIED main visual, shooter comparison and information ladder', flush=True)


def verify_team_report(browser):
    """Match the team table and one full team report with the saved team study."""
    js = browser.js
    data = json.loads((ROOT / 'explore/data/teams.json').read_bytes())
    shooters = json.loads((ROOT / 'explore/data/shooters.json').read_bytes())
    order = ['offence_quality', 'offence_making', 'defence_quality', 'defence_making']
    signed = lambda value: ('−' if value < 0 else '+') + f'{abs(value):.1f}'
    browser.wait("!document.getElementById('team-report').hidden && !!document.getElementById('team-table')")
    latest = max(data['seasons'])
    assert latest in js("document.getElementById('team-title').textContent")
    def per_game(team, key, field='estimate'):
        own = key.startswith('offence')
        return (1 if own else -1) * team[key][field] * (team['shots'] if own else team['shotsAgainst']) / team['games'] / 100

    net = lambda team: sum(per_game(team, key) for key in order)
    rows = "[...document.querySelectorAll('#team-table tbody tr')].map(r => [r.cells[0].textContent, ...[...r.cells].slice(1).map(c => Number(c.dataset.value))])"
    for season in (latest, '2016'):
        browser.select('season', season)
        teams = sorted(data['seasons'][season], key=lambda team: -net(team))
        shown = js(rows)
        assert js("[...document.querySelectorAll('#team-table tbody tr button')].map(b => b.textContent)") == [team['name'] for team in teams], season
        for row, team in zip(shown, teams):
            assert all(abs(value - per_game(team, key)) <= .0011 for value, key in zip(row[1:5], order)) and abs(row[5] - net(team)) <= .0011, (season, row)
        bars = js("[...document.querySelectorAll('#team-table .mini-track i')].map(i => [i.className, parseFloat(i.style.width), i.parentElement.parentElement.dataset.value])")
        assert len(bars) == 4 * len(teams) and all((kind == 'good') == (float(value) >= 0) and 0 <= width <= 50 for kind, width, value in bars)
        assert all(t[key]['low'] <= t[key]['estimate'] <= t[key]['high'] for t in teams for key in order)
    browser.select('season', latest)
    team = max(data['seasons'][latest], key=net)
    js(f"document.querySelector('#team-table button[data-team=\"{team['id']}\"]').click()")
    browser.wait(f"!!document.getElementById('team-chart') && document.getElementById('team').value === '{team['id']}'")
    assert js("document.getElementById('team-title').textContent") == f"{team['name']} in {latest}"
    shown = js("Object.fromEntries([...document.querySelectorAll('#team-chart .relative-row[data-measure]')].map(r => [r.dataset.measure, [Number(r.dataset.value), r.querySelector('em').textContent]]))")
    for key in order:
        ranking = sorted(data['seasons'][latest], key=lambda t: -per_game(t, key))
        value, note = shown[key]
        assert abs(value - per_game(team, key)) <= .0011 and note.endswith(f" of {len(ranking)}") and note.startswith(str(ranking.index(team) + 1)), (key, shown[key])
    starts = js("[...document.querySelectorAll('.team-starts table')].map(t => [...t.tBodies[0].rows].map(r => r.cells[2].textContent))")
    for cells, side in zip(starts, ('offence', 'defence'), strict=True):
        for text, row in zip(cells, team['starts'][side], strict=True):
            value, margin = (float(part) for part in text.split(' ± '))
            assert abs(value - row['per100']) <= .5 and abs(margin - row['margin']) <= .5, (text, row)
    whole = json.loads((ROOT / 'explore/data/team-possessions.json').read_bytes())
    mine = next(row for row in whole['seasons'][latest] if row['id'] == team['id'])
    detail = js("Object.fromEntries([...document.querySelectorAll('#team-possessions tbody tr')].map(r => [r.dataset.measure, [r.cells[1].textContent, r.cells[2].textContent]]))")
    assert len(detail) == 8 and all(detail[name] == [f"{mine[name]['value']:.1f}", f"{mine[name]['league']:.1f}"] for name in whole['labels']), detail
    roster = [p for p in shooters['seasons'][latest] if p.get('team') == team['id']][:3]
    text = js("document.getElementById('team-report').textContent")
    assert all(p['name'] in text for p in roster) and len(roster) > 0
    assert js("document.querySelector('#court-primary [data-year]').textContent") == latest
    js("document.getElementById('team-report').scrollIntoView({block:'start'})")
    browser.save_image('atlas_team_report_desktop.png')
    js("document.getElementById('team-back').click()")
    browser.wait("document.getElementById('team-table') && document.getElementById('team').value === 'all'")
    js("document.querySelector('#team-view [data-view=possessions]').click()")
    factors = [('offence_turnovers', -1), ('offence_rebounds', 1), ('offence_free_throws', 1), ('defence_turnovers', 1), ('defence_rebounds', -1), ('defence_free_throws', -1)]
    listed = js(rows)
    ranked = sorted(whole['seasons'][latest], key=lambda row: -row['net'])
    assert js("[...document.querySelectorAll('#team-table tbody tr button')].map(b => b.textContent)") == [row['name'] for row in ranked]
    for cells, row in zip(listed, ranked):
        assert all(abs(value - sign * row[key]['estimate']) <= .0011 for value, (key, sign) in zip(cells[1:7], factors)) and abs(cells[7] - row['net']) <= .0011, cells
    assert 'possessions' in js("document.getElementById('team-title').textContent")
    js("document.getElementById('team-report').scrollIntoView({block:'start'})")
    browser.save_image('atlas_team_possessions_desktop.png')
    js("document.querySelector('#team-view [data-view=shots]').click()")
    assert js("document.querySelectorAll('#team-table thead th').length") == 6
    control = js("[...document.querySelector('#team-control table').tBodies[0].rows].map(r => r.cells[1].textContent.split(' ')[0])")
    assert control == [f"{row['split_half']:.2f}" for row in data['repeatability']]
    assert js("document.querySelectorAll('#headline .takeaways li').length") == 4
    words = lambda value: 'very consistent' if value >= .75 else 'fairly consistent' if value >= .5 else 'only somewhat consistent' if value >= .3 else 'not consistent'
    repeat = {row['measure']: row['split_half'] for row in data['repeatability']}
    trust = js("document.getElementById('team-consistency').textContent")
    assert trust.startswith('How consistent was this across games?') and all(words(repeat[key]) in trust for key in order) and 'luck' not in trust
    assert js("document.querySelector('#more-control summary').textContent") == 'How consistent is each team number from game to game?'
    js("document.getElementById('example-team').click()")
    aces = next(row for row in data['seasons']['2026'] if row['name'] == 'Las Vegas Aces')
    browser.wait(f"document.getElementById('team').value === '{aces['id']}' && !document.getElementById('example-note').hidden")
    assert js("document.getElementById('team-title').textContent") == 'Las Vegas Aces in 2026' and js("document.getElementById('season').value") == '2026'
    assert 'Las Vegas Aces, 2026' in js("document.getElementById('example-note').textContent")
    browser.save_image('atlas_example_desktop.png')
    browser.select('team', 'all')
    browser.select('season', 'all')
    print('TEAM_REPORT_BROWSER_VERIFIED', len(data['seasons']), 'seasons of team tables and one full report', flush=True)


def verify_prediction(browser):
    """Match the 2027 prediction section and the shooter prediction option with the saved predictions."""
    js = browser.js
    data = json.loads((ROOT / 'explore/data/prediction-2027.json').read_bytes())
    signed = lambda value: ('−' if value < 0 else '+') + f'{abs(value):.1f}'
    browser.wait("!document.getElementById('more-prediction').hidden")
    assert js("document.querySelector('#more-prediction summary').textContent").startswith('Prediction')
    shown = js("[...document.querySelectorAll('#prediction .takeaways strong')].map(node => node.textContent)")
    assert shown == [f"{row['prediction']:.1f}%" if row['measure'].startswith('Share') else f"{row['prediction']:.2f}" for row in data['league']], shown
    rows = "[...document.querySelectorAll('#prediction-teams .relative-row')].map(r => [r.querySelector('span').textContent, r.querySelector('em').textContent, Number(r.dataset.value), Number(r.dataset.last)])"
    past = {row['id']: row for row in json.loads((ROOT / 'explore/data/teams.json').read_bytes())['seasons'][str(data['season'] - 1)]}

    def a_game(team, name, field):
        row = past[team['id']]
        own, other = row['shots'] / row['games'] / 100, row['shotsAgainst'] / row['games'] / 100
        return team[name][field] * ((own + other) / 2 if name == 'net' else own if name.startswith('offence') else -other)

    def number(text):
        value = float(text.split()[0])
        return -value if 'fewer' in text or 'worse' in text else value

    assert js("[...document.getElementById('prediction-measure').options].map(o => o.textContent)") == ['Overall', 'Gets good shots', 'Makes its shots', 'Limits good shots', 'Opponents miss']
    for name in ('net', 'defence_quality'):
        browser.select('prediction-measure', name)
        teams = sorted(data['teams'], key=lambda t: -a_game(t, name, 'prediction'))
        for (shown_name, text, value, before), t in zip(js(rows), teams, strict=True):
            expected = a_game(t, name, 'prediction')
            assert shown_name == t['name'] and abs(value - expected) <= .001 and abs(before - a_game(t, name, 'last')) <= .001, (name, shown_name, text)
            assert text == 'Level' or (abs(number(text) - expected) <= .0501 and text.endswith('better' if expected > 0 else 'worse')), (name, shown_name, text)
        assert all(t[name]['low'] < t[name]['prediction'] < t[name]['high'] for t in teams)
    assert js("document.querySelectorAll('#prediction-teams .relative-last').length") == len(data['teams'])
    assert 'points a game' in js("document.querySelector('#prediction-teams .relative-key').textContent")
    words = js("document.getElementById('prediction').textContent")
    assert not any(term in words for term in ('credible', 'random field', 'triangle mesh', 'per 100 shots against the league')), 'the prediction section should read in plain words'
    browser.select('prediction-measure', 'net')
    top = js("[...document.querySelectorAll('#prediction-shooters .relative-row > span:first-child')].map(node => node.textContent)")
    assert top == [p['name'] for p in data['shooters'][:10]]
    browser.select('shooter-season', 'prediction')
    listed = js("[...document.querySelectorAll('#shooter-chart .relative-row')].map(r => [r.querySelector('span').textContent, r.querySelector('em').textContent])")
    for (shown_name, text), p in zip(listed, data['shooters'][:10], strict=True):
        assert shown_name == p['name'] and text.endswith(f" · {p['attempts']:,} shots") and abs(number(text.split(' · ')[0]) - p['estimate']) <= .0501, text
    assert 'Predicted for 2027' in js("document.querySelector('#shooters > p.caption').textContent")
    browser.select('shooter-season', 'career')
    pack = json.loads((ROOT / 'explore/data/prediction.json').read_bytes())
    assert js("[...document.getElementById('compare').options].at(-1).textContent") == '2027 prediction'
    browser.select('season', 2026)
    browser.select('compare', 'prediction')
    browser.wait("document.querySelector('#court-secondary [data-year]').textContent === '2027 prediction'")
    attempts, makes, points = (sum(row[i] for row in pack['rows']) for i in (5, 6, 7))
    assert js("document.querySelector('#court-secondary [data-total=n]').textContent") == f'{attempts:,}'
    assert abs(float(js("document.querySelector('#court-secondary [data-total=rate]').textContent").rstrip('%')) - 100 * makes / attempts) <= .0501
    assert abs(float(js("document.querySelector('#court-secondary [data-total=points]').textContent")) - 100 * points / attempts) <= .00501
    assert js("[...document.querySelectorAll('#area-rows tr td:first-child')].filter(c => c.textContent === '2027 prediction').length") == 7
    assert 'prediction model' in js("document.querySelector('#court-secondary [data-location]').textContent")
    assert js("document.querySelectorAll('.area-result[data-season=prediction] .leaders').length") == 0
    browser.save_image('atlas_compare_prediction_desktop.png')
    browser.select('compare', 'off')
    browser.select('season', 'all')
    surface = json.loads((ROOT / 'explore/data/prediction-surface.json').read_bytes())
    browser.wait("document.querySelector('#prediction-surface .posterior-numbers strong')?.textContent.includes('estimated make chance')")
    depth, lateral = 15 - 5, 25 - 25
    cell = next(row for row in surface['surface'] if row[0] == depth and row[1] == lateral)
    assert js("document.querySelector('#prediction-surface .posterior-numbers strong').textContent") == f"{100 * cell[2]:.1f}% estimated make chance"
    assert f"{100 * cell[3]:.1f}% to {100 * cell[4]:.1f}%" in js("document.querySelector('#prediction-surface .posterior-numbers').textContent")
    assert js("(() => { const c = document.querySelector('#prediction-surface canvas'); return c.width > 100 && c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some(v => v > 0); })()")
    shown = js("[...document.querySelector('#prediction-backtest table').tBodies[0].rows].map(r => r.cells[4].textContent)")
    assert shown == [f"{row['rmse_bayes']:.2f}" for row in data['backtest']] and all(row['rmse_bayes'] <= row['rmse_carried'] for row in data['backtest'])
    js("document.getElementById('more-prediction').scrollIntoView({block:'start'})")
    browser.save_image('atlas_prediction_desktop.png')
    print('PREDICTION_BROWSER_VERIFIED', len(data['teams']), 'teams and', len(data['shooters']), 'shooters', flush=True)


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
    assert js("[...document.querySelectorAll('.tabs a')].map(a => a.textContent)") == ['Atlas', 'Methods lab']
    assert js("document.querySelector('#season').value") == 'all'
    combined_first = "document.getElementById('phase').selectedIndex === 0 && document.getElementById('phase').options[0].value === 'all'"
    assert js(combined_first)
    assert js(attempts) == fmt(sum(row[5] for row in all_pack['rows']))
    assert js(points) == fmt(sum(row[7] for row in all_pack['rows']))
    assert js(arc) == ','.join(str(r['arc_radius']) for r in index['court']['eras'])
    assert js("document.querySelectorAll('#court-primary [data-era-key] span').length") == 3
    browser.save_image('atlas_all_desktop.png')
    assert js("[...document.querySelectorAll('details.more')].every(node => !node.open)")
    js("document.querySelectorAll('details.more').forEach(node => { node.open = true; })")
    verify_shots_allowed(browser)
    verify_overview(browser)
    verify_team_report(browser)
    verify_prediction(browser)
    verify_court_areas(browser)
    verify_area_selection(browser)
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
    pick_area(browser, 3)
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
    chosen = [row for row in pack['rows'] if row[:3] == [0, 5, player] and row[8] == 1]
    check_area_table(browser, index['zones'], zone_totals(chosen, index['zones']), 'team, player and shot type')

    verify_shot_mix(browser)
    verify_shot_timing(browser)
    plays=json.loads((ROOT/'explore/data/plays.json').read_bytes())
    forms=json.loads((ROOT/'explore/data/shot-form.json').read_bytes())
    assert js("document.querySelector('#miss-scope').value")=='both'
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
    for key in ('recentAllRecorded', 'regularPlayoffs'):
        assert fmt(plays['sources'][key]) in js("document.querySelector('#source-explanation').textContent")
    assert plays['sources']['regularPlayoffs'] == sum(row[5] for row in all_pack['rows'])
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
    js("for(let n=document.querySelector('#public-study .posterior-view');n;n=n.parentElement){if(n.tagName==='DETAILS') n.open=true;}")
    browser.wait("document.querySelector('#public-study .posterior-numbers strong')?.textContent.includes('estimated make chance')")
    before = js("document.querySelector('#public-study .posterior-numbers').textContent")
    js("document.querySelector('#public-study .posterior-court canvas').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true,cancelable:true}))")
    assert js("document.querySelector('#public-study .posterior-numbers').textContent") != before
    js("""document.querySelectorAll('#public-study .posterior-controls select').forEach((node,i)=>{
        node.value=i ? 'spread' : 'spde'; node.dispatchEvent(new Event('change',{bubbles:true}));})""")
    assert 'wider intervals' in js("document.querySelector('#public-study .posterior-aside .caption').textContent")
    js("document.querySelector('#public-study .posterior-view').scrollIntoView({block:'center'})")
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
        js("document.getElementById('headline').scrollIntoView({block:'start'})")
        assert js("[...document.querySelectorAll('#headline .diet-bar > div')].every(d => d.scrollWidth <= d.clientWidth + 1 && d.getBoundingClientRect().right <= innerWidth)"), width
        browser.save_image(f'atlas_headline_mobile_{width}.png')
        js("document.getElementById('team-report').scrollIntoView({block:'start'})")
        assert js("(() => { const t = document.getElementById('team-table'); return t.scrollWidth <= t.parentElement.clientWidth + 1 || t.parentElement.scrollWidth > t.parentElement.clientWidth; })()"), width
        browser.save_image(f'atlas_team_report_mobile_{width}.png')
        js("document.querySelectorAll('details.more').forEach(node => { node.open = true; })")
        assert js("[...document.querySelectorAll('.timing-card')].every(c => c.offsetWidth > 0 && c.getBoundingClientRect().right <= innerWidth)")
        assert js("(() => { const t = document.getElementById('area-table'); return t.scrollWidth <= t.parentElement.clientWidth && t.getBoundingClientRect().right <= innerWidth; })()"), width
        js("document.getElementById('areas-title').scrollIntoView({block:'start'})")
        spot = js("""(() => { const cell = document.querySelector('#area-rows tr[data-zone="4"] td');
            cell.scrollIntoView({block: 'center'});
            const box = cell.getBoundingClientRect();
            return [box.left + box.width / 2, box.top + box.height / 2]; })()""")
        browser.call('Emulation.setTouchEmulationEnabled', {'enabled': True})
        for kind, points in [('touchStart', [{'x': spot[0], 'y': spot[1]}]), ('touchEnd', [])]:
            browser.call('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': points})
        browser.wait("document.querySelector('#area-rows button[aria-pressed=true]')?.dataset.zone === '4'")
        assert js("document.querySelector('#court-primary canvas').dataset.area") == '4'
        browser.save_image(f'atlas_court_areas_mobile_{width}.png')
        pick_area(browser, None)
        js("document.getElementById('shot-mix').scrollIntoView({block:'start'})")
        assert js("document.getElementById('mix-chart').clientWidth > 220 && [...document.querySelectorAll('.mix-part')].every(c => c.getBoundingClientRect().right <= innerWidth)")
        browser.save_image(f'atlas_shot_mix_mobile_{width}.png')
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
    lab = json.loads((ROOT / 'explore/data/methods-lab.json').read_bytes())
    browser.call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
    browser.call('Page.navigate', {'url': urljoin(url, 'lab/')})
    browser.wait("location.pathname.endsWith('/lab/') && document.body?.dataset.ready === 'true'")
    assert js("document.querySelector('.tabs a[aria-current=page]').textContent") == 'Methods lab'
    shown = js("[...document.querySelectorAll('#lab-scores .relative-row[data-method]')].map(r => [r.dataset.method, r.querySelector('em').textContent])")
    assert shown == [[row['method'], f"{row['brier']:.5f}"] for row in lab['methods']], shown
    browser.wait("document.getElementById('lab-spot').textContent.includes('%')")
    for name in ('Gaussian process', 'Areal CAR model', 'Stacked ensemble'):
        browser.select('lab-method', name) if False else js(f"(() => {{ const s = document.getElementById('lab-method'); s.value = {json.dumps(name)}; s.dispatchEvent(new Event('change')); }})()")
        value = lab['surfaces'][name][15 * lab['grid']['cols'] + 25]
        assert js("document.getElementById('lab-spot').textContent").endswith(f'{100 * value:.1f}%'), name
    assert js("document.querySelectorAll('#lab-spot-all tbody tr').length") == len(lab['methods'])
    about = js("document.querySelector('#lab-surface .caption').textContent")
    assert ' In technical terms: ' in about and not about.startswith(' In technical terms'), about
    assert js("[...document.querySelectorAll('#lab-moran .area-line')].map(r => r.dataset.value)") == [f"{row['morans_i']:.3f}" for row in lab['moran']]
    assert js("[...document.querySelectorAll('#lab-weights .area-line')].map(r => Number(r.dataset.value))") == [row['weight'] for row in lab['weights']]
    browser.wait("(() => { const c = document.getElementById('lab-variogram'); return c.width > 100 && c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some(v => v > 0); })()")
    browser.wait("(() => { const c = document.querySelector('#lab-density canvas'); return c.width > 100 && c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some(v => v > 0); })()")
    assert f"{lab['intensity']['scores']['cox_process']:.4f}" in js("document.getElementById('lab-density').parentElement.textContent")
    browser.save_image('atlas_lab_desktop.png')
    browser.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
    time.sleep(.3)
    assert js("document.documentElement.scrollWidth <= innerWidth"), 'the methods lab overflows on a phone'
    browser.save_image('atlas_lab_mobile_390.png')
    browser.call('Page.navigate', {'url': urljoin(url, 'study/')})
    browser.wait("location.pathname.endsWith('/study/') && document.body?.dataset.ready==='true' && document.body.dataset.recoveryReady==='true'")
    assert js("window.wnbaCheck.shownAttempts") == 38441
    browser.call('Page.navigate', {'url': urljoin(url, 'meeting/')})
    browser.wait("location.pathname.endsWith('/meeting/') && document.body?.dataset.recoveryReady==='true' && [...document.images].every(i=>i.complete && i.naturalWidth>0)")
    assert not browser.errors, browser.errors[:3]
    print('ATLAS_BROWSER_VERIFIED', len(seasons), 'seasons, pooled totals, phases, shot types, spatial and event findings, posterior, themes, mobile, original study', flush=True)


class QuietHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

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
