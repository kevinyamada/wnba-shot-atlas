"""Desktop CPU expected remaining points on audited, recorded event states."""
from __future__ import annotations
import os
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[name]='4'
from pathlib import Path
from collections import Counter,defaultdict
import hashlib
import json
import platform
import time
import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import SplineTransformer,StandardScaler,OneHotEncoder
from sklearn.linear_model import PoissonRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
import sklearn
from possession_reconstruction import FEATURES

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1/possession'
PRIVATE=HERE/'data/data1/possession'
CATEGORICAL=['stage','start_reason','offense_team_id','defense_team_id']
NUMERIC=[c for c in FEATURES if c not in CATEGORICAL]
EDGES=np.array([2,5,24,60,120,300,601])


def score(y,p):
    p=np.asarray(p,float);y=np.asarray(y,float)
    assert np.isfinite(p).all() and (p>=0).all()
    return {'states':len(y),'rmse':float(np.sqrt(np.mean((p-y)**2))),'mae':float(np.mean(abs(p-y))),
            'mean_prediction':float(p.mean()),'mean_observed':float(y.mean())}


def keys(s):
    bins=np.digitize(s.seconds_remaining,EDGES)-1
    return [f'{r.stage}|{r.start_reason if r.stage=="entry" else "any"}|{int(b)}|{int(r.home)}' for r,b in zip(s.itertuples(),bins)]


class StateMean:
    def __init__(self,alpha):self.alpha=alpha
    def fit(self,s):
        self.fallback=s.groupby('stage').remaining_points.mean().to_dict()
        a=s.assign(key=keys(s)).groupby(['key','stage']).remaining_points.agg(['sum','count']).reset_index()
        self.values={r.key:(r.sum+self.alpha*self.fallback[r.stage])/(r.count+self.alpha) for r in a.itertuples()}
        return self
    def predict(self,s):return np.array([self.values.get(k,self.fallback[stage]) for k,stage in zip(keys(s),s.stage)])


class MarkovValue:
    def __init__(self,alpha):self.alpha=alpha
    def fit(self,s):
        self.fallback=s.groupby('stage').remaining_points.mean().to_dict()
        self.labels=sorted(set(keys(s)));self.index={k:i for i,k in enumerate(self.labels)}
        n=len(self.labels);counts=np.zeros(n);rewards=np.zeros(n);transitions=np.zeros((n,n));absorbed=np.zeros(n)
        for _,a in s.assign(key=keys(s)).groupby('episode_id',sort=False):
            rows=list(a.itertuples())
            for position,r in enumerate(rows):
                i=self.index[r.key];counts[i]+=1
                if position+1<len(rows):
                    q=rows[position+1];reward=q.points_so_far-r.points_so_far
                    assert reward>=0 and q.seconds_remaining<=r.seconds_remaining
                    transitions[i,self.index[q.key]]+=1
                else:reward=r.remaining_points;absorbed[i]+=1
                rewards[i]+=reward
        # Positive absorbing pseudocounts regularize sparse states and make the
        # finite chain proper. Their rewards shrink to a training stage mean.
        prior=np.array([self.fallback[k.split('|')[0]] for k in self.labels])
        self.P=transitions/(counts[:,None]+self.alpha)
        self.r=(rewards+self.alpha*prior)/(counts+self.alpha)
        self.V=np.linalg.solve(np.eye(n)-self.P,self.r)
        self.residual=float(abs(self.V-self.r-self.P@self.V).max())
        self.radius=float(max(abs(np.linalg.eigvals(self.P))))
        assert self.residual<1e-10 and self.radius<1 and np.isfinite(self.V).all() and (self.V>=0).all()
        self.counts=counts;self.reward_sums=rewards;self.absorbed=absorbed
        return self
    def predict(self,s):return np.array([self.V[self.index[k]] if k in self.index else self.fallback[stage] for k,stage in zip(keys(s),s.stage)])


def main():
    started=time.monotonic();OUT.mkdir(parents=True,exist_ok=True)
    source=json.loads((OUT/'reconstruction_audit.json').read_text(encoding='utf-8'))
    assert source['only_data_source']=='Data (1).zip' and source['all_624_team_scores_reconcile']
    s=pd.read_csv(PRIVATE/'model_states.csv.gz',dtype={'offense_team_id':str,'defense_team_id':str},float_precision='round_trip')
    assert not s.state_id.duplicated().any() and s.eligible.all() and s.seconds_remaining.gt(2).all()
    train=s[s.split.eq('train')].copy();validation=s[s.split.eq('validation')].copy()
    mask=validation.stage.eq('entry');assert len(train)>10000 and mask.sum()>1000
    assert train.date.max()<validation.date.min()
    for split in ['validation','test','playoffs']:assert not set(train.game_id)&set(s.loc[s.split.eq(split),'game_id'])
    means=train.groupby('stage').remaining_points.mean().to_dict()
    candidates=[];models={}
    def loss(p):return float(np.mean((validation.loc[mask,'remaining_points'].to_numpy()-np.asarray(p)[mask.to_numpy()])**2))
    best=None
    for alpha in [10.,50.,200.]:
        m=StateMean(alpha).fit(train);value=loss(m.predict(validation));candidates.append({'model':'Shrunk state mean','setting':f'alpha={alpha}','validation_entry_mse':value})
        if best is None or value<best[0]:best=(value,m)
    models['Shrunk state mean']=best[1]
    best=None
    for alpha in [1.,10.,50.]:
        m=MarkovValue(alpha).fit(train);value=loss(m.predict(validation));candidates.append({'model':'Markov EPV','setting':f'alpha={alpha}','validation_entry_mse':value})
        if best is None or value<best[0]:best=(value,m)
    models['Markov EPV']=best[1]
    spline=SplineTransformer(n_knots=4,degree=3,include_bias=False).fit(train[['seconds_remaining','elapsed_seconds']])
    rest=[c for c in NUMERIC if c not in ['seconds_remaining','elapsed_seconds']]
    scaler=StandardScaler().fit(train[rest]);encoder=OneHotEncoder(handle_unknown='ignore',sparse_output=False).fit(train[CATEGORICAL])
    def design(a):return np.column_stack([spline.transform(a[['seconds_remaining','elapsed_seconds']]),scaler.transform(a[rest]),encoder.transform(a[CATEGORICAL])])
    xt,xv=design(train),design(validation);best=None
    for alpha in [.1,1.]:
        m=PoissonRegressor(alpha=alpha,max_iter=1500).fit(xt,train.remaining_points)
        value=loss(m.predict(xv));candidates.append({'model':'Poisson spline','setting':f'alpha={alpha}','validation_entry_mse':value})
        if best is None or value<best[0]:best=(value,m)
    models['Poisson spline']=best[1]
    levels={c:sorted(train[c].unique()) for c in CATEGORICAL}
    def histogram(a):
        x=a[FEATURES].copy()
        for c in CATEGORICAL:x[c]=pd.Categorical(x[c].where(x[c].isin(levels[c])),categories=levels[c])
        return x
    hx,hv=histogram(train),histogram(validation);best=None
    for depth in [3,5]:
        for penalty in [20.,100.]:
            m=HistGradientBoostingRegressor(loss='poisson',learning_rate=.04,max_iter=300,max_leaf_nodes=15,max_depth=depth,
                    min_samples_leaf=100,l2_regularization=penalty,max_bins=63,early_stopping=False,random_state=20261122,categorical_features='from_dtype').fit(hx,train.remaining_points)
            value=loss(m.predict(hv));candidates.append({'model':'Context boosting EPV','setting':f'depth={depth};penalty={penalty}','validation_entry_mse':value})
            if best is None or value<best[0]:best=(value,m)
            print('EPV_CPU_CANDIDATE',depth,penalty,value,flush=True)
    models['Context boosting EPV']=best[1]
    pd.DataFrame(candidates).to_csv(OUT/'validation_selection.csv',index=False)
    def predict(name,a):
        if name=='Stage mean':return a.stage.map(means).to_numpy(float)
        if name=='Poisson spline':return models[name].predict(design(a))
        if name=='Context boosting EPV':return models[name].predict(histogram(a))
        return models[name].predict(a)
    names=['Stage mean']+list(models)
    selected=min(names,key=lambda n:loss(predict(n,validation)))
    selection={'only_data_source':'Data (1).zip','archive_sha256':source['archive_sha256'],'selected_model':selected,
               'selection_rule':'Minimum mean squared error on August 10-26 episode-entry states; no later-game result selects settings.',
               'training_last_date':train.date.max(),'validation_first_date':validation.date.min(),'validation_last_date':validation.date.max(),
               'features':FEATURES,'fitted_stages':['entry','after_miss','after_offensive_rebound'],
               'current_event_outcome_rule':'A miss or rebound is already observed at a post-event state; the target is points scored later in that same episode.',
               'eligibility_limit':'Retrospectively source-qualified subset; not a live guarantee of episode completeness or official possession IDs.',
               'evaluation_limit':'Reused 2025 chronological benchmarks; source-limited prototype, not full spatial xT.',
               'training_states':len(train),'training_entry_states':int(train.stage.eq('entry').sum()),'runtime':'desktop CPU only',
               'state_table_sha256':hashlib.sha256((PRIVATE/'model_states.csv.gz').read_bytes()).hexdigest(),
               'versions':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'scikit_learn':sklearn.__version__},
               'selected_settings':{name:next((r['setting'] for r in sorted(candidates,key=lambda r:r['validation_entry_mse']) if r['model']==name),'training stage mean') for name in names}}
    # Freeze the choice before producing later game and playoff scores.
    (OUT/'model_selection_receipt.json').write_text(json.dumps(selection,indent=2),encoding='utf-8')
    saved=[];metrics=[];calibration=[];boot=[]
    for split,a in s[s.split.ne('train')].groupby('split'):
        q=a.copy()
        for name in names:
            q[name]=predict(name,a)
            assert np.isfinite(q[name]).all() and q[name].ge(0).all()
            for stage in ['all_states','entry','after_miss','after_offensive_rebound']:
                b=q if stage=='all_states' else q[q.stage.eq(stage)]
                metrics.append({'split':split,'stage':stage,'model':name,'episodes':int(b.episode_id.nunique()),'games':int(b.game_id.nunique()),**score(b.remaining_points,b[name])})
            for stage,b in q.groupby('stage'):
                for key,g in b.assign(bin=pd.cut(b[name],np.r_[-np.inf,np.arange(.25,3.01,.25),np.inf],include_lowest=True)).groupby('bin',observed=True):
                    calibration.append({'split':split,'stage':stage,'model':name,'prediction_bin':str(key),'states':len(g),'mean_prediction':float(g[name].mean()),'observed_remaining_points':float(g.remaining_points.mean())})
        if split!='validation':
            for stage in ['entry','after_miss','after_offensive_rebound']:
                b=q[q.stage.eq(stage)];games=sorted(b.game_id.unique());rng=np.random.default_rng(20261122)
                weights=rng.multinomial(len(games),np.full(len(games),1/len(games)),size=2000)
                for name in names:
                    error=(b[name]-b.remaining_points)**2-(b['Stage mean']-b.remaining_points)**2
                    group=pd.DataFrame({'game':b.game_id,'error':error}).groupby('game').error.agg(['sum','count']).reindex(games)
                    draws=(weights@group['sum'].to_numpy())/(weights@group['count'].to_numpy())
                    boot.append({'split':split,'stage':stage,'model':name,'baseline':'Stage mean','states':len(b),'games':len(games),
                                 'mse_difference':float(error.mean()),'lower':float(np.quantile(draws,.025)),'upper':float(np.quantile(draws,.975))})
        saved.append(q[['state_id','episode_id','source_row','game_id','split','stage','remaining_points']+names])
    predictions=pd.concat(saved,ignore_index=True);predictions.to_csv(PRIVATE/'predictions.csv.gz',index=False)
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(calibration).to_csv(OUT/'calibration.csv',index=False);pd.DataFrame(boot).to_csv(OUT/'game_bootstrap.csv',index=False)
    markov=models['Markov EPV']
    value_rows=[];edges=[]
    for i,key in enumerate(markov.labels):
        stage,reason,clock,home=key.split('|');value_rows.append({'state_key':key,'stage':stage,'start_reason':reason,'clock_bin':int(clock),'home':int(home),
                    'training_visits':int(markov.counts[i]),'markov_value':float(markov.V[i]),'immediate_reward_mean_regularized':float(markov.r[i]),'absorption_probability':float(1-markov.P[i].sum())})
        for j,p in enumerate(markov.P[i]):
            if p>0:edges.append({'state_from':key,'state_to':markov.labels[j],'probability':float(p)})
    pd.DataFrame(value_rows).to_csv(OUT/'markov_values.csv',index=False);pd.DataFrame(edges).to_csv(OUT/'markov_transitions.csv',index=False)
    proof={'bellman_residual_max':markov.residual,'transition_spectral_radius':markov.radius,'alpha':markov.alpha,
           'states':len(markov.labels),'absorbing_rows_positive':bool((markov.P.sum(axis=1)<1).all()),'finite_nonnegative_values':bool(np.isfinite(markov.V).all() and (markov.V>=0).all()),
           'interpretation':'Regularized empirical event-state reward/transition model, not a learned spatial movement policy.'}
    (OUT/'markov_diagnostics.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    # Summaries show actual benchmark states, not invented counterfactual locations.
    display=[]
    for split,a in s[s.split.ne('train')].groupby('split'):
        a=a.copy();a['prediction']=predict(selected,a);a['clock_bin']=np.digitize(a.seconds_remaining,EDGES)-1
        for (stage,clock),b in a.groupby(['stage','clock_bin']):display.append({'split':split,'stage':stage,'clock_bin':int(clock),'states':len(b),
                'mean_predicted':float(b.prediction.mean()),'mean_observed':float(b.remaining_points.mean())})
    pd.DataFrame(display).to_csv(OUT/'value_summary.csv',index=False)
    joblib.dump({'models':models,'stage_means':means,'spline':spline,'scaler':scaler,'encoder':encoder,'levels':levels,'rest':rest},PRIVATE/'models.joblib')
    selection['elapsed_seconds']=time.monotonic()-started
    (OUT/'model_selection_receipt.json').write_text(json.dumps(selection,indent=2),encoding='utf-8')
    print('EPV_MODELS_COMPLETE',selected,'seconds',round(selection['elapsed_seconds'],2),flush=True)
    print(pd.DataFrame(metrics).query("split=='test' and stage=='entry'").sort_values('rmse').to_string(index=False),flush=True)


if __name__=='__main__':
    # Keep saved class names importable when this file is invoked directly.
    from possession_models import main as run
    run()
