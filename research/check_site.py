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
RECOVERY_CHECK="""(()=>{const p=window.recoveryCheck?.data;if(!p||p.source.only_data_source!=='Data (1).zip')return false;for(const policy of ['first_rebound','second_rebound'])for(const split of ['test','playoffs'])for(const cohort of ['all','original','recovered'])for(const stage of ['entry','after_miss','after_offensive_rebound'])for(const allModels of [false,true]){for(const [id,value] of [['policy',policy],['period',split],['cohort',cohort],['stage',stage]])document.querySelector('#recovery-'+id).value=value;document.querySelector('#recovery-all-models').checked=allModels;window.recoveryCheck.render();const wanted=window.recoveryCheck.rows,rows=[...document.querySelectorAll('#recovery-results tr')],expected=p.metrics.filter(r=>r.policy===policy&&r.split===split&&r.cohort===cohort&&r.stage===stage);if(rows.length!==wanted.length||rows.length!==(allModels?8:4))return false;for(let i=0;i<rows.length;i++){const r=expected.find(r=>r.model===wanted[i]);if(rows[i].dataset.model!==r.model||rows[i].children[1].textContent!==r.rmse.toFixed(5)||rows[i].children[2].textContent!==r.mae.toFixed(5))return false;}if(!document.querySelector('#recovery-note').textContent.includes(Number(expected[0].states).toLocaleString('en-CA')))return false;const c=p.coverage.find(r=>r.policy===policy);if(!document.querySelector('#recovery-counts').textContent.includes(Number(c.added_entry_states).toLocaleString('en-CA')))return false;}return document.querySelector('#recovery-error').hidden;})()"""
RECOVERY_RESET="for(const [id,value] of [['policy','first_rebound'],['period','test'],['cohort','all'],['stage','entry']])document.querySelector('#recovery-'+id).value=value;document.querySelector('#recovery-all-models').checked=false;window.recoveryCheck.render();"
SET_DARK="if(document.documentElement.dataset.theme!=='dark')document.querySelector('#theme-toggle').click();"
SET_LIGHT="if(document.documentElement.dataset.theme!=='light')document.querySelector('#theme-toggle').click();"


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
        call('Network.setCacheDisabled',{'cacheDisabled':True})
        call('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-color-scheme','value':'dark'}]})
        reset=call('Page.addScriptToEvaluateOnNewDocument',{'source':"try{localStorage.removeItem('wnba-theme');}catch{}"})
        call('Page.navigate',{'url':args.url})
        for _ in range(100):
            if js('Boolean(document.body && document.body.dataset.ready === "true" && document.body.dataset.recoveryReady === "true")'):break
            time.sleep(.2)
        else:raise RuntimeError('App did not finish loading')
        tests=[]
        def check(name,expression):
            value=js(expression);assert value, (name,value)
            tests.append(name)
        call('Page.removeScriptToEvaluateOnNewDocument',{'identifier':reset['identifier']})
        check('Fresh visits default to light even with a dark system theme',"matchMedia('(prefers-color-scheme: dark)').matches && localStorage.getItem('wnba-theme')===null && document.documentElement.dataset.theme==='light' && getComputedStyle(document.body).backgroundColor==='rgb(255, 255, 255)'")
        js(SET_LIGHT);js(SET_DARK)
        check('Small dark mode toggle',"document.querySelector('#theme-toggle').getBoundingClientRect().width<=40 && document.querySelector('#theme-toggle').getAttribute('aria-pressed')==='true' && document.querySelector('#theme-toggle').getAttribute('aria-label')==='Switch to light mode' && localStorage.getItem('wnba-theme')==='dark' && getComputedStyle(document.body).backgroundColor==='rgb(17, 25, 31)'")
        call('Page.reload',{'ignoreCache':True})
        for _ in range(100):
            if js('Boolean(document.body && document.body.dataset.ready === "true" && document.body.dataset.recoveryReady === "true")'):break
            time.sleep(.2)
        else:raise RuntimeError('Reload did not finish')
        check('Dark mode preference survives reload',"document.documentElement.dataset.theme==='dark' && document.querySelector('#theme-toggle').getAttribute('aria-pressed')==='true'")
        js(SET_LIGHT)
        check('Light mode toggle restores readable surface',"document.documentElement.dataset.theme==='light' && localStorage.getItem('wnba-theme')==='light' && getComputedStyle(document.body).backgroundColor==='rgb(255, 255, 255)'")
        check('Source identity and visible totals',"D.source.only_data_source==='Data (1).zip' && D.source.regular_attempts===38535 && window.wnbaCheck.shownAttempts===38441 && window.wnbaCheck.shownMakes===16926 && window.wnbaCheck.shownPoints===38533")
        check('Thirteen archive sourced teams',"Object.keys(D.teams).length===13 && document.querySelector('#team').options.length===14")
        # All teams, all sizes, both descriptive modes: exact displayed totals.
        check('All team filters and cell sizes',"(()=>{for(const mode of ['attempts','rate'])for(const size of [1,2,4])for(const team of ['all',...Object.keys(D.teams)]){document.querySelector('#metric').value=mode;document.querySelector('#size').value=size;document.querySelector('#team').value=team;renderCourt();const q=D.cells.filter(r=>team==='all'||String(r[2])===team);for(const [key,col] of [['shownAttempts',4],['shownMakes',5],['shownPoints',6]])if(window.wnbaCheck[key]!==q.reduce((a,r)=>a+r[col],0))return false;}return true;})()")
        check('Known one foot Indiana square from source',"(()=>{document.querySelector('#metric').value='attempts';document.querySelector('#size').value='1';document.querySelector('#team').value='5';renderCourt();return current.n===51&&current.k===31&&current.points===62&&document.querySelector('#leaders').textContent.includes('Natasha Howard: 16 points');})()")
        check('Posterior and uncertainty maps',"(()=>{for(const mode of ['gp','uncertainty']){const el=document.querySelector('#metric');el.value=mode;el.dispatchEvent(new Event('change'));if(!document.querySelector('#team').disabled||document.querySelector('#team').value!=='all'||window.wnbaCheck.shownAttempts!==38441)return false;if(!document.querySelector('#cell-rate').textContent.includes('credible interval'))return false;}return true;})()")
        check('Arrow key selection',"(()=>{const before=current;document.querySelector('#court').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true}));return current.i===before.i+1&&current.j===before.j&&!document.querySelector('#unpin').hidden;})()")
        check('Tap selection and clear',"(()=>{cells[20].el.dispatchEvent(new MouseEvent('click',{bubbles:true}));if(current!==cells[20]||!pinned)return false;document.querySelector('#unpin').click();return !pinned&&document.querySelector('#unpin').hidden;})()")
        check('Every evaluation table',"(()=>{for(const split of ['validation','test','playoffs']){document.querySelector('#evaluation').value=split;results();if(document.querySelectorAll('#results tr').length!==D.metrics.filter(r=>r.split===split).length||!document.querySelector('#result-note').textContent.includes(Number(D.metrics.find(r=>r.split===split).shots).toLocaleString('en-CA')))return false;}return true;})()")
        check('Desktop CPU follow up tables',"(()=>{if(!D.localFollowup||!D.localFollowup.receipt.no_cloud_gpu_used)return false;for(const split of ['test','playoffs']){document.querySelector('#followup-period').value=split;followupResults();const expected=D.localFollowup.metrics.filter(r=>r.split===split),rows=[...document.querySelectorAll('#followup-results tr')];if(rows.length!==expected.length||rows.length!==6)return false;for(let i=0;i<rows.length;i++){const cells=rows[i].children;if(cells[0].textContent!==expected[i].model||cells[1].textContent!==expected[i].brier.toFixed(5)||cells[2].textContent!==expected[i].log_loss.toFixed(5))return false;}}return true;})()")
        check('Possession EPV controls and tables',"(()=>{const p=D.possessionValue;if(!p||p.selection.runtime!=='desktop CPU only'||p.audit.eligible_entry_states!==25306)return false;for(const split of ['validation','test','playoffs'])for(const stage of ['entry','after_miss','after_offensive_rebound']){document.querySelector('#possession-period').value=split;document.querySelector('#possession-stage').value=stage;possessionResults();const expected=p.metrics.filter(r=>r.split===split&&r.stage===stage).sort((a,b)=>a.rmse-b.rmse),rows=[...document.querySelectorAll('#possession-results tr')];if(rows.length!==5||rows.length!==expected.length)return false;for(let i=0;i<rows.length;i++)if(rows[i].children[0].textContent!==expected[i].model||rows[i].children[1].textContent!==expected[i].rmse.toFixed(5)||rows[i].children[2].textContent!==expected[i].mae.toFixed(5))return false;if(document.querySelector('#possession-results .selected td').textContent!==p.selection.selected_model)return false;const bins=p.summary.filter(r=>r.split===split&&r.stage===stage);if(document.querySelectorAll('#possession-chart circle').length!==2*bins.length)return false;const calibration=p.calibration.filter(r=>r.split===split&&r.stage===stage&&r.model===p.selection.selected_model);if(document.querySelectorAll('#possession-calibration tr').length!==calibration.length||calibration.reduce((v,r)=>v+r.states,0)!==expected[0].states)return false;}return true;})()")
        check('Recovery controls and tables',RECOVERY_CHECK)
        js(RECOVERY_RESET)
        check('Mesh, variogram, and all buffers',"(()=>{for(const kind of ['buffer','mesh','variogram']){document.querySelector('#geometry').value=kind;for(const buffer of [0,2,4]){document.querySelector('#buffer').value=buffer;geometry();if(!document.querySelector('#geometry-chart').children.length||!document.querySelector('#geometry-note').textContent)return false;}}return true;})()")
        check('Finite SVG geometry',"[...document.querySelectorAll('svg *')].every(e=>[...e.attributes].every(a=>!/(NaN|Infinity|undefined)/.test(a.value)))")
        check('No broken or empty links',"[...document.querySelectorAll('a')].every(a=>a.getAttribute('href')&& !a.href.includes('/wnba/'))")
        # Capture the app in its normal starting state at desktop and phone widths.
        js("document.querySelector('#metric').value='attempts';document.querySelector('#metric').dispatchEvent(new Event('change'));document.querySelector('#team').value='all';document.querySelector('#size').value='2';document.querySelector('#evaluation').value='test';document.querySelector('#geometry').value='buffer';document.querySelector('#buffer').value='2';document.querySelector('#possession-period').value='test';document.querySelector('#possession-stage').value='entry';renderCourt();results();geometry();possessionResults();window.scrollTo(0,0)")
        for name,width,height,mobile in [('desktop',1440,1000,False),('mobile',390,844,True)]:
            call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':mobile})
            time.sleep(.25)
            check(name+' layout fits viewport',"document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector('#court').getBoundingClientRect().width>200 && document.querySelector('#load-error').hidden")
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True})
            (root/(name+'.png')).write_bytes(base64.b64decode(shot['data']))
            box=js("(()=>{const b=document.querySelector('#possession-value').getBoundingClientRect();return {x:b.x+scrollX,y:b.y+scrollY,width:b.width,height:b.height,scale:1};})()")
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box})
            (root/('possession-'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
            box=js("(()=>{const b=document.querySelector('#recovery').getBoundingClientRect();return {x:b.x+scrollX,y:b.y+scrollY,width:b.width,height:b.height,scale:1};})()")
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box})
            (root/('recovery-'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
            js(SET_DARK)
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});(root/(name+'-dark.png')).write_bytes(base64.b64decode(shot['data']))
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box});(root/('recovery-'+name+'-dark.png')).write_bytes(base64.b64decode(shot['data']))
            js(SET_LIGHT)
        js(SET_DARK)
        call('Page.navigate',{'url':args.url.rstrip('/')+'/meeting/'})
        for _ in range(100):
            if js('Boolean(document.querySelector("#meeting-main") && document.body.dataset.recoveryReady === "true" && [...document.images].every(i=>i.complete&&i.naturalWidth>0))'):break
            time.sleep(.2)
        else:raise RuntimeError('Meeting walkthrough did not finish loading')
        check('Dark mode persists across meeting navigation',"document.documentElement.dataset.theme==='dark' && document.querySelector('#theme-toggle').getAttribute('aria-pressed')==='true'")
        check('Meeting walkthrough controls and layout',RECOVERY_CHECK)
        js(RECOVERY_RESET)
        for name,width,height,mobile in [('desktop',1440,1000,False),('mobile',390,844,True)]:
            call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':mobile});time.sleep(.2)
            check('Meeting '+name+' fits viewport',"document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector('#recovery-error').hidden && document.images.length===3 && [...document.images].every(i=>i.naturalWidth>0)")
            js(SET_DARK)
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True});(root/('meeting-'+name+'-dark.png')).write_bytes(base64.b64decode(shot['data']))
            js(SET_LIGHT)
            shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True});(root/('meeting-'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
        js(SET_DARK)
        call('Emulation.setEmulatedMedia',{'media':'print'})
        check('Meeting print stylesheet',"getComputedStyle(document.querySelector('header')).display==='none' && getComputedStyle(document.querySelector('.controls')).display==='none' && getComputedStyle(document.body).backgroundColor==='rgb(255, 255, 255)'")
        call('Emulation.setEmulatedMedia',{'media':''})
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
