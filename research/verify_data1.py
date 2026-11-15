"""Independent final verification, run after analysis and publication.

Read the original ZIP again with csv.DictReader. Do not import preparation or
model scoring functions. Validate source identities, lagged inputs, predictions,
metrics, bootstrap intervals, posterior diagnostics and every published cell.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import subprocess
import time
import urllib.request
import zipfile
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import logit,expit
from scipy.stats import rankdata
from scipy.spatial import cKDTree

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1'
DATA=HERE/'data/data1'
SHA='22a86860e179ce40ed34648c592bbd384297ddd5833000117973308a915a2120'
SPECIAL={401781604,401736430}
CHECKS=[]


def checked(name,condition):
    assert condition,name
    CHECKS.append(name)
    print('CHECK',name,flush=True)


def digest(stream):
    h=hashlib.sha256()
    for b in iter(lambda:stream.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()


def integer(x):return int(float(x))
def flag(x):return x.lower()=='true'
def optional_count(x):return 0 if x.strip().lower() in ['', 'na','nan','null'] else integer(x)


def independent_score(y,p):
    y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-12,1-1e-12)
    ranks=rankdata(p);positive=y.sum();negative=len(y)-positive
    return {'shots':len(y),'brier':float(((p-y)**2).mean()),'log_loss':float(-(y*np.log(p)+(1-y)*np.log1p(-p)).mean()),
            'auc':float((ranks[y==1].sum()-positive*(positive+1)/2)/(positive*negative)),
            'mean_prediction':float(p.mean()),'observed':float(y.mean())}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--live-url',default='https://kevinyamada.github.io/wnba-shot-atlas/')
    ap.add_argument('--modal-python',help='Optional interpreter with Modal SDK for the final read-only shutdown check');args=ap.parse_args()
    start=time.time();audit=json.loads((HERE/'results/archive_audit.json').read_text(encoding='utf-8'))
    with args.source.open('rb') as f:actual_sha=digest(f)
    checked('Original Data (1).zip is unchanged',args.source.name=='Data (1).zip' and actual_sha==SHA==audit['source_sha256'] and args.source.stat().st_size==1937912926)
    with zipfile.ZipFile(args.source) as z:
        members={m['path']:m for m in audit['members']}
        checked('All 45 files and directory are inventoried',set(z.namelist())==set(members) and sum(not m['is_directory'] for m in members.values())==45)
        for entry in z.infolist():
            if entry.is_dir():continue
            with z.open(entry) as f:h=digest(f)
            assert h==members[entry.filename]['sha256'] and entry.file_size==members[entry.filename]['bytes'],entry.filename
        CHECKS.append('All 45 member byte counts and SHA-256 hashes independently match')
        manifest=list(csv.DictReader((HERE/'results/archive_manifest.csv').open(encoding='utf-8')))
        checked('Public manifest agrees with current inventory',len(manifest)==45 and all(all(str(row[k])==str(members[row['path']].get(k,'')) for k in row) for row in manifest))
        def load(suffix):
            name=next(n for n in z.namelist() if n.endswith(suffix))
            return list(csv.DictReader(io.TextIOWrapper(z.open(name),encoding='utf-8-sig',newline='')))
        events=load('/original/wehoop_wnba_pbp.csv')
        players=load('/WNBA_player/wnba_player_box.csv')
        teams=load('/WNBA_Team/wnba_team_box.csv')
    keys=set();raw={};by_game=defaultdict(list);player_counts=defaultdict(lambda:np.zeros(3,dtype=int));team_counts=defaultdict(lambda:np.zeros(3,dtype=int));conflicts=0
    # Score updates follow the original game/play sort, independently of the
    # preparation script. Source-row identity remains the original CSV record.
    for line,r in enumerate(events,2):r['_source_row']=line
    previous={}
    for r in sorted(events,key=lambda r:(integer(r['game_id']),integer(r['game_play_number']))):
        g=integer(r['game_id']);play=integer(r['game_play_number']);key=(g,play)
        assert key not in keys;keys.add(key)
        h,a=integer(r['home_score']),integer(r['away_score']);old=previous.get(g,(0,0));previous[g]=(h,a)
        if not flag(r['shooting_play']) or 'free throw' in r['type_text'].lower():continue
        p=integer(r['score_value']);made=int(flag(r['scoring_play']));assert p in [0,2,3] and (p>0)==bool(made)
        t=integer(r['team_id']);athlete=integer(r['athlete_id_1']);home=int(t==integer(r['home_team_id']));sign=1 if home else -1
        x=41.75-sign*float(r['coordinate_x']);y=sign*float(r['coordinate_y'])
        minutes,seconds=map(float,r['clock_display_value'].split(':'))
        scope='special' if g in SPECIAL else 'playoffs' if integer(r['season_type'])==3 else 'regular'
        date=r['game_date'][:10]
        split='playoffs' if scope=='playoffs' else 'special' if scope=='special' else 'train' if date<'2025-08-10' else 'validation' if date<'2025-08-27' else 'test'
        q={'source_row':r['_source_row'],'game_id':g,'game_play_number':play,'player_id':str(athlete),'team_id':str(t),'made':made,'points':p,'x':x,'y':y,'home':home,
           'period_number':integer(r['period_number']),'seconds':60*minutes+seconds,'scope':scope,'split':split,'date':date,'date_time':r['game_date_time']}
        raw[r['_source_row']]=q;by_game[g].append(q)
        counts=np.array([1,made,p]);player_counts[g,athlete]+=counts;team_counts[g,t]+=counts
        conflicts+=h-old[0]+a-old[1]!=p
    checked('Original event keys, source rows and shot outcomes are valid',len(events)==121342 and len(raw)==42193)
    checked('All 88 source score-update conflicts are disclosed',conflicts==88)
    current_players={};prior_counts=defaultdict(lambda:np.zeros(2,dtype=int));names={}
    for r in players:
        season=integer(r['season']);athlete=integer(r['athlete_id']);g=integer(r['game_id'])
        n=optional_count(r['field_goals_attempted']);k=optional_count(r['field_goals_made']);three=optional_count(r['three_point_field_goals_made'])
        assert 0<=k<=n
        if season==2025:
            assert (g,athlete) not in current_players
            current_players[g,athlete]=np.array([n,k,2*k+three]);names[g,athlete]=r['athlete_display_name']
        if 2022<=season<=2024 and integer(r['season_type'])==2:prior_counts[athlete]+=np.array([n,k])
    bad=[]
    for key in set(current_players)|set(player_counts):
        assert key in current_players
        if not np.array_equal(current_players[key],player_counts[key]):bad.append(key)
    excluded={g for g,p in bad}
    checked('Independent outer player comparison reproduces all eight exclusions',len(bad)==18 and excluded==set(pd.read_csv(OUT/'excluded_games.csv').game_id))
    nteams=0
    for r in teams:
        if integer(r['season'])!=2025:continue
        key=(integer(r['game_id']),integer(r['team_id']))
        expected=np.array([integer(r['field_goals_attempted']),integer(r['field_goals_made']),2*integer(r['field_goals_made'])+integer(r['three_point_field_goals_made'])])
        assert np.array_equal(team_counts.pop(key),expected);nteams+=1
    checked('All 624 game/team attempts, makes and FG points reconcile',nteams==624 and not team_counts)
    # Independently rebuild counts available strictly before each player's game.
    history=defaultdict(lambda:np.zeros(2,dtype=int));expected_history={}
    for g,shots in sorted(by_game.items(),key=lambda item:(item[1][0]['date_time'],item[0])):
        if shots[0]['scope']!='regular' or g in excluded:continue
        game_counts=defaultdict(lambda:np.zeros(2,dtype=int))
        for q in shots:
            athlete=int(q['player_id']);expected_history[g,athlete]=history[athlete].copy();game_counts[athlete]+=np.array([1,q['made']])
        for athlete,c in game_counts.items():history[athlete]+=c
    expected={row:q for row,q in raw.items() if q['scope'] in ['regular','playoffs'] and q['game_id'] not in excluded and -5.25<=q['x']<=41.75}
    table=pd.read_csv(DATA/'model_shots.csv.gz',dtype={'player_id':str,'team_id':str})
    checked('Model cohort has precisely the eligible source records',len(table)==40683 and not table.source_row.duplicated().any() and set(table.source_row)==set(expected))
    for q in table.to_dict('records'):
        r=expected[q['source_row']]
        for c in ['game_id','game_play_number','player_id','team_id','made','points','x','y','home','period_number','seconds','scope','split','date']:assert q[c]==r[c],(q['source_row'],c,q[c],r[c])
        athlete=int(r['player_id']);pre_n,pre_k=prior_counts[athlete]
        hn,hk=history[athlete] if r['scope']=='playoffs' else expected_history[r['game_id'],athlete]
        for c,value in {'distance':math.hypot(r['x'],r['y']),'angle':math.atan2(abs(r['y']),r['x']),'prior_rate':(hk+22)/(hn+50),'log_prior_n':math.log1p(hn),'preseason_rate':(pre_k+22)/(pre_n+50),'preseason_log_n':math.log1p(pre_n)}.items():assert np.isclose(q[c],value,rtol=1e-12,atol=1e-12),(q['source_row'],c)
        assert q['player']==names[r['game_id'],athlete]
    CHECKS.append('Every model label, coordinate, name, clock and lagged/preseason predictor matches the original archive')
    for split,count in [('train',25751),('validation',5995),('test',5626),('playoffs',3311)]:assert table.split.eq(split).sum()==count
    bounds=table.groupby('split').date.agg(['min','max'])
    for l,r in [('train','validation'),('validation','test'),('test','playoffs')]:assert bounds.loc[l,'max']<bounds.loc[r,'min']
    checked('Dates and games are disjoint across temporal cohorts',table.groupby('game_id').split.nunique().eq(1).all())
    source=json.loads((OUT/'source_audit.json').read_text())
    launch=json.loads((DATA/'input_manifest.json').read_text())
    checked('GPU inputs and executed model code retain their recorded hashes',launch['source_archive_sha256']==SHA and launch['model_table_sha256']==hashlib.sha256((DATA/'model_shots.csv.gz').read_bytes()).hexdigest() and launch['gpu_code_sha256']==hashlib.sha256((HERE/'gpu_models.py').read_bytes()).hexdigest())
    past_check=json.loads((OUT/'preseason_history_audit.json').read_text())
    checked('All 1404 supplied historical game/team count sums agree',past_check['all_game_teams_present_in_both'] and past_check['game_team_rows']==1404 and past_check['disagreeing_game_team_rows']==0)
    checked('Predictor allowlist excludes post-outcome fields',set(source['numeric_features'])=={'x','y','distance','angle','period_number','seconds','home','prior_rate','log_prior_n','preseason_rate','preseason_log_n'} and source['categorical_features']==['player_id','team_id'])
    predictions=pd.read_csv(DATA/'comparison_predictions.csv.gz')
    truth=table[table.split.ne('train')].set_index('source_row')
    checked('Every compared prediction uses identical source keys and outcomes',not predictions.source_row.duplicated().any() and set(predictions.source_row)==set(truth.index))
    for q in predictions.to_dict('records'):
        r=expected[q['source_row']]
        for c in ['game_id','game_play_number','made','points','split']:assert q[c]==r[c]
    meta=['source_row','game_id','game_play_number','made','points','split'];models=[c for c in predictions if c not in meta]
    checked('All comparison probabilities are finite and bounded',np.isfinite(predictions[models]).all().all() and predictions[models].ge(0).all().all() and predictions[models].le(1).all().all())
    metrics=pd.read_csv(OUT/'metrics.csv')
    for r in metrics.to_dict('records'):
        a=predictions[predictions.split.eq(r['split'])];score=independent_score(a.made,a[r['model']])
        assert all(np.isclose(r[k],v,atol=1e-12,rtol=1e-10) for k,v in score.items()),r
    CHECKS.append('Every published Brier score, log loss, AUC and mean independently recomputes')
    selection=json.loads((OUT/'selection_receipt.json').read_text())
    val=metrics[metrics.split.eq('validation')].sort_values('log_loss')
    checked('Primary model choice agrees with validation loss alone',selection['selected_model']==val.iloc[0].model and selection['test_not_used_for_selection'])
    checked('Ensemble uses the five declared equal weights',np.allclose(predictions['Equal-weight ensemble'],predictions[selection['ensemble_components']].mean(axis=1)))
    target_order=predictions.source_row.to_numpy()
    gp_saved=pd.read_csv(OUT/'experiments'/selection['selected_gp_id']/'predictions.csv.gz').set_index('source_row').loc[target_order]
    checked('Chosen GP predictions are the saved selected fit',np.allclose(gp_saved.prediction,predictions['Bayesian GP']))
    for family in ['CatBoost spatial','CatBoost context','XGBoost spatial','XGBoost context','Joint 0/2/3 points']:
        parts=[pd.read_csv(OUT/'experiments'/f'boost-main-{seed}-v214'/'predictions.csv.gz').set_index('source_row').loc[target_order,family].to_numpy() for seed in [2026,2027,2028]]
        assert np.allclose(np.mean(parts,axis=0),predictions[family])
    CHECKS.append('All GPU tree family predictions equal the three declared saved seed fits')
    cal=json.loads((OUT/'calibration_parameters.json').read_text())
    checked('Calibration transformation and reporting are coherent',np.allclose(predictions['Validation-calibrated ensemble'],expit(cal['intercept']+cal['slope']*logit(predictions['Equal-weight ensemble'].clip(1e-8,1-1e-8)))) and not ((metrics.model=='Validation-calibrated ensemble')&(metrics.split=='validation')).any())
    # Independently reproduce the paired, cluster-resampled confidence intervals.
    for split,a in predictions.groupby('split'):
        if split=='validation':continue
        groups=a.groupby('game_id');games=sorted(a.game_id.unique());sizes=groups.size().reindex(games).to_numpy()
        rng=np.random.default_rng(20261115);weights=rng.multinomial(len(games),np.full(len(games),1/len(games)),size=2000)
        for r in pd.read_csv(OUT/'game_bootstrap.csv').query('split == @split').to_dict('records'):
            diff=(a[r['model']]-a.made)**2-(a['Distance baseline']-a.made)**2
            sums=pd.Series(diff.values,index=a.game_id).groupby(level=0).sum().reindex(games).to_numpy()
            interval=np.quantile((weights@sums)/(weights@sizes),[.025,.975])
            assert np.allclose(interval,[r['lower'],r['upper']],atol=1e-12) and np.isclose(diff.mean(),r['brier_difference'])
    CHECKS.append('All paired game-bootstrap Brier differences and intervals recompute')
    point=pd.read_csv(DATA/'points_comparison_predictions.csv.gz')
    for name,a in point.groupby('model'):
        assert set(a.source_row)==set(truth.index) and not a.source_row.duplicated().any()
        p=a[['p_zero','p_two','p_three']].to_numpy()
        assert np.isfinite(p).all() and (p>=0).all() and (p<=1).all() and np.allclose(p.sum(axis=1),1)
        assert np.allclose(a.make_prediction,a.p_two+a.p_three) and np.allclose(a.expected_points,2*a.p_two+3*a.p_three)
        for r in a.to_dict('records'):assert r['points']==expected[r['source_row']]['points']
    for r in pd.read_csv(OUT/'points_metrics.csv').to_dict('records'):
        a=point[point.model.eq(r['model'])&point.split.eq(r['split'])]
        assert np.isclose(r['rmse'],np.sqrt(((a.expected_points-a.points)**2).mean())) and np.isclose(r['mae'],abs(a.expected_points-a.points).mean())
    CHECKS.append('All joint point probabilities, make/point identities and errors are coherent')
    for split in ['test','playoffs']:
        base=point[point.model.eq('Distance outcome baseline')&point.split.eq(split)].set_index('source_row')
        for r in pd.read_csv(OUT/'points_game_bootstrap.csv').query('split == @split').to_dict('records'):
            a=point[point.model.eq(r['model'])&point.split.eq(split)].set_index('source_row').loc[base.index]
            difference=(a.expected_points-a.points)**2-(base.expected_points-base.points)**2
            g=pd.DataFrame({'game':a.game_id,'d':difference}).groupby('game').d.agg(['sum','count'])
            rng=np.random.default_rng(20261116);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
            interval=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])
            assert np.allclose(interval,[r['lower'],r['upper']],atol=1e-12) and np.isclose(difference.mean(),r['mse_difference'])
    CHECKS.append('All expected-point MSE differences and game-bootstrap intervals recompute')
    gp_dir=OUT/'experiments'/selection['selected_gp_id'];diag=pd.read_csv(gp_dir/'diagnostics.csv')
    checked('Selected GP has finite four-chain diagnostics passing all thresholds',np.isfinite(diag[['r_hat','ess_bulk','ess_tail']]).all().all() and diag.r_hat.max()<1.01 and diag.ess_bulk.min()>=400 and selection['gp_diagnostics']['divergences']==0 and selection['gp_diagnostics']['max_tree_depth_hits']==0)
    surface=pd.read_csv(OUT/'gp_surface.csv');checked('All posterior map means and intervals are ordered and bounded',len(surface)==2397 and not surface.duplicated(['x','y']).any() and surface.lower.between(0,1).all() and surface.upper.between(0,1).all() and (surface.lower<=surface['mean']).all() and (surface['mean']<=surface.upper).all())
    checked('Published surface is the exact selected posterior surface',np.array_equal(surface.to_numpy(),pd.read_csv(gp_dir/'surface.csv').to_numpy()))
    experiments=list((OUT/'experiments').glob('*/task.json'));prediction_files=0
    for path in experiments:
        r=json.loads(path.read_text());c=r.get('config',{});file=path.parent/'predictions.csv.gz'
        if not file.exists():continue
        a=pd.read_csv(file);prediction_files+=1
        assert not a.source_row.duplicated().any()
        for q in a.to_dict('records'):
            raw_q=expected[q['source_row']]
            for field in ['game_id','game_play_number','made','points']:assert q[field]==raw_q[field]
            if c.get('fold','main')=='main':assert q['split']==raw_q['split']
        for col in a.columns.difference(meta):assert np.isfinite(a[col]).all() and a[col].between(0,3 if col=='expected_points' else 1).all()
        if 'expected_points' in a:
            assert np.allclose(a.expected_points,2*a.p_two+3*a.p_three) and np.allclose(a['Joint 0/2/3 points'],a.p_two+a.p_three)
    CHECKS.append(f'All {prediction_files} GPU experiment prediction files join to original Data1 labels')
    folds=pd.read_csv(OUT/'cpu/spatial_folds.csv');cv=pd.read_csv(OUT/'spatial_cv.csv')
    checked('All buffered spatial folds are separated and pooled on the training cohort',len(folds)==12 and (folds.minimum_separation_ft>folds.buffer_ft).all() and cv.groupby(['buffer_ft','model']).shots.sum().eq(25751).all())
    early=table[table.split.eq('train')];blocks=early.x.ge(16).astype(int)*2+early.y.ge(0).astype(int)
    for r in folds.to_dict('records'):
        held=early[blocks.eq(r['fold'])];other=early[blocks.ne(r['fold'])]
        near=cKDTree(held[['x','y']].drop_duplicates()).query(other[['x','y']])[0]
        distances_retained=near[near>r['buffer_ft']]
        assert len(held)==r['test_shots'] and len(distances_retained)==r['train_shots'] and np.isclose(distances_retained.min(),r['minimum_separation_ft'])
    CHECKS.append('Every spatial fold count and buffer separation independently rebuilds from source-verified coordinates')
    site_bytes=(HERE.parent/'assets/data.json').read_bytes();site=json.loads(site_bytes)
    regular=[q for q in raw.values() if q['scope']=='regular'];half=[q for q in regular if -5.25<=q['x']<=41.75]
    counts=defaultdict(lambda:np.zeros(3,dtype=int))
    for q in half:counts[(int(q['x']),int(q['y']),int(q['team_id']),int(q['player_id']))]+=np.array([1,q['made'],q['points']])
    checked('Every website cell/team/player aggregate matches fresh raw event counts',len(counts)==len(site['cells']) and all(np.array_equal(counts[tuple(r[:4])],r[4:]) for r in site['cells']))
    checked('Website season totals match Data1',len(regular)==38535 and len(half)==38441 and sum(q['made'] for q in regular)==16926 and sum(q['points'] for q in regular)==38533)
    checked('Website map and all model tables are the published current results',np.allclose(np.array(site['gp']),surface[['x','y','mean','lower','upper']].to_numpy(),atol=.00000051) and site['metrics']==metrics.to_dict('records') and site['selection']==selection and site['source']==source)
    # Independent finite-segment/arc distance implementation for the density ratio.
    radius=22+1.75/12;join=math.sqrt(radius**2-22**2);angle=math.asin(22/radius)
    def offset(q):
        x,y=q['x'],q['y'];theta=max(-angle,min(angle,math.atan2(y,x)))
        curve=math.hypot(x-radius*math.cos(theta),y-radius*math.sin(theta))
        segment=math.hypot(x-max(-5.25,min(join,x)),abs(y)-22)
        inside=abs(y)<22 if x<=join else math.hypot(x,y)<radius
        return min(curve,segment)*(-1 if inside else 1)
    distances=[offset(q) for q in regular];inside=sum(-2<=d<0 for d in distances);outside=sum(0<d<=2 for d in distances)
    checked('Arc band counts independently match all raw shots',inside==508 and outside==4380 and sum(abs(d)<1e-10 for d in distances)==140)
    checked('Area-adjusted density ratio is coherent',np.isclose(site['arc']['outside_inside_density_ratio'],(outside/site['arc']['outside_2ft_area'])/(inside/site['arc']['inside_2ft_area'])))
    def vector_offset(x,y):
        theta=np.clip(np.arctan2(y,x),-angle,angle)
        curve=np.hypot(x-radius*np.cos(theta),y-radius*np.sin(theta))
        segment=np.hypot(x-np.clip(x,-5.25,join),np.abs(y)-22)
        inside=np.where(x<=join,np.abs(y)<22,np.hypot(x,y)<radius)
        return np.minimum(curve,segment)*np.where(inside,-1,1)
    gx,gy=np.meshgrid(np.arange(-5.225,41.75,.05),np.arange(-24.975,25,.05));gd=vector_offset(gx,gy)
    ai=((gd>=-2)&(gd<0)).sum()*.0025;ao=((gd>0)&(gd<=2)).sum()*.0025
    assert np.isclose(ai,site['arc']['inside_2ft_area']) and np.isclose(ao,site['arc']['outside_2ft_area'])
    arc_games=defaultdict(lambda:np.zeros(2,dtype=int))
    for q,d in zip(regular,distances):arc_games[q['game_id']]+=np.array([int(-2<=d<0),int(0<d<=2)])
    values=np.array([arc_games[g] for g in sorted(arc_games)]);rng=np.random.default_rng(2026)
    w=rng.multinomial(len(values),np.full(len(values),1/len(values)),size=2000)
    interval=np.quantile((w@values[:,1]/ao)/(w@values[:,0]/ai),[.025,.975])
    assert np.allclose(interval,site['arc']['game_bootstrap_95_interval'])
    rx=np.array([q['x'] for q in regular]);ry=np.array([q['y'] for q in regular]);jitter=[]
    for _ in range(100):
        d=vector_offset(np.clip(rx+rng.uniform(-.5,.5,len(rx)),-5.25,88.75),np.clip(ry+rng.uniform(-.5,.5,len(ry)),-25,25))
        jitter.append((((d>0)&(d<=2)).sum()/ao)/(((d>=-2)&(d<0)).sum()/ai))
    checked('Arc areas, 2000-game bootstrap and all coordinate sensitivity scenarios recompute',np.allclose([min(jitter),max(jitter)],site['arc']['coordinate_sensitivity_ratio_range']))
    compute=json.loads((OUT/'compute_usage.json').read_text());billing=compute.get('modal_billing',{})
    stop=json.loads((OUT/'compute_stop.json').read_text())
    checked('Later credit stop is respected and usage is accurately documented',compute['measured_gpu_usd_lower_bound']>0 and 0<billing.get('total_usd_before_credits',0)<40 and stop['all_study_apps_stopped'] and stop['remaining_credit_usd_reported_by_user']==1 and compute['original_measured_gpu_target_met']==(compute['measured_gpu_usd_lower_bound']>=20))
    shutdown=None
    if args.modal_python:
        apps=json.loads(subprocess.check_output([args.modal_python,'-m','modal','app','list','--json'],text=True,encoding='utf-8'))
        study=[r for r in apps if r.get('description')=='wnba-atlas-data1-20261115']
        checked('Live Modal status has zero active study tasks and all study apps stopped',bool(study) and all(r['state']=='stopped' and int(r['tasks'])==0 for r in study))
        shutdown={'study_apps_checked':len(study),'active_tasks':0,'all_stopped':True}
    live=urllib.request.urlopen(args.live_url+'assets/data.json?verify='+str(int(time.time())),timeout=30).read()
    checked('Live GitHub Pages serves the exact verified data artifact',hashlib.sha256(live).hexdigest()==hashlib.sha256(site_bytes).hexdigest())
    browser=json.loads((OUT/'live_site_checks.json').read_text())
    checked('Live desktop/mobile UI checks passed',browser['all_pass'] and browser['javascript_errors']==0 and browser['url']==args.live_url)
    tracked=subprocess.check_output(['git','ls-files'],cwd=HERE.parent,text=True).splitlines()
    forbidden=[p for p in tracked if p.startswith('research/data/') or '/experiments/' in p or p.endswith(('.zip','.pdf','.docx','.npz','.csv.gz')) or p=='research/results/data1/compute_ledger.json' or p.startswith('research/reference/')]
    checked('Git contains no raw source, paper text, private event predictions or obsolete reference outputs',not forbidden)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip()
    remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],cwd=HERE.parent,text=True).split()[0]
    checked('Local analysis commit matches GitHub main',head==remote)
    result={'stage':'Final verification after analysis and publication','completed_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'all_checks_pass':True,'checks':CHECKS,'archive_sha256':actual_sha,'site_data_sha256':hashlib.sha256(site_bytes).hexdigest(),
            'analysis_commit':head,'live_url':args.live_url,'seconds':round(time.time()-start,2),'modal_shutdown':shutdown,
            'remaining_source_limits':['18 player/game attempt discrepancies in eight games; excluded from all models, retained in descriptive maps.','88 shot-score-update conflicts; no score-margin or possession model.','Previously examined 2025 benchmark; no untouched WNBA season in this archive.','Missed-shot two/three labels, tracking and actual shot clock unavailable.']}
    (OUT/'final_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
