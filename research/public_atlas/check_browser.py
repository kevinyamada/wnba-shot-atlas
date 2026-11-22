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
        for _ in range(120):
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


def verify(browser, url):
    atom = {row['season']: row for row in json.loads((ROOT/'explore/data/index.json').read_bytes())['coverage']}
    js = browser.js
    q = "document.querySelector('#court-primary [data-total=n]').textContent"
    arc = "document.querySelector('#court-primary canvas').dataset.arc"
    fmt = lambda n: f'{n:,}'
    browser.call('Emulation.setEmulatedMedia', {'features':[{'name':'prefers-color-scheme','value':'dark'}]})
    browser.call('Page.navigate', {'url':url})
    browser.wait("document.body?.dataset.ready==='true' && !document.querySelector('#comparison-callout').hidden")
    assert js("document.documentElement.dataset.theme") == 'light'
    assert js(q) == '38,535' and js("document.querySelector('#court-primary [data-total=points]').textContent") == '38,533'
    browser.save_image('explorer_desktop.png')
    for season, row in atom.items():
        browser.select('season', season)
        assert js(q) == fmt(row['regular']['attempts']), season
        assert abs(float(js(arc)) - (20 + 6.25/12 if season < 2013 else 22 + 1.75/12)) < 1e-10
    browser.select('phase', 1)
    assert js(q) == fmt(atom[2026]['playoffs']['attempts'])
    browser.select('phase', 'all')
    assert js(q) == fmt(atom[2026]['regular']['attempts'] + atom[2026]['playoffs']['attempts'])

    js("document.querySelector('#compare-rule').click()")
    browser.wait("document.querySelector('#court-secondary [data-year]').textContent==='2013'")
    assert js(q) == '26,863'
    assert js("document.querySelector('#court-secondary [data-total=n]').textContent") == '26,868'
    assert js("document.querySelector('#court-primary [data-arc]').textContent.includes('20 ft 6¼ in') && document.querySelector('#court-secondary [data-arc]').textContent.includes('22 ft 1¾ in')")
    assert '2,396' in js("document.querySelector('#arc-finding').textContent")
    assert '403' in js("document.querySelector('#arc-finding').textContent")
    browser.save_image('explorer_comparison.png')
    before = js("document.querySelector('#area-position').textContent")
    js("document.querySelector('#court-primary canvas').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true,cancelable:true}))")
    assert js("document.querySelector('#area-position').textContent") != before
    browser.wait("document.querySelector('#history-rows').rows.length===16")
    assert js("document.querySelector('#court-primary canvas').dataset.selected===document.querySelector('#court-secondary canvas').dataset.selected")
    js("(()=>{const canvas=document.querySelector('#court-secondary canvas'); const b=canvas.getBoundingClientRect(); canvas.dispatchEvent(new MouseEvent('click',{clientX:b.left + 15,clientY:b.top + 12,bubbles:true}));})()")
    assert js("document.querySelector('#court-secondary canvas').dataset.selected===document.querySelector('#court-primary canvas').dataset.selected")
    browser.select('zone', 3)
    assert js("document.querySelector('#area-title').textContent") == 'Corner three area'
    browser.wait("document.querySelector('#history-rows').rows.length===16")
    for metric in ('share','rate','points'):
        js(f"document.querySelector('[data-metric={metric}]').click()")
        assert js(f"document.querySelector('[data-metric={metric}]').getAttribute('aria-pressed')") == 'true'
    js("document.querySelector('#theme-toggle').click()")
    assert js("document.documentElement.dataset.theme") == 'dark'
    browser.save_image('explorer_comparison_dark.png')
    browser.call('Page.reload',{'ignoreCache':True})
    browser.wait("document.body?.dataset.ready==='true'")
    assert js("document.documentElement.dataset.theme") == 'dark'
    js("document.querySelector('#theme-toggle').click()")
    browser.select('team', 5)
    browser.wait("document.querySelector('#history-rows').rows.length===16")
    player = js("document.querySelector('#player').options[1].value")
    browser.select('player', player)
    browser.wait("document.querySelector('#history-rows').rows.length===16")
    expected = sum(row[5] for row in json.loads((ROOT/'explore/data/2025.json').read_bytes())['rows'] if row[:3]==[0,5,int(player)])
    assert expected > 0 and js(q) == fmt(expected)
    assert js("document.querySelector('#history-context').textContent.includes(document.querySelector('#player').selectedOptions[0].textContent)")
    browser.select('team', 'all')
    browser.select('player', 'all')
    for width in [390, 320]:
        browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':844,'deviceScaleFactor':1,'mobile':True})
        time.sleep(.2)
        assert js(f"innerWidth==={width} && document.documentElement.scrollWidth<=innerWidth && document.querySelector('#court-primary canvas').clientWidth>240")
        js("document.querySelector('#compare-rule').click()")
        browser.wait("document.querySelector('#court-secondary [data-year]').textContent==='2013' && !document.querySelector('#court-secondary').hidden")
        js("document.querySelectorAll('details').forEach(node=>node.open=true)")
        assert js('document.documentElement.scrollWidth<=innerWidth')
        js("document.querySelectorAll('details').forEach(node=>node.open=false)")
        browser.save_image(f'explorer_mobile_{width}.png', beyond=True)
    assert not browser.errors, browser.errors[:2]
    print('EXPLORER_BROWSER_PASS: 16 seasons, court rules, comparison, filters, area history, themes, 390 and 320 px.', flush=True)


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
                verify(browser, args.url or f'http://127.0.0.1:{server.server_port}/explore/')
            finally:
                browser.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
