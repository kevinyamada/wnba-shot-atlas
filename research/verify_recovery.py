"""Independent raw source, restart, target, model and publication verification."""
import os
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[name]='4'
from pathlib import Path
from collections import defaultdict,Counter
import argparse,csv,hashlib,io,json,re,subprocess,sys,time,urllib.request,zipfile
import joblib
import numpy as np
import pandas as pd
from possession_reconstruction import FEATURES
from recovery_models import ClockMean

HERE=Path(__file__).resolve().parent;BASE=HERE/'results/data1';OUT=BASE/'recovery';PRIVATE=HERE/'data/data1/recovery';OLD=HERE/'data/data1/possession'
FT={97:(1,1),98:(1,2),99:(2,2),100:(1,3),101:(2,3),102:(3,3)}
SPECIAL={103,104,105,106,107,108,157,165,166};FOUL={22,25,28,29,30,31,32,35,36,37,40,47,257}
HAZARD=SPECIAL|FOUL|{215,279};TO=set(range(62,73))|{74,75,76,78,84,86,87,88,89,90};SOFT={'special_free_throw_or_foul','overturned_review'}


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def number(x):return int(float(x))
def clock_seconds(x):a,b=x.split(':');return 60*float(a)+float(b)
def flags(x):return set(str(x).split('|')) if pd.notna(x) and x else set()


def interval(a,model,baseline):
    d=(a[model]-a.remaining_points)**2-(a[baseline]-a.remaining_points)**2
    g=pd.DataFrame({'game':a.game_id,'d':d}).groupby('game').d.agg(['sum','count']);rng=np.random.default_rng(20261122)
    w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
    return d.mean(),np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--live',action='store_true');args=ap.parse_args();checks=[]
    def check(name,ok=True):
        assert ok,name
        checks.append(name);print('CHECK',name,flush=True)
    rule=json.loads((OUT/'recovery_rule_receipt.json').read_text(encoding='utf-8'));fit=json.loads((OUT/'fit_receipt.json').read_text(encoding='utf-8'))
    check('Original Data1 ZIP digest and all frozen predecessor artifacts are unchanged',args.source.name=='Data (1).zip' and digest(args.source)==rule['archive_sha256']==fit['archive_sha256'] and all(digest(HERE.parent/p)==h for p,h in rule['original_frozen_input_hashes'].items()))
    with zipfile.ZipFile(args.source) as z:
        def read(suffix):return list(csv.DictReader(io.TextIOWrapper(z.open(next(n for n in z.namelist() if n.endswith(suffix))),encoding='utf-8-sig',newline='')))
        raw=read('/original/wehoop_wnba_pbp.csv');players=read('/WNBA_player/wnba_player_box.csv');teams=read('/WNBA_Team/wnba_team_box.csv')
    roster={};names=defaultdict(set)
    for r in players:
        if number(r['season'])==2025:
            roster[number(r['game_id']),number(r['athlete_id'])]=number(r['team_id']);names[number(r['game_id']),r['athlete_display_name']].add(number(r['team_id']))
    games=defaultdict(list);period_rows=defaultdict(list);team_points=Counter();quality={}
    for source_row,r in enumerate(raw,2):
        r['_row']=source_row;r['_gid']=number(r['game_id']);r['_period']=number(r['period_number']);r['_play']=number(r['game_play_number']);r['_type']=number(r['type_id'])
        r['_team']=None if r['team_id'].strip().lower() in ['','na','nan','null'] else number(r['team_id']);r['_points']=number(r['score_value']);r['_seconds']=clock_seconds(r['clock_display_value'])
        r['_fga']=r['shooting_play'].lower()=='true' and 'free throw' not in r['type_text'].lower()
        games[r['_gid']].append(r)
    for gid,g in games.items():
        g.sort(key=lambda r:r['_play']);home=number(g[0]['home_team_id']);away=number(g[0]['away_team_id']);score={home:0,away:0};board=0
        for r in g:
            p=(gid,r['_period']);period_rows[p].append(r)
            if p not in quality:quality[p]={'flags':set(),'snapshot':0,'cumulative':0,'scope':'special' if gid in {401781604,401736430} else 'playoffs' if number(g[0]['season_type'])==3 else 'regular'}
            q=quality[p];total=number(r['home_score'])+number(r['away_score'])
            if total-board!=r['_points']:q['flags'].add('score_snapshot_conflict');q['snapshot']+=1
            board=total
            if r['_team'] in score:score[r['_team']]+=r['_points'];team_points[gid,r['_team']]+=r['_points']
            if score[home]!=number(r['home_score']) or score[away]!=number(r['away_score']):q['flags'].add('cumulative_score_conflict');q['cumulative']+=1
            if r['_type'] in SPECIAL|FOUL:q['flags'].add('special_free_throw_or_foul')
            if r['_type'] in {215,279}:q['flags'].add('overturned_review')
            if r['_type']==615:
                match=re.search(r'\((.*?) gains possession\)',r['text']);winner=names.get((gid,match.group(1)),set()) if match else set()
                evidence=[next(iter(winner))] if len(winner)==1 else []
                if r['athlete_id_3'].strip().lower() not in ['','na','nan','null']:
                    team=roster.get((gid,number(r['athlete_id_3'])))
                    if team is not None:evidence.append(team)
                if not evidence or any(t!=r['_team'] for t in evidence):q['flags'].add('unvalidated_jump_winner')
        for p in [(gid,k) for k in sorted({r['_period'] for r in g})]:
            a=period_rows[p];q=quality[p];duration=600 if p[1]<=4 else 300
            if any(r['_seconds']<0 or r['_seconds']>duration for r in a):q['flags'].add('invalid_clock')
            if any(y['_seconds']>x['_seconds'] for x,y in zip(a,a[1:])):q['flags'].add('clock_reversal')
            if not any(r['_type'] in {402,412} for r in a):q['flags'].add('missing_period_end')
    old_periods=pd.read_csv(BASE/'possession/period_quality.csv').fillna({'flags':''})
    for r in old_periods.itertuples():
        q=quality[r.game_id,r.period_number];assert flags(r.flags)==q['flags'] and r.scope==q['scope'] and r.rows==len(period_rows[r.game_id,r.period_number]) and r.score_snapshot_conflicts==q['snapshot'] and r.cumulative_score_conflicts==q['cumulative']
    boxes={(number(r['game_id']),number(r['team_id'])):number(r['team_score']) for r in teams if number(r['season'])==2025}
    check('Fresh source parsing independently rebuilds every period quality flag and all 624 team scores',len(boxes)==624 and all(team_points[k]==v for k,v in boxes.items()) and len(quality)==1257)
    observed={r['_type'] for r in raw if re.search('technical|flagrant|clear path|away from|take foul|overturned|double personal',r['type_text'],flags=re.I)}
    check('Hazard catalog covers every observed special/review label family',observed==HAZARD==set(rule['hazard_type_ids']))
    episodes=pd.read_csv(OLD/'all_episodes.csv.gz',float_precision='round_trip');original_states=pd.read_csv(OLD/'all_states.csv.gz',dtype={'offense_team_id':str,'defense_team_id':str},float_precision='round_trip').set_index('state_id')
    starts={(r.game_id,r.period_number,int(r.start_source_row)):r for r in episodes.itertuples() if r.start_reason=='defensive_rebound' and r.start_anchored}
    independent={}
    for p,q in quality.items():
        if not q['flags'] or not q['flags']<=SOFT or q['scope']=='special':continue
        rows=period_rows[p];last=max(i for i,r in enumerate(rows) if r['_type'] in HAZARD);last_clock=rows[last]['_seconds'];anchors=[]
        # Look backwards to the preceding significant opportunity, rather than
        # sharing the recovery implementation's pending miss loop.
        for i in range(last+1,len(rows)):
            r=rows[i]
            if r['_type']!=155 or r['_seconds']>=last_clock:continue
            prior=[j for j in range(last+1,i) if rows[j]['_fga'] or rows[j]['_type'] in set(FT)|TO|{11,155,156,615,402,412}]
            if not prior:continue
            m=rows[prior[-1]]
            if not m['_fga'] or m['_points']!=0 or m['_team']==r['_team'] or m['_team'] is None or m['_seconds']<r['_seconds']:continue
            following=next((v for v in rows[i+1:] if v['_fga'] or v['_type'] in set(FT)|TO|{11,155,615,402,412}),None)
            if following is None or not (following['_fga'] or following['_type'] in set(FT)|TO|{11}) or following['_team']!=r['_team']:continue
            if following['_type']==11:assert 'violation' in following['text'].lower()
            e=starts.get((p[0],p[1],r['_row']))
            if e is None or int(e.offense_team_id)!=r['_team']:continue
            anchors.append({'row':r['_row'],'play':r['_play'],'miss':m['_row'],'corroboration':following['_row'],'hazard':rows[last]['_row']})
        independent[p]=anchors
    manifest=pd.read_csv(OUT/'recovery_periods.csv');expected_episodes={};selected={}
    for policy,required in [('first_rebound',1),('second_rebound',2)]:
        m=manifest[manifest.policy.eq(policy)].set_index(['game_id','period_number']);allowed={}
        for p,q in quality.items():
            r=m.loc[p];candidate=p in independent;assert bool(r.candidate_period)==candidate
            if candidate:
                a=independent[p];assert r.qualified_restarts==len(a)
                if len(a)>=required:
                    chosen=a[required-1];allowed[p]=chosen
                    assert r.status=='tail_available' and r.restart_source_row==chosen['row'] and r.miss_source_row==chosen['miss'] and r.corroboration_source_row==chosen['corroboration'] and r.last_hazard_source_row==chosen['hazard']
                else:assert r.status=='no_supported_restart'
            elif q['flags'] and q['scope']!='special':assert r.status=='hard_period_exclusion'
        new=set()
        for r in episodes.itertuples():
            anchor=allowed.get((r.game_id,r.period_number))
            if anchor and flags(r.flags)<=SOFT and r.start_anchored and r.scope!='special' and raw[int(r.start_source_row)-2]['_play']>=anchor['play']:new.add(r.episode_id)
        expected=set(original_states.index[original_states.eligible])|set(original_states.index[original_states.episode_id.isin(new)&original_states.seconds_remaining.gt(2)])
        a=pd.read_csv(PRIVATE/f'{policy}_states.csv.gz',dtype={'offense_team_id':str,'defense_team_id':str},float_precision='round_trip').set_index('state_id')
        assert not a.index.duplicated().any() and set(a.index)==expected and a.recovery_eligible.all()
        reference=original_states.loc[a.index]
        for c in FEATURES+['remaining_points','episode_points','game_id','source_row','split','eligible']:assert a[c].eq(reference[c]).all(),(policy,c)
        assert a.cohort.eq(np.where(reference.eligible,'original','recovered')).all()
        selected[policy]=a;expected_episodes[policy]=new
    check('Every recovery decision independently satisfies the last hazard, live rebound, owner corroboration and original parser anchor rules')
    check('Both expanded samples retain every original row and copy all features and labels without editing',set(selected['second_rebound'].index)<=set(selected['first_rebound'].index))
    ledger=pd.read_csv(OLD/'event_ledger.csv.gz',float_precision='round_trip');ledger['position']=np.arange(len(ledger));positions=ledger.set_index('source_row').position.to_dict()
    for r in ledger.itertuples():
        q=raw[int(r.source_row)-2];assert r.game_id==q['_gid'] and r.period_number==q['_period'] and r.type_id==q['_type'] and r.points==q['_points']
        if r.reward_lane=='ordinary':assert q['_fga'] or q['_type'] in FT
        if r.reward_lane=='special_free_throw':assert q['_type'] in SPECIAL
    sums=ledger[ledger.reward_lane.eq('ordinary')].groupby('episode_id').points.sum()
    assert np.array_equal(episodes.points,sums.reindex(episodes.episode_id).fillna(0))
    check('All ledger rewards remain original, counted once, and reconcile with the complete source score',int(ledger.points.sum())==51073 and int(episodes.points.sum())==50774 and int(ledger.loc[ledger.reward_lane.eq('special_free_throw'),'points'].sum())==299)
    prefix={}
    for eid,a in ledger[ledger.episode_id.notna()].groupby('episode_id',sort=False):
        arrays=[];pending=0
        for r in a.itertuples():
            q=raw[int(r.source_row)-2];orb=int(q['_type']==156 and pending==0)
            if q['_type'] in FT:
                n,total=FT[q['_type']];pending=n+1 if n<total else 0
            arrays.append([q['_points'] if r.reward_lane=='ordinary' else 0,int(q['_fga']),int(q['_type'] in FT),orb])
        prefix[eid]=(a.position.to_numpy(),np.cumsum(np.asarray(arrays),axis=0))
    ep=episodes.set_index('episode_id')
    for r in selected['first_rebound'].itertuples():
        q=raw[int(r.source_row)-2];position=positions[r.source_row];x=prefix.get(r.episode_id);counts=np.zeros(4,dtype=int)
        if x is not None:
            i=np.searchsorted(x[0],position,side='right')-1
            if i>=0:counts=x[1][i]
        assert np.array_equal(counts,[r.points_so_far,r.fga_so_far,r.fta_so_far,r.offensive_rebounds_so_far]),r.Index
        assert r.remaining_points==ep.loc[r.episode_id,'points']-counts[0] and r.episode_points==ep.loc[r.episode_id,'points']
        sign=1 if int(r.offense_team_id)==number(q['home_team_id']) else -1
        assert r.home==int(sign==1) and r.score_margin==sign*(number(q['home_score'])-number(q['away_score']))
        assert np.isclose(r.elapsed_seconds,ep.loc[r.episode_id,'start_seconds']-r.seconds_remaining)
    check('Every expanded state reward target, past field goal/free throw/rebound count, clock and source score margin independently recomputes')
    check('Predictors exclude future rewards, eligibility, terminal actions, player IDs and invented spatial movement',fit['features']==FEATURES and not set(FEATURES)&{'remaining_points','episode_points','cohort','eligible','recovery_eligible','end_reason','end_seconds','athlete_id','text','coordinate_x'})
    for policy,a in selected.items():
        for split,lo,hi in [('train','2025-05-01','2025-08-09'),('validation','2025-08-10','2025-08-26'),('test','2025-08-27','2025-09-11'),('playoffs','2025-09-14','2025-10-10')]:
            b=a[a.split.eq(split)];assert b.date.between(lo,hi).all() and not set(b.game_id)&set(a.loc[a.split.ne(split),'game_id'])
    check('Every state and game obeys the original disjoint chronological cutoffs')
    coverage=pd.read_csv(OUT/'recovery_coverage.csv');cohorts=pd.read_csv(OUT/'recovery_cohorts.csv')
    for r in coverage.itertuples():
        a=selected[r.policy];added=a[a.cohort.eq('recovered')]
        assert len(a)==r.total_states and a.stage.eq('entry').sum()==r.total_entry_states and len(added)==r.added_states and added.stage.eq('entry').sum()==r.added_entry_states and len(added[['game_id','period_number']].drop_duplicates())==r.periods_with_added_states
    for r in cohorts.itertuples():
        a=selected[r.policy];a=a[a.cohort.eq(r.cohort)&a.split.eq(r.split)&a.stage.eq(r.stage)]
        assert len(a)==r.states and a.episode_id.nunique()==r.episodes and a.game_id.nunique()==r.games and np.isclose(a.remaining_points.mean(),r.mean_remaining_points) and np.isclose(a.seconds_remaining.mean(),r.mean_period_seconds)
    check('All coverage, cohort counts and clock/outcome means rebuild from qualified state keys')
    cases=pd.read_csv(OUT/'source_case_events.csv');index=pd.read_csv(OUT/'source_case_index.csv')
    for r in cases.itertuples():
        q=raw[int(r.source_row)-2]
        for c in ['game_id','period_number','game_play_number','type_id','score_value','home_score','away_score']:assert getattr(r,c)==number(q[c])
        assert str(r.clock_display_value)==q['clock_display_value'] and r.type_text.replace('\r\n','\n')==q['type_text'].replace('\r\n','\n')
        assert pd.isna(r.team_id) and q['_team'] is None or r.team_id==q['_team']
    check('Source case snippets exactly match the ZIP and cover all 24 observed hazard types',set(index.type_id)==HAZARD and not cases.duplicated(['case_id','source_row']).any())
    for script in ['test_possession_reconstruction.py','test_possession_recovery.py']:
        result=subprocess.run([sys.executable,str(HERE/script)],check=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True);print(result.stdout,flush=True)
    check('All eight original parser tests and twelve recovery scenarios pass, including every hazard type')
    fitted=joblib.load(PRIVATE/'models.joblib');frozen=joblib.load(OLD/'models.joblib');predictions={};edges=np.array([2,5,24,60,120,300,601])
    original_train=original_states[original_states.eligible&original_states.split.eq('train')];old_means=original_train.groupby('stage').remaining_points.mean().to_dict()
    def clock_values(a):
        means=a.groupby('stage').remaining_points.mean().to_dict();b=a.assign(bin=np.digitize(a.seconds_remaining,edges)-1).groupby(['stage','bin']).remaining_points.agg(['sum','count'])
        return means,{key:(r['sum']+50*means[key[0]])/(r['count']+50) for key,r in b.iterrows()}
    old_clock_means,old_values=clock_values(original_train)
    for policy,a in selected.items():
        train=a[a.split.eq('train')];models=fitted['fits'][policy];record=next(r for r in fit['fits'] if r['policy']==policy)
        assert models['context'].get_params()==frozen['models']['Context boosting EPV'].get_params()==fit['context_parameters']
        assert record['training_states']==len(train) and record['training_entry_states']==train.stage.eq('entry').sum() and record['last_training_date']==train.date.max()=='2025-08-09'
        means,values=clock_values(train)
        p=pd.read_csv(PRIVATE/f'{policy}_predictions.csv.gz',float_precision='round_trip').set_index('state_id');expected=a[a.split.ne('train')].loc[p.index]
        assert len(p)==len(a[a.split.ne('train')]) and not p.index.duplicated().any() and p.remaining_points.eq(expected.remaining_points).all()
        for c in ['game_id','source_row','split','stage','cohort','episode_id']:assert p[c].eq(expected[c]).all()
        for name,mn,lookup in [('Frozen clock',old_clock_means,old_values),('Expanded clock',means,values)]:
            computed=[lookup.get((r.stage,int(np.digitize(r.seconds_remaining,edges)-1)),mn[r.stage]) for r in expected.itertuples()]
            assert np.allclose(computed,p[name],atol=1e-12,rtol=1e-12)
        assert np.allclose(expected.stage.map(old_means),p['Frozen average'],atol=1e-12) and np.allclose(expected.stage.map(means),p['Expanded average'],atol=1e-12)
        sample=expected
        for label,model,levels in [('Frozen context',frozen['models']['Context boosting EPV'],frozen['levels']),('Expanded context',models['context'],models['levels'])]:
            x=sample[FEATURES].copy()
            for c in levels:x[c]=pd.Categorical(x[c].where(x[c].isin(levels[c])),categories=levels[c])
            assert np.allclose(model.predict(x),p.loc[sample.index,label],atol=1e-12,rtol=1e-12)
        for label,model in [('Frozen Markov',frozen['models']['Markov EPV']),('Expanded Markov',models['markov'])]:
            ks=[f'{r.stage}|{r.start_reason if r.stage=="entry" else "any"}|{int(np.digitize(r.seconds_remaining,edges)-1)}|{int(r.home)}' for r in expected.itertuples()]
            computed=[model.V[model.index[k]] if k in model.index else model.fallback[stage] for k,stage in zip(ks,expected.stage)]
            assert np.allclose(computed,p[label],atol=1e-12,rtol=1e-12)
        # Rebuild each expanded Markov matrix from adjacent state arrays.
        m=models['markov'];visits=np.zeros(len(m.labels));reward=np.zeros(len(m.labels));transition=np.zeros_like(m.P)
        for _,b in train.groupby('episode_id',sort=False):
            ks=[f'{r.stage}|{r.start_reason if r.stage=="entry" else "any"}|{int(np.digitize(r.seconds_remaining,edges)-1)}|{int(r.home)}' for r in b.itertuples()];ix=np.array([m.index[k] for k in ks])
            np.add.at(visits,ix,1);np.add.at(reward,ix,np.r_[np.diff(b.points_so_far),b.remaining_points.iloc[-1]])
            if len(ix)>1:np.add.at(transition,(ix[:-1],ix[1:]),1)
        P=transition/(visits[:,None]+m.alpha);r=(reward+m.alpha*np.array([means[k.split('|')[0]] for k in m.labels]))/(visits+m.alpha)
        v=np.zeros(len(m.labels))
        for _ in range(1000):
            nxt=r+P@v
            if max(abs(nxt-v))<1e-13:break
            v=nxt
        assert np.allclose(P,m.P,atol=1e-14) and np.allclose(r,m.r,atol=1e-14) and np.allclose(nxt,m.V,atol=1e-12) and (P.sum(axis=1)<1).all() and np.isfinite(m.V).all() and (m.V>=0).all()
        predictions[policy]=p
    check('All fixed fit settings and training counts verify; saved context, clock, average and Markov inference reproduce')
    check('Both expanded Markov transition matrices and iterative value solutions independently reconstruct')
    metrics=pd.read_csv(OUT/'metrics.csv');boot=pd.read_csv(OUT/'game_bootstrap.csv')
    def subset(table,r):
        a=table[table.split.eq(r.split)];a=a if r.cohort=='all' else a[a.cohort.eq(r.cohort)]
        return a if r.stage=='all_states' else a[a.stage.eq(r.stage)]
    for r in metrics.itertuples():
        a=subset(predictions[r.policy],r);v=a[r.model].to_numpy();y=a.remaining_points.to_numpy();assert np.isfinite(v).all() and (v>=0).all()
        assert len(a)==r.states and a.game_id.nunique()==r.games and a.episode_id.nunique()==r.episodes
        assert np.allclose([np.sqrt(np.mean((v-y)**2)),np.mean(abs(v-y)),v.mean(),y.mean()],[r.rmse,r.mae,r.mean_prediction,r.mean_observed],atol=1e-12)
    check('Every metric uses identical state keys and independently recomputes for all policies, stages, splits and cohorts')
    for r in boot.itertuples():
        a=subset(predictions[r.policy],r);d,ci=interval(a,r.model,r.baseline)
        assert len(a)==r.states and a.game_id.nunique()==r.games and np.isclose(d,r.mse_difference,atol=1e-12) and np.allclose(ci,[r.lower,r.upper],atol=1e-12)
    check('Every paired game bootstrap effect and interval independently recomputes')
    first=predictions['first_rebound'];second=predictions['second_rebound'];common=first.loc[second.index]
    for r in pd.read_csv(OUT/'policy_sensitivity.csv').itertuples():
        a=subset(common,r).copy();a['stricter']=second.loc[a.index,r.model].to_numpy();d,ci=interval(a,r.model,'stricter')
        assert len(a)==r.states and np.isclose(d,r.mse_difference,atol=1e-12) and np.allclose(ci,[r.lower,r.upper],atol=1e-12)
    check('Stricter policy effects compare identical shared states and independently reproduce')
    cal=pd.read_csv(OUT/'calibration.csv')
    for (policy,split,stage,model),a in cal.groupby(['policy','split','stage','model']):
        p=predictions[policy];p=p[p.split.eq(split)&p.stage.eq(stage)]
        assert a.states.sum()==len(p) and np.isclose(np.average(a.mean_prediction,weights=a.states),p[model].mean()) and np.isclose(np.average(a.mean_observed,weights=a.states),p.remaining_points.mean())
    check('Calibration bins cover every state and preserve predicted and observed means')
    public=json.loads((HERE.parent/'assets/recovery.json').read_text(encoding='utf-8'))
    check('Website recovery data exactly matches the independently checked result files',public['coverage']==coverage.to_dict('records') and public['metrics']==metrics.to_dict('records') and public['bootstrap']==boot.to_dict('records') and public['cohorts']==cohorts.to_dict('records') and public['sensitivity']==pd.read_csv(OUT/'policy_sensitivity.csv').to_dict('records') and public['fit']==fit and public['rule']==rule)
    check('Original artifacts remain unchanged after verification',all(digest(HERE.parent/p)==h for p,h in rule['original_frozen_input_hashes'].items()))
    if args.live:
        for path in [HERE.parent/'assets/recovery.json',HERE.parent/'recovery.js',HERE.parent/'theme.js',HERE.parent/'meeting/index.html']+list(OUT.glob('*.csv'))+list(OUT.glob('*.png')):
            relative=path.relative_to(HERE.parent).as_posix();data=urllib.request.urlopen('https://kevinyamada.github.io/wnba-shot-atlas/'+relative+'?verify='+str(time.time_ns()),timeout=40).read()
            assert data==path.read_bytes() if path.suffix=='.png' else data.replace(b'\r\n',b'\n')==path.read_bytes().replace(b'\r\n',b'\n'),relative
        check('All recovery web assets, result tables and figures match the live publication')
        browser=json.loads((BASE/'live_site_checks.json').read_text(encoding='utf-8'));check('Main app and meeting walkthrough pass final real browser checks',browser['all_pass'] and 'Recovery controls and tables' in browser['checks'] and 'Meeting walkthrough controls and layout' in browser['checks'])
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip();remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],cwd=HERE.parent,text=True).split()[0];check('Checked analysis commit matches GitHub main',head==remote)
    record={'all_checks_pass':True,'checks':checks,'only_data_source':'Data (1).zip','archive_sha256':rule['archive_sha256'],'compute':'desktop CPU only',
        'analysis_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip(),'completed_utc':pd.Timestamp.now(tz='UTC').isoformat(),'stage':'final after publication' if args.live else 'development'}
    (OUT/('final_verification.json' if args.live else 'development_verification.json')).write_text(json.dumps(record,indent=2),encoding='utf-8');print('RECOVERY_VERIFICATION_ALL_PASS',len(checks),flush=True)


if __name__=='__main__':main()
