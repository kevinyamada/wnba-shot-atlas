"""Independent final verification of the source investigation and CPU follow up."""
from pathlib import Path
from collections import defaultdict
import argparse
import csv
import io
import json
import math
import time
import zipfile
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from catboost import CatBoostClassifier

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1/followup'
PRIVATE=HERE/'data/data1/followup'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args()
    checks=[]
    def passed(name,condition):
        assert condition,name
        checks.append(name);print('CHECK',name,flush=True)
    receipt=json.loads((OUT/'local_model_receipt.json').read_text(encoding='utf-8'))
    original=json.loads((HERE/'results/data1/final_verification.json').read_text(encoding='utf-8'))
    passed('Primary original archive final verification has passed for this source',original['all_checks_pass'] and receipt['archive_sha256']==original['archive_sha256'])
    predictions=pd.read_csv(PRIVATE/'local_predictions.csv.gz',float_precision='round_trip')
    table=pd.read_csv(HERE/'data/data1/model_shots.csv.gz',dtype={'player_id':str,'team_id':str},float_precision='round_trip')
    all_shots=pd.read_csv(HERE/'data/data1/all_shots.csv.gz',low_memory=False).set_index('source_row')
    passed('Every local prediction has a unique model/source key',not predictions.duplicated(['source_row','model']).any())
    joined=predictions.merge(all_shots[['game_id','game_play_number','made','points']],left_on='source_row',right_index=True,how='left',validate='many_to_one',suffixes=('','_source'))
    passed('All local prediction labels and event keys match archive verified source rows',all(joined[c].eq(joined[c+'_source']).all() for c in ['game_id','game_play_number','made','points']))
    passed('All local probabilities are finite and bounded',np.isfinite(predictions.prediction).all() and predictions.prediction.between(0,1).all())
    metrics=pd.read_csv(OUT/'local_metrics.csv')
    for r in metrics.to_dict('records'):
        a=predictions[predictions.model.eq(r['model'])&predictions.split.eq(r['split'])]
        y=a.made.to_numpy(float);p=a.prediction.to_numpy(float);positive=y.sum();negative=len(y)-positive
        values={'shots':len(y),'brier':np.mean((y-p)**2),'log_loss':-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)),
                'auc':(rankdata(p)[y==1].sum()-positive*(positive+1)/2)/(positive*negative),'mean_prediction':p.mean(),'observed':y.mean()}
        assert all(np.isclose(r[k],v,atol=1e-12,rtol=1e-10) for k,v in values.items()),r
    checks.append('Every CPU Brier score, log loss, AUC, count and mean recomputes independently')
    for r in pd.read_csv(OUT/'local_game_bootstrap.csv').to_dict('records'):
        a=predictions[predictions.model.eq(r['model'])&predictions.split.eq(r['split'])].set_index('source_row')
        b=predictions[predictions.model.eq(r['baseline'])&predictions.split.eq(r['split'])].set_index('source_row').loc[a.index]
        difference=(a.prediction-a.made)**2-(b.prediction-b.made)**2
        g=pd.DataFrame({'game':a.game_id,'difference':difference}).groupby('game').difference.agg(['sum','count'])
        rng=np.random.default_rng(20261121);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
        interval=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])
        assert np.isclose(difference.mean(),r['brier_difference']) and np.allclose(interval,[r['lower'],r['upper']],atol=1e-12)
        assert bool(r['single_game_interval_is_not_inferential'])==(len(g)==1)
    checks.append('All paired game bootstrap differences and intervals recompute; single game cases are flagged')
    passed('No refit score is reported on its own validation training data',not ((metrics.model.str.endswith('refit'))&metrics.split.eq('validation')).any())
    for model,count in [('CPU CatBoost reference',25751),('CPU CatBoost refit',31746)]:
        fits=[r for r in receipt['fits'] if r['model']==model]
        assert len(fits)==3 and all(r['parameters']['task_type']=='CPU' and r['parameters']['thread_count']==4 and r['train_shots']==count for r in fits)
        cutoff='2025-08-09' if count==25751 else '2025-08-26'
        assert all(r['last_training_date']==cutoff for r in fits)
        for r in fits:
            selected=json.loads((HERE/f"results/data1/experiments/boost-main-{r['seed']}-v214/task.json").read_text(encoding='utf-8'))['selected']['CatBoost context']
            assert r['parameters']['iterations']==selected['trees'] and r['parameters']['depth']==selected['depth'] and r['parameters']['l2_leaf_reg']==selected['penalty']
        # Independently load the saved CPU weights and check a spread of rows.
        p=predictions[predictions.model.eq(model)].sort_values('source_row')
        sample=p.iloc[np.linspace(0,len(p)-1,200,dtype=int)]
        features=table.set_index('source_row').loc[sample.source_row]
        columns=['x','y','distance','angle','period_number','seconds','home','prior_rate','log_prior_n','preseason_rate','preseason_log_n','player_id','team_id']
        values=[]
        for seed in [2026,2027,2028]:
            m=CatBoostClassifier();m.load_model(str(PRIVATE/(model.lower().replace(' ','_')+f'_{seed}.cbm')))
            values.append(m.predict_proba(features[columns],thread_count=4)[:,1])
        assert np.allclose(np.mean(values,axis=0),sample.prediction,atol=1e-12,rtol=1e-12)
    checks.append('Frozen settings, chronological cutoffs, CPU only training and saved model predictions verify')
    passed('Identity free sensitivity excludes every uncertain shooter/history/outcome field',set(receipt['identity_free_features'])=={'x','y','distance','angle','period_number','seconds','home','team_id'} and receipt['identity_free_added_training_shots']==935 and receipt['identity_free_added_training_games']==7)
    raw_train=all_shots[all_shots.split.eq('train')&all_shots.scope.eq('regular')&all_shots.x.between(-5.25,41.75)]
    extra=raw_train.loc[raw_train.index.difference(table.loc[table.split.eq('train'),'source_row'])]
    excluded=set(pd.read_csv(HERE/'results/data1/excluded_games.csv').game_id)
    passed('The 935 added attempts are precisely the seven earlier excluded games',len(raw_train)==26686 and len(extra)==935 and extra.game_id.nunique()==7 and set(extra.game_id)<=excluded and extra.date.max()<'2025-08-10')
    selected=pd.read_csv(OUT/'identity_free_validation.csv').sort_values('validation_log_loss').iloc[0]
    expected=metrics[metrics.model.eq('Identity-free HGB excluded games')&metrics.split.eq('validation')].iloc[0]
    passed('Identity free settings were selected on eligible validation loss',np.isclose(selected.validation_log_loss,expected.log_loss) and selected.l2_regularization==receipt['identity_free_parameters']['l2_regularization'])
    # Fresh stdlib parsing verifies the discrepancy examples, independent of
    # the investigator's pandas groupby and name parser.
    with zipfile.ZipFile(args.source) as z:
        def read(suffix):return list(csv.DictReader(io.TextIOWrapper(z.open(next(n for n in z.namelist() if n.endswith(suffix))),encoding='utf-8-sig',newline='')))
        events=read('/original/wehoop_wnba_pbp.csv');players=read('/WNBA_player/wnba_player_box.csv')
    counts=defaultdict(int);names={};box_counts={}
    for r in events:
        if r['shooting_play'].lower()=='true' and 'free throw' not in r['type_text'].lower():counts[(int(r['game_id']),int(float(r['athlete_id_1'])))]+=1
    for r in players:
        if int(r['season'])!=2025:continue
        key=(int(r['game_id']),int(float(r['athlete_id'])));names[key]=r['athlete_display_name'];box_counts[key]=0 if r['field_goals_attempted'].strip().lower() in ['', 'na','nan','null'] else float(r['field_goals_attempted'])
    bad={k for k,n in counts.items() if n!=box_counts[k]}
    examples=pd.read_csv(OUT/'attempt_discrepancy_examples.csv')
    for r in examples.to_dict('records'):
        key=(r['game_id'],r['athlete_id_1']);assert key in bad and r['athlete_display_name']==names[key]
        assert r['event_attempts']==counts[key] and r['field_goals_attempted']==box_counts[key]
    passed('All 18 named discrepancy examples independently match the raw ZIP and boxes',len(examples)==len(bad)==18 and len({k[0] for k in bad})==8)
    row=pd.read_csv(OUT/'text_actor_disagreements.csv').iloc[0];raw=events[int(row.source_row)-2]
    passed('Description/ID contradiction is an actual archive record',int(raw['game_id'])==row.game_id and int(float(raw['athlete_id_1']))==row.athlete_id and raw['text'].startswith(row.text_name+' misses'))
    site=json.loads((HERE.parent/'assets/data.json').read_text(encoding='utf-8'))['localFollowup']
    passed('Published desktop tables, intervals and receipt match checked files',site['metrics']==metrics.to_dict('records') and site['paired']==pd.read_csv(OUT/'local_game_bootstrap.csv').to_dict('records') and site['receipt']==receipt)
    passed('Follow up source is the same original archive and no cloud GPU is used',receipt['no_cloud_gpu_used'] and site['sourceInvestigation']['only_data_source']=='Data (1).zip')
    result={'all_checks_pass':True,'checks':checks,'archive_sha256':receipt['archive_sha256'],'completed_utc':pd.Timestamp.now(tz='UTC').isoformat(),
            'analysis_commit':original['analysis_commit'],'only_data_source':'Data (1).zip','compute':'desktop CPU only'}
    (OUT/'final_followup_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('FINAL_FOLLOWUP_CHECKS',len(checks),'ALL_PASS',True)


if __name__=='__main__':main()
