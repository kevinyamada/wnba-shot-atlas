"""Independent source and frozen prediction checks for the meeting diagnostics."""
from pathlib import Path
from collections import defaultdict,Counter
import argparse,csv,hashlib,io,json,subprocess,time,urllib.request,zipfile
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;BASE=HERE/'results/data1';OUT=BASE/'meeting';PRIVATE=HERE/'data/data1/possession'


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--live',action='store_true');args=ap.parse_args();checks=[]
    def check(name,condition=True):
        assert condition,name
        checks.append(name);print('CHECK',name,flush=True)
    receipt=json.loads((OUT/'diagnostics_receipt.json').read_text(encoding='utf-8'))
    check('Exact original archive is the only observation source',args.source.name=='Data (1).zip' and digest(args.source)==receipt['archive_sha256'])
    with zipfile.ZipFile(args.source) as z:
        def read(suffix):return list(csv.DictReader(io.TextIOWrapper(z.open(next(n for n in z.namelist() if n.endswith(suffix))),encoding='utf-8-sig',newline='')))
        events=read('/original/wehoop_wnba_pbp.csv');teams=read('/WNBA_Team/wnba_team_box.csv');players=read('/WNBA_player/wnba_player_box.csv')
    periods={};team_points=Counter();howard=0
    for r in events:
        gid=int(r['game_id']);period=int(r['period_number']);tid=int(r['type_id']);key=(gid,period)
        if key not in periods:periods[key]={'events':0,'points':0,'fga':0,'fta':0,'special':0,'month':r['game_date'][:7],
            'home':int(r['home_team_id']),'away':int(r['away_team_id']),'scope':'special' if gid in [401781604,401736430] else 'playoffs' if int(r['season_type'])==3 else 'regular'}
        p=periods[key];p['events']+=1;p['points']+=int(float(r['score_value']))
        fga=r['shooting_play'].lower()=='true' and 'free throw' not in r['type_text'].lower();p['fga']+=int(fga)
        p['fta']+=int(tid in [97,98,99,100,101,102]);p['special']+=int(tid in [103,104,105,106,107,108,157,165,166])
        if r['team_id'].strip().lower() not in ['','na','nan','null']:team_points[gid,int(float(r['team_id']))]+=int(float(r['score_value']))
        if gid==401736112 and fga and int(float(r['athlete_id_1']))==4398674:howard+=1
    boxes={(int(r['game_id']),int(r['team_id'])):int(float(r['team_score'])) for r in teams if int(r['season'])==2025}
    check('Fresh standard library CSV parsing reproduces all 624 final team scores',len(boxes)==624 and all(team_points[k]==v for k,v in boxes.items()))
    q=pd.read_csv(BASE/'possession/period_quality.csv').fillna({'flags':''});by_team=defaultdict(lambda:[0,0]);by_month=defaultdict(lambda:[0,0]);reasons=Counter();reason_events=Counter();comparisons=defaultdict(list);special_only=0
    for r in q.itertuples():
        p=periods[r.game_id,r.period_number];passed=r.flags=='';assert r.scope==p['scope'] and r.rows==p['events']
        flags=set(r.flags.split('|')) if r.flags else set()
        special_only+=int(bool(flags) and flags<={'special_free_throw_or_foul','overturned_review'})
        for reason in flags:reasons[reason]+=1;reason_events[reason]+=p['events']
        if r.scope=='special':continue
        for team in [p['home'],p['away']]:by_team[team][0]+=1;by_team[team][1]+=int(passed)
        by_month[p['month']][0]+=1;by_month[p['month']][1]+=int(passed);comparisons[r.scope,passed].append(p)
    check('Every period and overlapping exclusion reason matches fresh source keys',len(periods)==len(q)==1257 and receipt['passing_periods']==int(q['flags'].eq('').sum()) and special_only==receipt['excluded_only_for_special_or_review_rules']==485)
    for r in pd.read_csv(OUT/'exclusion_reasons.csv').itertuples():assert r.periods==reasons[r.reason] and r.events==reason_events[r.reason]
    for r in pd.read_csv(OUT/'coverage_by_team.csv').itertuples():assert [r.periods,r.passing_periods]==by_team[r.team_id] and np.isclose(r.coverage_fraction,r.passing_periods/r.periods)
    for r in pd.read_csv(OUT/'coverage_by_month.csv').itertuples():assert [r.periods,r.passing_periods]==by_month[r.month] and np.isclose(r.coverage_fraction,r.passing_periods/r.periods)
    check('All 13 team and monthly coverage counts independently rebuild',len(by_team)==13)
    for r in pd.read_csv(OUT/'period_comparison.csv').itertuples():
        a=comparisons[r.scope,r.passes_period_checks];assert len(a)==r.periods
        for source,out in [('points','mean_recorded_points'),('fga','mean_fga'),('fta','mean_ordinary_fta'),('special','mean_special_fta'),('events','mean_events')]:assert np.isclose(np.mean([p[source] for p in a]),getattr(r,out),atol=1e-12)
    check('Retained/excluded period scoring and event summaries reproduce from original rows')
    box=next(r for r in players if int(r['game_id'])==401736112 and int(float(r['athlete_id']))==4398674)
    check('Meeting example independently confirms 14 event attempts versus 15 in the box',howard==14 and int(float(box['field_goals_attempted']))==15)
    s=pd.read_csv(PRIVATE/'model_states.csv.gz',float_precision='round_trip');p=pd.read_csv(PRIVATE/'predictions.csv.gz',float_precision='round_trip')
    a=p.merge(s[['state_id','seconds_remaining','remaining_points','split','stage']],on='state_id',suffixes=('','_source'),validate='one_to_one')
    for c in ['remaining_points','split','stage']:assert a[c].eq(a[c+'_source']).all()
    check('Every diagnostic prediction joins to its verified source state target',len(a)==len(s[s.split.ne('train')]))
    for r in pd.read_csv(OUT/'model_by_stage_clock.csv').itertuples():
        b=a[a.split.eq(r.split)&a.stage.eq(r.stage)]
        if r.clock_group=='2_to_24_seconds':b=b[b.seconds_remaining.le(24)]
        elif r.clock_group=='over_24_seconds':b=b[b.seconds_remaining.gt(24)]
        y=b.remaining_points.to_numpy();v=b[r.model].to_numpy();base=b['Stage mean'].to_numpy();d=(v-y)**2-(base-y)**2
        assert len(b)==r.states and b.game_id.nunique()==r.games and np.isclose(np.sqrt(np.mean((v-y)**2)),r.model_rmse,atol=1e-12) and np.isclose(np.sqrt(np.mean((base-y)**2)),r.baseline_rmse,atol=1e-12)
        g=pd.DataFrame({'game':b.game_id,'d':d}).groupby('game').d.agg(['sum','count']);rng=np.random.default_rng(20261122)
        w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000);ci=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])
        assert np.isclose(d.mean(),r.mse_difference,atol=1e-12) and np.allclose(ci,[r.lower,r.upper],atol=1e-12)
    check('Every state/clock diagnostic error and paired game interval recomputes')
    for r in pd.read_csv(OUT/'prediction_spread.csv').itertuples():
        b=a[a.split.eq(r.split)&a.stage.eq(r.stage)];v=b[r.model].to_numpy();assert len(b)==r.states
        assert np.allclose([v.mean(),v.std(),*np.quantile(v,[.05,.95]),b.remaining_points.mean(),b.remaining_points.std(ddof=0)],
            [r.mean_prediction,r.sd_prediction,r.prediction_05,r.prediction_95,r.mean_observed,r.sd_observed],atol=1e-12)
    check('Every reported prediction spread statistic recomputes')
    clock=json.loads((OUT/'clock_baseline_receipt.json').read_text(encoding='utf-8'));train=s[s.split.eq('train')]
    check('Clock baseline uses only earlier training targets and fixed settings',clock['features']==['stage','seconds_remaining'] and clock['prior_strength']==50 and clock['training_last_date']==train.date.max()=='2025-08-09' and clock['training_states']==len(train))
    edges=clock['clock_edges_seconds'];bucket=lambda t:sum(t>=e for e in edges)-1
    bins=defaultdict(list);stage_values=defaultdict(list)
    for r in train.itertuples():bins[r.stage,bucket(r.seconds_remaining)].append(r.remaining_points);stage_values[r.stage].append(r.remaining_points)
    stage_means={k:np.mean(v) for k,v in stage_values.items()};values={k:(sum(v)+50*stage_means[k[0]])/(len(v)+50) for k,v in bins.items()}
    for r in pd.read_csv(OUT/'clock_baseline_training.csv').itertuples():assert np.isclose(r.expected_points,values[r.stage,r.clock_bin],atol=1e-12) and r.count==len(bins[r.stage,r.clock_bin])
    a['Simple clock average']=[values.get((r.stage,bucket(r.seconds_remaining)),stage_means[r.stage]) for r in a.itertuples()]
    saved=pd.read_csv(PRIVATE/'meeting_clock_predictions.csv.gz',float_precision='round_trip').set_index('state_id')
    check('Training bin sums and every saved clock prediction independently reproduce',len(a)==len(saved) and np.allclose(a['Simple clock average'],saved.loc[a.state_id,'Simple clock average'],atol=1e-12))
    for r in pd.read_csv(OUT/'clock_baseline_metrics.csv').itertuples():
        b=a[a.split.eq(r.split)&a.stage.eq(r.stage)];d=b[r.model]-b.remaining_points
        assert len(b)==r.states and np.isclose(np.sqrt(np.mean(d**2)),r.rmse,atol=1e-12) and np.isclose(np.mean(abs(d)),r.mae,atol=1e-12)
    for r in pd.read_csv(OUT/'clock_baseline_comparisons.csv').itertuples():
        b=a[a.split.eq(r.split)&a.stage.eq(r.stage)];d=(b[r.model]-b.remaining_points)**2-(b['Simple clock average']-b.remaining_points)**2
        g=pd.DataFrame({'game':b.game_id,'d':d}).groupby('game').d.agg(['sum','count']);rng=np.random.default_rng(20261122);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
        ci=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975]);assert np.isclose(d.mean(),r.mse_difference,atol=1e-12) and np.allclose(ci,[r.lower,r.upper],atol=1e-12)
    check('All simple clock comparisons, errors and intervals independently recompute')
    check('All five original model, prediction and website artifacts remain unchanged',all(digest(HERE.parent/rel)==value for rel,value in receipt['frozen_inputs_unchanged'].items()))
    for name in ['coverage_by_team.png','entry_error_by_clock.png','error_by_state.png']:
        assert (OUT/name).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    check('All three standalone figures exist and have PNG signatures')
    check('Brief and technical report preserve exploratory interpretation',all((HERE/name).exists() for name in ['MEETING_BRIEF.md','MEETING_DIAGNOSTICS.md']) and 'exploratory' in (HERE/'MEETING_BRIEF.md').read_text(encoding='utf-8').lower())
    if args.live:
        for f in sorted(OUT.iterdir()):
            if f.suffix not in ['.csv','.png','.json'] or f.name in ['final_verification.json','development_verification.json']:continue
            b=urllib.request.urlopen('https://kevinyamada.github.io/wnba-shot-atlas/research/results/data1/meeting/'+f.name+'?verify='+str(time.time_ns()),timeout=30).read()
            assert (b==f.read_bytes() if f.suffix=='.png' else b.replace(b'\r\n',b'\n')==f.read_bytes().replace(b'\r\n',b'\n')),f.name
        check('All published meeting tables, figures and receipts match checked outputs')
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip();remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],cwd=HERE.parent,text=True).split()[0]
        check('Checked analysis commit matches GitHub main',head==remote)
    result={'all_checks_pass':True,'checks':checks,'archive_sha256':receipt['archive_sha256'],'only_data_source':'Data (1).zip','compute':'desktop CPU only',
        'analysis_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip(),'stage':'final after publication' if args.live else 'development',
        'completed_utc':pd.Timestamp.now(tz='UTC').isoformat()}
    (OUT/('final_verification.json' if args.live else 'development_verification.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('MEETING_FINAL_CHECKS_PASS',len(checks),flush=True)


if __name__=='__main__':main()
