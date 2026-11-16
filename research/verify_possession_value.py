"""Independently check rewards, causality, Markov values and EPV outputs on CPU."""
from pathlib import Path
from collections import defaultdict
import argparse,csv,hashlib,io,json,subprocess,sys,urllib.request,zipfile
import joblib
import numpy as np
import pandas as pd
from possession_reconstruction import Reconstructor,FEATURES
from possession_models import CATEGORICAL,EDGES

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1/possession';PRIVATE=HERE/'data/data1/possession'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--final',action='store_true');args=ap.parse_args()
    checks=[]
    def check(name,ok=True):
        assert ok,name
        checks.append(name);print('CHECK',name,flush=True)
    def read(name):return pd.read_csv(PRIVATE/name,float_precision='round_trip')
    audit=json.loads((OUT/'reconstruction_audit.json').read_text(encoding='utf-8'))
    receipt=json.loads((OUT/'model_selection_receipt.json').read_text(encoding='utf-8'))
    digest=hashlib.file_digest(args.source.open('rb'),'sha256').hexdigest()
    check('Original ZIP hash agrees across reconstruction and model receipts',digest==audit['archive_sha256']==receipt['archive_sha256'])
    with zipfile.ZipFile(args.source) as z:
        def raw(suffix):return list(csv.DictReader(io.TextIOWrapper(z.open(next(n for n in z.namelist() if n.endswith(suffix))),encoding='utf-8-sig',newline='')))
        events=raw('/original/wehoop_wnba_pbp.csv');teams=raw('/WNBA_Team/wnba_team_box.csv')
    ledger=read('event_ledger.csv.gz');episodes=read('all_episodes.csv.gz');states=read('model_states.csv.gz')
    full=read('all_states.csv.gz');pred=read('predictions.csv.gz')
    ledger['position']=np.arange(len(ledger));positions=ledger.set_index('source_row').position.to_dict()
    check('One ledger record exists for each original event',len(events)==len(ledger)==121342 and not ledger.source_row.duplicated().any() and set(ledger.source_row)==set(range(2,len(events)+2)))
    totals=defaultdict(int);positive=set()
    for r in ledger.itertuples():
        q=events[int(r.source_row)-2];team=None if q['team_id'].strip().lower() in ['','na','nan','null'] else int(float(q['team_id']))
        assert int(q['game_id'])==r.game_id and int(q['type_id'])==r.type_id and int(float(q['score_value']))==r.points
        assert team is None and pd.isna(r.team_id) or team==r.team_id
        if r.points:
            totals[r.game_id,team]+=r.points;positive.add(r.source_row)
            assert r.reward_lane in ['ordinary','special_free_throw']
    boxes={(int(q['game_id']),int(q['team_id'])):int(float(q['team_score'])) for q in teams if int(q['season'])==2025}
    check('Fresh CSV parsing reconciles all 624 final team scores including free throws',len(boxes)==624 and all(totals[k]==v for k,v in boxes.items()))
    check('Every positive scoring event is credited exactly once',len(positive)==ledger.points.gt(0).sum() and ledger.loc[ledger.points.gt(0)&ledger.reward_lane.eq('ordinary'),'episode_id'].notna().all())
    ordinary=ledger[ledger.reward_lane.eq('ordinary')];sums=ordinary.groupby('episode_id').points.sum()
    check('All episode rewards plus separately audited special points conserve every score',np.array_equal(episodes.points,sums.reindex(episodes.episode_id).fillna(0)) and int(episodes.points.sum())==50774 and int(ledger.loc[ledger.reward_lane.eq('special_free_throw'),'points'].sum())==299 and ledger.points.sum()==51073)
    check('Retained states are exactly the strict eligible source states',set(states.state_id)==set(full.loc[full.eligible,'state_id']) and len(states)==40617 and states.stage.eq('entry').sum()==25306 and states.seconds_remaining.gt(2).all() and states.quality_flags.isna().all())
    ep=episodes.set_index('episode_id');quality=pd.read_csv(OUT/'period_quality.csv').set_index(['game_id','period_number'])
    check('All retained episodes have anchored starts and clean periods',ep.loc[states.episode_id].eligible.all() and ep.loc[states.episode_id].start_anchored.all() and all(pd.isna(quality.loc[(r.game_id,r.period_number),'flags']) for r in states.itertuples()))
    groups={k:g for k,g in ledger[ledger.episode_id.notna()].groupby('episode_id',sort=False)}
    for r in states.itertuples():
        a=groups.get(r.episode_id,ledger.iloc[:0]);position=positions[r.source_row]
        after=a[a.position.gt(position)&a.reward_lane.eq('ordinary')]
        before=a[a.position.le(position)&a.reward_lane.eq('ordinary')]
        assert r.remaining_points==after.points.sum() and r.points_so_far==before.points.sum()
        assert r.episode_points==ep.loc[r.episode_id,'points'] and r.remaining_points+r.points_so_far==r.episode_points
        q=events[int(r.source_row)-2];margin=int(q['home_score'])-int(q['away_score'])
        assert r.score_margin==(margin if r.home else -margin)
    check('Every target is the independently summed future ordinary reward; all margins match source snapshots')
    empty=episodes[episodes.eligible&~episodes.episode_id.isin(ledger.episode_id)]
    check('Unobserved-between-boundary intervals explicitly have zero recorded reward',len(empty)==16 and empty.points.eq(0).all() and empty.end_reason.eq('jump_ball').all())
    check('Feature allowlist excludes future rewards, actor IDs, text and invented movement coordinates',receipt['features']==FEATURES and not set(FEATURES)&{'remaining_points','episode_points','end_seconds','end_reason','eligible','quality_flags','source_row','game_id','athlete_id_1','text','coordinate_x','coordinate_y'})
    # Reconstruct truncated actual games; compare observed features before joining
    # the final reward and quality labels. Quality itself is retrospective.
    ids=sorted(states.game_id.unique())[::max(1,states.game_id.nunique()//8)][:8]
    with zipfile.ZipFile(args.source) as z:
        name=next(n for n in z.namelist() if n.endswith('/original/wehoop_wnba_pbp.csv'));rawframe=pd.read_csv(z.open(name),low_memory=False)
    rawframe['source_row']=np.arange(len(rawframe))+2
    roles=pd.read_csv(OUT/'jump_ball_role_audit.csv');rawframe['jump_winner_validated']=rawframe.source_row.map(roles.set_index('source_row').validated).fillna(False).astype(bool)
    comparisons=0
    for gid in ids:
        game=rawframe[rawframe.game_id.eq(gid)].sort_values('game_play_number',kind='stable')
        b=Reconstructor();b.game(game)
        key=lambda s:(s['source_row'],s['stage'],s['offense_team_id'],s['period_number'])
        reference={key(s):s for s in b.states}
        for fraction in [.25,.5,.75]:
            b=Reconstructor();b.game(game.iloc[:max(1,int(len(game)*fraction))])
            for s in b.states:
                if key(s) in reference:
                    assert [s[c] for c in FEATURES]==[reference[key(s)][c] for c in FEATURES]
                    comparisons+=1
    check('Actual-game prefix reconstructions preserve all shared feature values',comparisons>1000)
    subprocess.run([sys.executable,str(HERE/'test_possession_reconstruction.py')],check=True)
    check('Eight synthetic boundary, free-throw, rebound and prefix scenarios pass')
    expected={'train':('2025-05-01','2025-08-09'),'validation':('2025-08-10','2025-08-26'),'test':('2025-08-27','2025-09-11'),'playoffs':('2025-09-14','2025-10-10')}
    for split,(lo,hi) in expected.items():
        a=states[states.split.eq(split)];assert a.date.between(lo,hi).all()
        assert not set(a.game_id)&set(states.loc[states.split.ne(split),'game_id'])
    check('Games are disjoint and every state respects chronological cutoffs')
    joined=pred.merge(states[['state_id','episode_id','source_row','game_id','split','stage','remaining_points']],on='state_id',suffixes=('','_source'),validate='one_to_one')
    for c in ['episode_id','source_row','game_id','split','stage','remaining_points']:assert joined[c].eq(joined[c+'_source']).all()
    check('All saved predictions have unique source-verified state keys and targets',len(pred)==len(states[states.split.ne('train')]) and not pred.state_id.duplicated().any())
    names=list(pred.columns[7:]);metrics=pd.read_csv(OUT/'metrics.csv')
    for r in metrics.itertuples():
        a=pred[pred.split.eq(r.split)];a=a if r.stage=='all_states' else a[a.stage.eq(r.stage)]
        y=a.remaining_points.to_numpy();p=a[r.model].to_numpy()
        assert np.isfinite(p).all() and (p>=0).all()
        assert (len(a),a.game_id.nunique(),a.episode_id.nunique())==(r.states,r.games,r.episodes)
        assert np.allclose([np.sqrt(np.mean((p-y)**2)),np.mean(abs(p-y)),p.mean(),y.mean()],[r.rmse,r.mae,r.mean_prediction,r.mean_observed],atol=1e-12)
    check('Every reported RMSE, MAE, mean and cohort count recomputes independently')
    candidates=pd.read_csv(OUT/'validation_selection.csv');v=metrics[metrics.split.eq('validation')&metrics.stage.eq('entry')]
    for model,a in candidates.groupby('model'):
        best=a.sort_values('validation_entry_mse').iloc[0];assert np.isclose(best.validation_entry_mse,v[v.model.eq(model)].iloc[0].rmse**2)
        assert best.setting==receipt['selected_settings'][model]
    check('Model family and all settings follow validation entry MSE',v.sort_values('rmse').iloc[0].model==receipt['selected_model'] and receipt['training_last_date']=='2025-08-09' and receipt['state_table_sha256']==hashlib.file_digest((PRIVATE/'model_states.csv.gz').open('rb'),'sha256').hexdigest())
    for r in pd.read_csv(OUT/'game_bootstrap.csv').itertuples():
        a=pred[pred.split.eq(r.split)&pred.stage.eq(r.stage)];d=(a[r.model]-a.remaining_points)**2-(a['Stage mean']-a.remaining_points)**2
        g=pd.DataFrame({'game':a.game_id,'d':d}).groupby('game').d.agg(['sum','count'])
        rng=np.random.default_rng(20261122);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
        interval=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])
        assert np.isclose(d.mean(),r.mse_difference) and np.allclose(interval,[r.lower,r.upper],atol=1e-12)
    check('Every paired whole-game bootstrap interval independently recomputes')
    calibration=pd.read_csv(OUT/'calibration.csv')
    for (split,stage,model),a in calibration.groupby(['split','stage','model']):
        b=pred[pred.split.eq(split)&pred.stage.eq(stage)]
        assert a.states.sum()==len(b)
        assert np.isclose(np.average(a.mean_prediction,weights=a.states),b[model].mean())
        assert np.isclose(np.average(a.observed_remaining_points,weights=a.states),b.remaining_points.mean())
    check('Calibration bins cover every evaluation state and preserve weighted means')
    fitted=joblib.load(PRIVATE/'models.joblib');train=states[states.split.eq('train')].copy();m=fitted['models']['Markov EPV']
    # Build transition counts independently with adjacent arrays, not the fit loop.
    key=lambda r:f'{r.stage}|{r.start_reason if r.stage=="entry" else "any"}|{int(np.searchsorted(EDGES,r.seconds_remaining,side="right")-1)}|{int(r.home)}'
    labels=sorted({key(r) for r in train.itertuples()});idx={k:i for i,k in enumerate(labels)};n=len(labels)
    visits=np.zeros(n);reward=np.zeros(n);transition=np.zeros((n,n))
    for _,a in train.groupby('episode_id',sort=False):
        rows=list(a.itertuples());ix=np.array([idx[key(r)] for r in rows]);points=a.points_so_far.to_numpy()
        np.add.at(visits,ix,1);np.add.at(reward,ix,np.r_[np.diff(points),rows[-1].remaining_points])
        if len(ix)>1:np.add.at(transition,(ix[:-1],ix[1:]),1)
    prior=train.groupby('stage').remaining_points.mean().to_dict();alpha=m.alpha
    P=transition/(visits[:,None]+alpha);r=(reward+alpha*np.array([prior[k.split('|')[0]] for k in labels]))/(visits+alpha)
    value=np.zeros(n)
    for _ in range(1000):
        next_value=r+P@value
        if max(abs(next_value-value))<1e-13:break
        value=next_value
    check('Independent transition counts and value iteration reproduce the saved Markov solution',labels==m.labels and np.allclose(P,m.P,atol=1e-14) and np.allclose(r,m.r,atol=1e-14) and np.allclose(next_value,m.V,atol=1e-12) and (P.sum(axis=1)<1).all())
    table=pd.read_csv(OUT/'markov_values.csv');edges=pd.read_csv(OUT/'markov_transitions.csv')
    public=np.zeros_like(P)
    for q in edges.itertuples():public[idx[q.state_from],idx[q.state_to]]=q.probability
    check('Public Markov values, rewards, absorption and transitions match the verified model',table.state_key.tolist()==labels and np.allclose(table.markov_value,m.V) and np.allclose(table.absorption_probability,1-P.sum(axis=1)) and np.allclose(table.immediate_reward_mean_regularized,r) and np.allclose(public,P))
    sample=states[states.split.ne('train')].iloc[::31].copy();sample[CATEGORICAL]=sample[CATEGORICAL].astype(str)
    for name in names:
        if name=='Stage mean':p=sample.stage.map(fitted['stage_means']).to_numpy()
        elif name=='Poisson spline':
            x=np.column_stack([fitted['spline'].transform(sample[['seconds_remaining','elapsed_seconds']]),fitted['scaler'].transform(sample[fitted['rest']]),fitted['encoder'].transform(sample[CATEGORICAL])]);p=fitted['models'][name].predict(x)
        elif name=='Context boosting EPV':
            x=sample[FEATURES].copy()
            for c in CATEGORICAL:x[c]=pd.Categorical(x[c].where(x[c].isin(fitted['levels'][c])),categories=fitted['levels'][c])
            p=fitted['models'][name].predict(x)
        else:p=fitted['models'][name].predict(sample)
        assert np.allclose(p,pred.set_index('state_id').loc[sample.state_id,name],atol=1e-12)
    check('Saved desktop model weights reproduce predictions across the evaluation cohorts')
    summary=pd.read_csv(OUT/'value_summary.csv')
    for q in summary.itertuples():
        a=pred[pred.split.eq(q.split)&pred.stage.eq(q.stage)].merge(states[['state_id','seconds_remaining']],on='state_id')
        a=a[(np.digitize(a.seconds_remaining,EDGES)-1)==q.clock_bin]
        assert len(a)==q.states and np.isclose(a[receipt['selected_model']].mean(),q.mean_predicted) and np.isclose(a.remaining_points.mean(),q.mean_observed)
    check('All displayed clock-bin values are aggregates of actual verified states')
    site=json.loads((HERE.parent/'assets/data.json').read_text(encoding='utf-8'))['possessionValue']
    check('Website EPV data matches every checked aggregate and receipt',site['audit']==audit and site['selection']==receipt and site['metrics']==metrics.to_dict('records') and site['bootstrap']==pd.read_csv(OUT/'game_bootstrap.csv').to_dict('records') and site['summary']==summary.to_dict('records') and site['calibration']==calibration.to_dict('records') and site['markov']==json.loads((OUT/'markov_diagnostics.json').read_text()))
    if args.final:
        for f in ['final_verification.json','followup/final_followup_verification.json']:
            record=json.loads((HERE/'results/data1'/f).read_text(encoding='utf-8'));assert record['all_checks_pass'] and record['archive_sha256']==digest
        check('Primary and desktop follow-up final source checks have passed')
        live=urllib.request.urlopen('https://kevinyamada.github.io/wnba-shot-atlas/assets/data.json?epv-final=1',timeout=45).read()
        check('Live GitHub Pages data is byte-identical to the checked publication',live==(HERE.parent/'assets/data.json').read_bytes())
        browser=json.loads((HERE/'results/data1/live_site_checks.json').read_text(encoding='utf-8'))
        check('Final live browser checks include every possession control and table',browser['all_pass'] and 'Possession EPV controls and tables' in browser['checks'])
    result={'all_checks_pass':True,'checks':checks,'archive_sha256':digest,'only_data_source':'Data (1).zip','compute':'desktop CPU only','actual_game_prefix_feature_comparisons':comparisons,
        'analysis_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip(),
        'completed_utc':pd.Timestamp.now(tz='UTC').isoformat(),'stage':'final after publication' if args.final else 'development'}
    (OUT/('final_possession_verification.json' if args.final else 'development_verification.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('POSSESSION_VERIFICATION_ALL_PASS',len(checks),flush=True)


if __name__=='__main__':main()
