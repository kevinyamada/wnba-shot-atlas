"""Exercise the actual public/local app in an isolated Chrome session.

Operated on the authorized desktop through Desktop Commander. The temporary
browser profile has no user accounts. Screenshots and logs stay outside Git.
"""
from pathlib import Path
import argparse
import base64
import json
import os
import subprocess
import time
import urllib.request
import websocket

HERE=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--url',required=True);ap.add_argument('--final',action='store_true');args=ap.parse_args()
    root=HERE/'data/site_check';root.mkdir(parents=True,exist_ok=True)
    chrome=next(p for p in [Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',Path('C:/Program Files (x86)/Google/Chrome/Application/chrome.exe')] if p.exists())
    process=subprocess.Popen([str(chrome),'--headless=new','--disable-gpu','--remote-debugging-port=9337','--remote-allow-origins=*',f'--user-data-dir={root / "profile"}','--window-size=1440,1000','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    ws=None
    try:
        for _ in range(100):
            try:
                tabs=json.load(urllib.request.urlopen('http://127.0.0.1:9337/json',timeout=2))
                target=next(t for t in tabs if t.get('type')=='page');break
            except Exception:time.sleep(.2)
        else:raise RuntimeError('Isolated Chrome did not start')
        ws=websocket.create_connection(target['webSocketDebuggerUrl'],timeout=30,suppress_origin=True)
        serial=0;events=[]
        def call(method,params=None):
            nonlocal serial
            serial+=1;ws.send(json.dumps({'id':serial,'method':method,'params':params or {}}))
            while True:
                r=json.loads(ws.recv())
                if r.get('id')==serial:
                    assert 'error' not in r,r
                    return r.get('result',{})
                events.append(r)
        def js(expression):
            r=call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            assert 'exceptionDetails' not in r,r
            return r['result'].get('value')
        call('Runtime.enable');call('Page.enable');call('Log.enable');call('Network.enable')
        call('Network.setCacheDisabled',{'cacheDisabled':True});call('Page.navigate',{'url':args.url})
        for _ in range(100):
            if js('Boolean(document.body && document.body.dataset.ready === "true")'):break
            time.sleep(.2)
        else:raise RuntimeError('App did not finish loading')
        tests=[]
        def check(name,expression):
            value=js(expression);assert value, (name,value)
            tests.append(name)
        check('Source identity and visible totals',"D.source.only_data_source==='Data (1).zip' && D.source.regular_attempts===38535 && window.wnbaCheck.shownAttempts===38441 && window.wnbaCheck.shownMakes===16926 && window.wnbaCheck.shownPoints===38533")
        check('Thirteen archive-sourced teams',"Object.keys(D.teams).length===13 && document.querySelector('#team').options.length===14")
        # All teams, all sizes, both descriptive modes: exact displayed totals.
        check('All team filters and cell sizes',"(()=>{for(const mode of ['attempts','rate'])for(const size of [1,2,4])for(const team of ['all',...Object.keys(D.teams)]){document.querySelector('#metric').value=mode;document.querySelector('#size').value=size;document.querySelector('#team').value=team;renderCourt();const q=D.cells.filter(r=>team==='all'||String(r[2])===team);for(const [key,col] of [['shownAttempts',4],['shownMakes',5],['shownPoints',6]])if(window.wnbaCheck[key]!==q.reduce((a,r)=>a+r[col],0))return false;}return true;})()")
        check('Known one-foot Indiana square from source',"(()=>{document.querySelector('#metric').value='attempts';document.querySelector('#size').value='1';document.querySelector('#team').value='5';renderCourt();return current.n===51&&current.k===31&&current.points===62&&document.querySelector('#leaders').textContent.includes('Natasha Howard: 16 points');})()")
        check('Posterior and uncertainty maps',"(()=>{for(const mode of ['gp','uncertainty']){const el=document.querySelector('#metric');el.value=mode;el.dispatchEvent(new Event('change'));if(!document.querySelector('#team').disabled||document.querySelector('#team').value!=='all'||window.wnbaCheck.shownAttempts!==38441)return false;if(!document.querySelector('#cell-rate').textContent.includes('credible interval'))return false;}return true;})()")
        check('Arrow-key selection',"(()=>{const before=current;document.querySelector('#court').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true}));return current.i===before.i+1&&current.j===before.j&&!document.querySelector('#unpin').hidden;})()")
        check('Tap selection and clear',"(()=>{cells[20].el.dispatchEvent(new MouseEvent('click',{bubbles:true}));if(current!==cells[20]||!pinned)return false;document.querySelector('#unpin').click();return !pinned&&document.querySelector('#unpin').hidden;})()")
        check('Every evaluation table',"(()=>{for(const split of ['validation','test','playoffs']){document.querySelector('#evaluation').value=split;results();if(document.querySelectorAll('#results tr').length!==D.metrics.filter(r=>r.split===split).length||!document.querySelector('#result-note').textContent.includes(Number(D.metrics.find(r=>r.split===split).shots).toLocaleString('en-CA')))return false;}return true;})()")
        check('Desktop CPU follow-up tables',"(()=>{if(!D.localFollowup||!D.localFollowup.receipt.no_cloud_gpu_used)return false;for(const split of ['test','playoffs']){document.querySelector('#followup-period').value=split;followupResults();const expected=D.localFollowup.metrics.filter(r=>r.split===split),rows=[...document.querySelectorAll('#followup-results tr')];if(rows.length!==expected.length||rows.length!==6)return false;for(let i=0;i<rows.length;i++){const cells=rows[i].children;if(cells[0].textContent!==expected[i].model||cells[1].textContent!==expected[i].brier.toFixed(5)||cells[2].textContent!==expected[i].log_loss.toFixed(5))return false;}}return true;})()")
        check('Mesh, variogram, and all buffers',"(()=>{for(const kind of ['buffer','mesh','variogram']){document.querySelector('#geometry').value=kind;for(const buffer of [0,2,4]){document.querySelector('#buffer').value=buffer;geometry();if(!document.querySelector('#geometry-chart').children.length||!document.querySelector('#geometry-note').textContent)return false;}}return true;})()")
        check('Finite SVG geometry',"[...document.querySelectorAll('svg *')].every(e=>[...e.attributes].every(a=>!/(NaN|Infinity|undefined)/.test(a.value)))")
        check('No broken or empty links',"[...document.querySelectorAll('a')].every(a=>a.getAttribute('href')&& !a.href.includes('/wnba/'))")
        # Capture the app in its normal starting state at desktop and phone widths.
        js("document.querySelector('#metric').value='attempts';document.querySelector('#metric').dispatchEvent(new Event('change'));document.querySelector('#team').value='all';document.querySelector('#size').value='2';document.querySelector('#evaluation').value='test';document.querySelector('#geometry').value='buffer';document.querySelector('#buffer').value='2';renderCourt();results();geometry();window.scrollTo(0,0)")
        for name,width,height,mobile in [('desktop',1440,1000,False),('mobile',390,844,True)]:
            call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':mobile})
            time.sleep(.25)
            check(name+' layout fits viewport',"document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector('#court').getBoundingClientRect().width>200 && document.querySelector('#load-error').hidden")
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True})
            (root/(name+'.png')).write_bytes(base64.b64decode(shot['data']))
        errors=[e for e in events if e.get('method')=='Runtime.exceptionThrown' or (e.get('method')=='Log.entryAdded' and e.get('params',{}).get('entry',{}).get('level')=='error' and 'favicon' not in (e.get('params',{}).get('entry',{}).get('url','')+e.get('params',{}).get('entry',{}).get('text','')))]
        assert not errors,errors
        result={'url':args.url,'completed_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cache_disabled':True,'checks':tests,'all_pass':True,'javascript_errors':0,'viewport_widths':[1440,390],
                'stage':'final live verification' if args.final else 'development browser check'}
        out=HERE/'results/data1'/('live_site_checks.json' if args.final else 'development_site_checks.json')
        out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    finally:
        if ws:
            try:call('Browser.close')
            except Exception:pass
            ws.close()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.terminate()


if __name__=='__main__':main()
