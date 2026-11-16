"""Fixed setting CPU recovery refits and matched frozen model comparisons."""
import os
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[key]='4'
from pathlib import Path
import hashlib,json,time
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from possession_reconstruction import FEATURES
from possession_models import MarkovValue,CATEGORICAL,EDGES
from possession_recovery import POLICIES,digest

HERE=Path(__file__).resolve().parent;BASE=HERE/'results/data1';OUT=BASE/'recovery';PRIVATE=HERE/'data/data1/recovery';OLD=HERE/'data/data1/possession'
NAMES=['Frozen average','Expanded average','Frozen clock','Expanded clock','Frozen context','Expanded context','Frozen Markov','Expanded Markov']


class ClockMean:
    def __init__(self,alpha=50.):self.alpha=alpha
    def fit(self,a):
        self.means=a.groupby('stage').remaining_points.mean().to_dict()
        x=a.assign(clock_bin=np.digitize(a.seconds_remaining,EDGES)-1).groupby(['stage','clock_bin']).remaining_points.agg(['sum','count']).reset_index()
        self.values={(r.stage,int(r.clock_bin)):(r.sum+self.alpha*self.means[r.stage])/(r.count+self.alpha) for r in x.itertuples()}
        return self
    def predict(self,a):return np.array([self.values.get((r.stage,int(np.digitize(r.seconds_remaining,EDGES)-1)),self.means[r.stage]) for r in a.itertuples()])


def context_matrix(a,levels):
    x=a[FEATURES].copy()
    for c in CATEGORICAL:x[c]=pd.Categorical(x[c].where(x[c].isin(levels[c])),categories=levels[c])
    return x


def predict_all(a,frozen,fits,frozen_clock):
    return {'Frozen average':a.stage.map(frozen['stage_means']).to_numpy(float),'Expanded average':a.stage.map(fits['means']).to_numpy(float),
        'Frozen clock':frozen_clock.predict(a),'Expanded clock':fits['clock'].predict(a),
        'Frozen context':frozen['models']['Context boosting EPV'].predict(context_matrix(a,frozen['levels'])),
        'Expanded context':fits['context'].predict(context_matrix(a,fits['levels'])),
        'Frozen Markov':frozen['models']['Markov EPV'].predict(a),'Expanded Markov':fits['markov'].predict(a)}


def paired(a,model,baseline):
    d=(a[model]-a.remaining_points)**2-(a[baseline]-a.remaining_points)**2
    g=pd.DataFrame({'game':a.game_id,'d':d}).groupby('game').d.agg(['sum','count'])
    rng=np.random.default_rng(20261122);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
    ci=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])
    return {'states':len(a),'games':len(g),'mse_difference':float(d.mean()),'lower':float(ci[0]),'upper':float(ci[1])}


def main():
    started=time.monotonic();rule=json.loads((OUT/'recovery_rule_receipt.json').read_text(encoding='utf-8'))
    original=json.loads((BASE/'possession/model_selection_receipt.json').read_text(encoding='utf-8'))
    assert original['selected_model']=='Context boosting EPV'
    assert all(digest(HERE.parent/path)==value for path,value in rule['original_frozen_input_hashes'].items())
    frozen=joblib.load(OLD/'models.joblib');frozen_clock=ClockMean().fit(pd.read_csv(OLD/'model_states.csv.gz',float_precision='round_trip').query("split=='train'"))
    settings=frozen['models']['Context boosting EPV'].get_params();assert settings['max_depth']==3 and settings['l2_regularization']==100 and settings['max_iter']==300
    plan={'only_data_source':'Data (1).zip','archive_sha256':rule['archive_sha256'],'runtime':'desktop CPU only','features':FEATURES,
        'policies':list(POLICIES),'context_parameters':settings,'markov_alpha':frozen['models']['Markov EPV'].alpha,'clock_prior_strength':50,
        'training_cutoff':'2025-08-09','setting_rule':'Reuse the frozen validation-selected context and Markov settings; use the diagnostic clock rule fixed earlier. No new tuning or winner selection.',
        'evaluation_limit':'Exploratory refits and recovery sensitivity on reused 2025 data. The source eligibility rule was fixed before these fits.',
        'model_names':NAMES,'fits':[]}
    (OUT/'fit_receipt.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    data={};fits={}
    for policy in POLICIES:
        a=pd.read_csv(PRIVATE/f'{policy}_states.csv.gz',dtype={'offense_team_id':str,'defense_team_id':str},float_precision='round_trip')
        train=a[a.split.eq('train')].copy();assert train.date.max()=='2025-08-09' and not set(train.game_id)&set(a.loc[a.split.ne('train'),'game_id'])
        assert a.recovery_eligible.all() and not a.state_id.duplicated().any()
        levels={c:sorted(train[c].unique()) for c in CATEGORICAL}
        context=HistGradientBoostingRegressor(**settings).fit(context_matrix(train,levels),train.remaining_points)
        markov=MarkovValue(plan['markov_alpha']).fit(train);clock=ClockMean(50).fit(train)
        fits[policy]={'context':context,'markov':markov,'clock':clock,'means':train.groupby('stage').remaining_points.mean().to_dict(),'levels':levels}
        data[policy]=a
        plan['fits'].append({'policy':policy,'training_states':len(train),'training_entry_states':int(train.stage.eq('entry').sum()),
            'added_training_states':int(train.cohort.eq('recovered').sum()),'last_training_date':train.date.max(),'markov_states':len(markov.labels),
            'markov_bellman_residual':markov.residual,'markov_spectral_radius':markov.radius,'cpu_threads':4})
        print('RECOVERY_CPU_FIT',policy,len(train),flush=True)
    # All refits are fixed before producing evaluation metrics.
    joblib.dump({'fits':fits,'frozen_clock':frozen_clock},PRIVATE/'models.joblib')
    (OUT/'fit_receipt.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    metrics=[];comparisons=[];calibration=[];saved={}
    for policy,a in data.items():
        a=a[a.split.ne('train')].copy()
        for name,value in predict_all(a,frozen,fits[policy],frozen_clock).items():
            assert np.isfinite(value).all() and (value>=0).all();a[name]=value
        saved[policy]=a
        a[['state_id','episode_id','source_row','game_id','split','stage','cohort','remaining_points']+NAMES].to_csv(PRIVATE/f'{policy}_predictions.csv.gz',index=False)
        for split in ['validation','test','playoffs']:
            for cohort in ['all','original','recovered']:
                q=a[a.split.eq(split)];q=q if cohort=='all' else q[q.cohort.eq(cohort)]
                for stage in ['all_states','entry','after_miss','after_offensive_rebound']:
                    b=q if stage=='all_states' else q[q.stage.eq(stage)]
                    if b.empty:continue
                    for model in NAMES:
                        d=b[model]-b.remaining_points
                        metrics.append({'policy':policy,'split':split,'cohort':cohort,'stage':stage,'model':model,'states':len(b),'episodes':b.episode_id.nunique(),
                            'games':b.game_id.nunique(),'rmse':float(np.sqrt(np.mean(d**2))),'mae':float(np.mean(abs(d))),
                            'mean_prediction':float(b[model].mean()),'mean_observed':float(b.remaining_points.mean())})
                    if split!='validation' and stage!='all_states':
                        pairs=[(name,'Frozen clock') for name in NAMES]+[('Expanded context','Frozen context'),('Expanded Markov','Frozen Markov'),('Expanded clock','Frozen clock')]
                        for model,baseline in dict.fromkeys(pairs):
                            comparisons.append({'policy':policy,'split':split,'cohort':cohort,'stage':stage,'model':model,'baseline':baseline,**paired(b,model,baseline)})
                if cohort=='all':
                    for stage,b in q.groupby('stage'):
                        for model in ['Frozen context','Expanded context','Expanded clock']:
                            bins=pd.cut(b[model],[-np.inf,.25,.5,.75,1.,1.25,1.5,1.75,2.,2.25,2.5,2.75,3.,np.inf])
                            for label,g in b.assign(bin=bins).groupby('bin',observed=True):
                                calibration.append({'policy':policy,'split':split,'stage':stage,'model':model,'prediction_bin':str(label),'states':len(g),
                                    'mean_prediction':float(g[model].mean()),'mean_observed':float(g.remaining_points.mean())})
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(comparisons).to_csv(OUT/'game_bootstrap.csv',index=False)
    pd.DataFrame(calibration).to_csv(OUT/'calibration.csv',index=False)
    sensitivity=[]
    first=saved['first_rebound'].set_index('state_id');second=saved['second_rebound'].set_index('state_id')
    common=first.loc[second.index].copy();assert np.array_equal(common.remaining_points,second.remaining_points)
    for split in ['test','playoffs']:
        for stage in ['entry','after_miss','after_offensive_rebound']:
            for cohort in ['all','original']:
                b=common[common.split.eq(split)&common.stage.eq(stage)];b=b if cohort=='all' else b[b.cohort.eq('original')]
                for model in ['Expanded context','Expanded Markov','Expanded clock']:
                    b=b.copy();b['stricter']=second.loc[b.index,model].to_numpy()
                    sensitivity.append({'split':split,'stage':stage,'cohort':cohort,'model':model,'comparison':'first-restart fit minus second-restart fit on identical shared states',**paired(b,model,'stricter')})
    pd.DataFrame(sensitivity).to_csv(OUT/'policy_sensitivity.csv',index=False)
    # Frozen model inference must reproduce the old saved predictions exactly.
    old=pd.read_csv(OLD/'predictions.csv.gz',float_precision='round_trip').set_index('state_id')
    for policy,a in saved.items():
        b=a[a.cohort.eq('original')].set_index('state_id').loc[old.index]
        for name,original_name in [('Frozen context','Context boosting EPV'),('Frozen Markov','Markov EPV'),('Frozen average','Stage mean')]:assert np.allclose(b[name],old[original_name],atol=1e-12,rtol=1e-12)
    assert all(digest(HERE.parent/path)==value for path,value in rule['original_frozen_input_hashes'].items())
    plan['original_model_predictions_reproduced']=True;plan['original_artifacts_unchanged']=True;plan['elapsed_seconds']=time.monotonic()-started
    plan['completed_utc']=pd.Timestamp.now(tz='UTC').isoformat();(OUT/'fit_receipt.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    print('RECOVERY_MODELS_COMPLETE',round(plan['elapsed_seconds'],2),flush=True)
    print(pd.DataFrame(metrics).query("policy=='first_rebound' and split=='test' and cohort=='all' and stage=='entry'").to_string(index=False),flush=True)


if __name__=='__main__':
    from recovery_models import main as run
    run()
