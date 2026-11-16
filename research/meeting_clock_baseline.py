"""One fixed training only clock baseline to explain frozen model results.

This is a post hoc diagnostic, not a fresh test or model reselection.
"""
from pathlib import Path
import hashlib,json,time
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;BASE=HERE/'results/data1';OUT=BASE/'meeting';PRIVATE=HERE/'data/data1/possession'
EDGES=np.array([2,5,24,60,120,300,601]);ALPHA=50.0


def main():
    started=time.monotonic();source=json.loads((BASE/'possession/model_selection_receipt.json').read_text(encoding='utf-8'))
    s=pd.read_csv(PRIVATE/'model_states.csv.gz',float_precision='round_trip');train=s[s.split.eq('train')].copy()
    assert train.date.max()=='2025-08-09' and train.date.max()<s.loc[s.split.ne('train'),'date'].min()
    train['clock_bin']=np.digitize(train.seconds_remaining,EDGES)-1
    means=train.groupby('stage').remaining_points.mean().to_dict()
    values=train.groupby(['stage','clock_bin']).remaining_points.agg(['sum','count']).reset_index()
    values['stage_prior']=values.stage.map(means);values['expected_points']=(values['sum']+ALPHA*values.stage_prior)/(values['count']+ALPHA)
    lookup={(r.stage,r.clock_bin):r.expected_points for r in values.itertuples()}
    values.to_csv(OUT/'clock_baseline_training.csv',index=False)
    receipt={'only_data_source':'Data (1).zip','archive_sha256':source['archive_sha256'],'features':['stage','seconds_remaining'],
        'training_last_date':train.date.max(),'training_states':len(train),'clock_edges_seconds':EDGES.tolist(),'prior_strength':ALPHA,
        'definition':'Training mean in each state-type/period-clock bin, shrunk toward its training state-type mean with 50 pseudocounts.',
        'setting_selection':'Fixed diagnostic settings; no validation or later-period tuning. Uses the existing clock-bin boundaries.',
        'limit':'Designed after examining reused 2025 results. Exploratory explanation, not independent confirmation or a new selected model.',
        'runtime':'desktop CPU only','existing_selected_model_unchanged':source['selected_model'],
        'source_state_table_sha256':hashlib.file_digest((PRIVATE/'model_states.csv.gz').open('rb'),'sha256').hexdigest()}
    (OUT/'clock_baseline_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    # Parameters are frozen above before scoring any evaluation rows.
    pred=pd.read_csv(PRIVATE/'predictions.csv.gz',float_precision='round_trip')
    a=pred.merge(s[['state_id','seconds_remaining']],on='state_id',validate='one_to_one')
    a['Simple clock average']=[lookup.get((r.stage,int(np.digitize(r.seconds_remaining,EDGES)-1)),means[r.stage]) for r in a.itertuples()]
    a[['state_id','Simple clock average']].to_csv(HERE/'data/data1/possession/meeting_clock_predictions.csv.gz',index=False)
    metrics=[];pairs=[]
    for split in ['validation','test','playoffs']:
        for stage in ['entry','after_miss','after_offensive_rebound']:
            b=a[a.split.eq(split)&a.stage.eq(stage)]
            for model in ['Stage mean','Simple clock average',source['selected_model'],'Markov EPV']:
                error=(b[model]-b.remaining_points)**2
                metrics.append({'split':split,'stage':stage,'model':model,'states':len(b),'games':b.game_id.nunique(),'rmse':float(np.sqrt(error.mean())),'mae':float(abs(b[model]-b.remaining_points).mean())})
                if model=='Simple clock average':continue
                d=error-(b['Simple clock average']-b.remaining_points)**2
                g=pd.DataFrame({'game':b.game_id,'difference':d}).groupby('game').difference.agg(['sum','count'])
                rng=np.random.default_rng(20261122);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
                interval=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])
                pairs.append({'split':split,'stage':stage,'model':model,'baseline':'Simple clock average','states':len(b),'games':len(g),
                    'mse_difference':float(d.mean()),'lower':float(interval[0]),'upper':float(interval[1])})
    pd.DataFrame(metrics).to_csv(OUT/'clock_baseline_metrics.csv',index=False);pd.DataFrame(pairs).to_csv(OUT/'clock_baseline_comparisons.csv',index=False)
    receipt['elapsed_seconds']=time.monotonic()-started;(OUT/'clock_baseline_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('CLOCK_DIAGNOSTIC_COMPLETE',flush=True)
    print(pd.DataFrame(metrics).query("stage=='entry'").to_string(index=False),flush=True)
    print(pd.DataFrame(pairs).query("stage=='entry' and split!='validation'").to_string(index=False),flush=True)


if __name__=='__main__':main()
