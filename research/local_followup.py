"""Bounded desktop-CPU follow-up using only existing Data (1) observations.

Two questions: does adding earlier validation games help a fixed primary model,
and do player-count-discrepant games materially affect identity-free models?
The published original comparison and GP surface remain the frozen baseline.
"""
from __future__ import annotations
import os
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:
    os.environ[name]='4'
from pathlib import Path
import argparse
import hashlib
import json
import platform
import subprocess
import time
import numpy as np
import pandas as pd
import catboost
from catboost import CatBoostClassifier
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import log_loss,roc_auc_score
from data1_cpu import distance_model

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1/followup'
PRIVATE=HERE/'data/data1/followup'
NUMERIC=['x','y','distance','angle','period_number','seconds','home','prior_rate','log_prior_n','preseason_rate','preseason_log_n']
FULL=NUMERIC+['player_id','team_id']
SAFE=['x','y','distance','angle','period_number','seconds','home','team_id']
KEYS=['source_row','game_id','game_play_number','split','made','points']


def score(y,p):
    p=np.asarray(p,float);assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
    return {'shots':len(y),'brier':float(np.mean((np.asarray(y)-p)**2)),'log_loss':float(log_loss(y,p)),
            'auc':float(roc_auc_score(y,p)),'mean_prediction':float(p.mean()),'observed':float(np.mean(y))}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();source=json.loads((HERE/'results/data1/source_audit.json').read_text(encoding='utf-8'))
    h=hashlib.sha256()
    with args.source.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    assert args.source.name=='Data (1).zip' and h.hexdigest()==source['archive_sha256']
    s=pd.read_csv(HERE/'data/data1/model_shots.csv.gz',dtype={'player_id':str,'team_id':str})
    raw=pd.read_csv(HERE/'data/data1/all_shots.csv.gz',dtype={'player_id':str,'team_id':str},low_memory=False)
    raw=raw[raw.scope.isin(['regular','playoffs'])&raw.x.between(-5.25,41.75)].copy()
    train=s[s.split.eq('train')].copy();validation=s[s.split.eq('validation')].copy();refit=s[s.split.isin(['train','validation'])].copy()
    later=s[s.split.isin(['test','playoffs'])].copy();hold=s[s.split.ne('train')].copy()
    all_train=raw[raw.split.eq('train')].copy()
    bad=set(pd.read_csv(HERE/'results/data1/excluded_games.csv').game_id)
    assert len(train)==25751 and len(refit)==31746 and len(all_train)==26686
    assert set(all_train.game_id)-set(train.game_id)<=bad
    assert train.date.max()<'2025-08-10' and refit.date.max()<'2025-08-27'
    assert not set(refit.game_id)&set(later.game_id)
    receipt={'only_data_source':'Data (1).zip','archive_sha256':h.hexdigest(),'runtime':'desktop CPU; no Modal calls',
             'python':platform.python_version(),'catboost':catboost.__version__,'scikit_learn':sklearn.__version__,'threads':4,
             'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip(),
             'model_table_sha256':hashlib.sha256((HERE/'data/data1/model_shots.csv.gz').read_bytes()).hexdigest(),
             'refit_rule':'Same CPU algorithm, three frozen GPU-validation-selected parameter sets and fixed tree counts; fit through August 9 versus August 26. No late-game tuning or early stopping.',
             'identity_free_rule':'Same fixed feature set excludes player ID, names, all player histories, outcome descriptions, score margin and inferred attempt values. Tune on eligible validation only, then hold settings fixed when adding the seven excluded early-season games.',
             'evaluation_limit':'Reused 2025 benchmark; the follow-up is a sensitivity study, not an untouched test or a reason to replace the frozen primary table.',
             'fits':[],'cohorts':{'early_eligible':len(train),'through_august_26_eligible':len(refit),'early_including_discrepant_games':len(all_train)},
             'started_utc':pd.Timestamp.now(tz='UTC').isoformat()}
    (OUT/'local_model_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    tables=[]
    def save(name,a,p):
        q=a[KEYS].copy();q['model']=name;q['prediction']=np.asarray(p,float)
        assert not q.source_row.duplicated().any() and np.isfinite(q.prediction).all()
        tables.append(q)
    # Matched CPU reference/refit, avoiding a CPU-versus-GPU confound.
    for label,training,evaluation in [('CPU CatBoost reference',train,hold),('CPU CatBoost refit',refit,later)]:
        predictions=[]
        for seed in [2026,2027,2028]:
            r=json.loads((HERE/f'results/data1/experiments/boost-main-{seed}-v214/task.json').read_text(encoding='utf-8'))
            assert r['source_archive_sha256']==source['archive_sha256']
            selected=r['selected']['CatBoost context']
            params={'iterations':int(selected['trees']),'depth':int(selected['depth']),'l2_leaf_reg':float(selected['penalty']),
                    'learning_rate':.035,'loss_function':'Logloss','boosting_type':'Plain','task_type':'CPU',
                    'thread_count':4,'random_seed':seed,'verbose':False,'allow_writing_files':False}
            m=CatBoostClassifier(**params)
            before=time.monotonic();m.fit(training[FULL],training.made,cat_features=['player_id','team_id'])
            assert m.get_all_params()['task_type']=='CPU'
            predictions.append(m.predict_proba(evaluation[FULL])[:,1])
            filename=label.lower().replace(' ','_')+f'_{seed}.cbm';m.save_model(str(PRIVATE/filename))
            fit={'model':label,'seed':seed,'train_shots':len(training),'train_games':int(training.game_id.nunique()),'last_training_date':training.date.max(),
                 'parameters':params,'seconds':time.monotonic()-before,'validation_not_scored_after_refit':label.endswith('refit')}
            receipt['fits'].append(fit);print('CPU_FIT_COMPLETE',label,seed,len(training),round(fit['seconds'],2),flush=True)
        save(label,evaluation,np.mean(predictions,axis=0))
    save('Distance reference',hold,distance_model(train,hold));save('Distance refit',later,distance_model(refit,later))
    levels=sorted(train.team_id.unique())
    def safe(a):
        x=a[SAFE].copy();x['team_id']=pd.Categorical(x.team_id.where(x.team_id.isin(levels)),categories=levels);return x
    best=None;candidates=[]
    for penalty in [5.,20.,80.]:
        params={'learning_rate':.05,'max_iter':300,'max_leaf_nodes':15,'max_depth':6,'min_samples_leaf':100,
                'l2_regularization':penalty,'max_bins':63,'early_stopping':False,'random_state':20261115,'categorical_features':'from_dtype'}
        m=HistGradientBoostingClassifier(**params).fit(safe(train),train.made)
        loss=float(log_loss(validation.made,m.predict_proba(safe(validation))[:,1]))
        candidates.append({'l2_regularization':penalty,'validation_log_loss':loss})
        if best is None or loss<best[0]:best=(loss,m,params)
    pd.DataFrame(candidates).to_csv(OUT/'identity_free_validation.csv',index=False)
    save('Identity-free HGB excluded games',hold,best[1].predict_proba(safe(hold))[:,1])
    included=HistGradientBoostingClassifier(**best[2]).fit(safe(all_train),all_train.made)
    save('Identity-free HGB included games',hold,included.predict_proba(safe(hold))[:,1])
    receipt['identity_free_parameters']=best[2]
    receipt['identity_free_features']=SAFE
    receipt['identity_free_added_training_shots']=len(all_train)-len(train)
    receipt['identity_free_added_training_games']=len(set(all_train.game_id)-set(train.game_id))
    receipt['identity_free_validation_shots']=len(validation)
    # Explicitly identify the validation rows whose player totals disagree;
    # these were never used for model selection.
    bad_validation=raw[raw.split.eq('validation')&raw.game_id.isin(bad)].copy()
    for name,m in [('Identity-free HGB excluded games',best[1]),('Identity-free HGB included games',included)]:
        q=bad_validation.copy();q['split']='excluded-game validation';save(name,q,m.predict_proba(safe(q))[:,1])
    predictions=pd.concat(tables,ignore_index=True)
    predictions.to_csv(PRIVATE/'local_predictions.csv.gz',index=False)
    metrics=[]
    for (model,split),a in predictions.groupby(['model','split']):metrics.append({'model':model,'split':split,**score(a.made,a.prediction)})
    pd.DataFrame(metrics).to_csv(OUT/'local_metrics.csv',index=False)
    paired=[]
    pairs=[('CPU CatBoost refit','CPU CatBoost reference'),('Distance refit','Distance reference'),
           ('Identity-free HGB included games','Identity-free HGB excluded games')]
    for split in ['validation','test','playoffs','excluded-game validation']:
        for name,baseline in pairs:
            a=predictions[predictions.model.eq(name)&predictions.split.eq(split)].set_index('source_row')
            b=predictions[predictions.model.eq(baseline)&predictions.split.eq(split)].set_index('source_row')
            if not len(a) or not len(b):continue
            assert set(a.index)==set(b.index);b=b.loc[a.index]
            error=(a.prediction-a.made)**2-(b.prediction-b.made)**2
            g=pd.DataFrame({'game':a.game_id,'error':error}).groupby('game').error.agg(['sum','count'])
            rng=np.random.default_rng(20261121);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
            values=(w@g['sum'].to_numpy())/(w@g['count'].to_numpy())
            paired.append({'split':split,'model':name,'baseline':baseline,'shots':len(a),'games':len(g),
                           'brier_difference':float(error.mean()),'lower':float(np.quantile(values,.025)),'upper':float(np.quantile(values,.975)),
                           'single_game_interval_is_not_inferential':len(g)==1})
    pd.DataFrame(paired).to_csv(OUT/'local_game_bootstrap.csv',index=False)
    receipt['completed_utc']=pd.Timestamp.now(tz='UTC').isoformat();receipt['elapsed_seconds']=time.monotonic()-started
    receipt['prediction_rows']=len(predictions);receipt['models']=sorted(predictions.model.unique())
    receipt['no_cloud_gpu_used']=True
    (OUT/'local_model_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('LOCAL_FOLLOWUP_COMPLETE',round(receipt['elapsed_seconds'],2),'seconds',flush=True)
    print(pd.DataFrame(metrics).query("split=='test'").to_string(index=False),flush=True)


if __name__=='__main__':main()
