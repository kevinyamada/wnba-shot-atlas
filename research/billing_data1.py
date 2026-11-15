"""Read Modal's usage export; publish only this study's resource totals."""
from pathlib import Path
import argparse
import datetime
import json
import os
import subprocess
from collections import defaultdict

HERE=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--modal-python',required=True);args=ap.parse_args()
    env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','NO_COLOR':'1'}
    result=subprocess.run([args.modal_python,'-m','modal','billing','report','--for','today','-r','h','--tag-names','project,source,run','--show-resources','--json'],capture_output=True,text=True,encoding='utf-8',env=env,check=True)
    rows=json.loads(result.stdout)
    (HERE/'data/billing_report_private.json').write_text(result.stdout,encoding='utf-8')
    kept=[]
    for r in rows:
        tags=r.get('tags') or {}
        if isinstance(tags,str):tags=json.loads(tags)
        if r.get('description','').startswith('wnba-atlas-data1-20261115') or (tags.get('source')=='data1' and tags.get('run')=='20261115'):
            kept.append(r)
    assert kept,'No project-attributed usage returned'
    costs=defaultdict(float)
    for r in kept:costs[r['resource']]+=float(r['cost'])
    usage_path=HERE/'results/data1/compute_usage.json'
    usage=json.loads(usage_path.read_text(encoding='utf-8'))
    usage['modal_billing']={'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'attribution':'Only description wnba-atlas-data1-20261115 or source=data1/run=20261115 tags',
        'by_resource':dict(costs),'total_usd_before_credits':sum(costs.values()),
        'interval_starts_utc':sorted({str(r['interval_start']) for r in kept}),
        'basis':'Modal billing report gross resource usage before credits; may include partial current-hour buckets and reporting delay. Not cash paid after credits.'}
    assert usage['modal_billing']['total_usd_before_credits']<40,'Total budget ceiling needs review'
    usage_path.write_text(json.dumps(usage,indent=2),encoding='utf-8')
    print(json.dumps(usage['modal_billing'],indent=2))


if __name__=='__main__':main()
