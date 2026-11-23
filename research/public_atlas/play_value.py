"""Estimate the next recorded shot and remaining points from the last ten within-turn actions."""
from collections import defaultdict
import json

import numpy as np
import pandas as pd

from benchmark import paired_games
from build import DERIVED, RESULTS, SITE, ZONES, write_json
from fetch import YEARS, digest, manifest_digest
from league_turns import INPUT, OUT
from play_sources import MANIFEST

FIT_END=2024
PRIOR=40
MODELS=('League average','Last action','Up to ten actions')
SITS=('Steal','Opponent turnover','Defensive rebound','Opponent basket','Opponent free throw','Offensive rebound')


def rows(frame):
    return json.loads(frame.to_json(orient='records',double_precision=14))


def read_all(name):
    return pd.concat([pd.read_csv(INPUT/f'{name}_{y}.csv.gz') for y in YEARS],ignore_index=True)


def provenance():
    records=[]
    for y in YEARS:
        f=pd.read_csv(DERIVED/f'shots_{y}.csv.gz',usecols=['scope','made','points','cell'])
        for phase,grp in f.groupby('scope'):
            records.append(dict(season=y,provider='WNBA Stats' if y<=2001 else 'ESPN',scope=phase,
                attempts=len(grp),makes=int(grp.made.sum()),points=int(grp.points.sum()),mapped=int(grp.cell.ge(0).sum())))
    frame=pd.DataFrame(records)
    frame.to_csv(OUT/'shot_sources.csv',index=False)
    counted=frame[frame.scope.isin(['regular','playoffs'])]
    totals=[]
    for a,b in [(1997,2001),(2002,2010),(2011,2026)]:
        sub=counted[counted.season.between(a,b)]
        totals.append(dict(start=a,end=b,source=sub.provider.iloc[0],attempts=int(sub.attempts.sum())))
    latest=frame[frame.season.ge(2011)]
    return dict(bands=totals, regularPlayoffs=int(counted.attempts.sum()), recentRegularPlayoffs=totals[-1]['attempts'],
        recentSpecial=int(latest.loc[latest.scope.eq('special'),'attempts'].sum()),recentAllRecorded=int(latest.attempts.sum()))


def quality():
    name='points Joint boosted'
    pred=pd.read_csv(DERIVED/'shot_predictions.csv.gz',usecols=['season','game_id','source_row','split','made','points',name])
    pred=pred[pred.season.eq(2026)]
    coords=pd.read_csv(DERIVED/'shots_2026.csv.gz',usecols=['game_id','source_row','zone','scope'])
    x=pred.merge(coords,on=['game_id','source_row'],validate='one_to_one')
    assert len(x)==len(pred) and x.zone.between(0,4).all() and x[name].between(0,3).all()
    x['area']=x.zone.map(dict(enumerate(ZONES)))
    result=[]
    for phase,group in [('both',x),*x.groupby('scope')]:
        for area,g in group.groupby('area'):
            result.append(dict(scope=phase,area=area,attempts=len(g),makes=int(g.made.sum()),points=int(g.points.sum()),
                share=len(g)/len(group),expected=float(g[name].mean()),observed=g.points.mean()))
    pd.DataFrame(result).to_csv(OUT/'location_value.csv',index=False)
    return result


def fit(states):
    train=states[states.season.le(FIT_END)]
    grouped=train.groupby('history').agg(n=('will_shoot','size'),shots=('will_shoot','sum'),points=('remaining','sum'),scores=('will_score','sum'))
    total=grouped.sum()
    levels=[defaultdict(lambda: np.zeros(4)) for _ in range(11)]
    for path,values in grouped.iterrows():
        h=path.split('|')
        v=values[['n','shots','points','scores']].to_numpy(dtype=float)
        for depth in range(1,len(h)+1):
            levels[depth]['|'.join(h[-depth:])]+=v
    base=np.array([total.shots,total.points,total.scores])/total.n
    levels[0]['']=base
    for level in range(1,11):
        for key,(n,shots,points,scores) in list(levels[level].items()):
            previous=key.partition('|')[2]
            prior=levels[level-1][previous]
            levels[level][key]=(np.array([shots,points,scores])+PRIOR*prior)/(n+PRIOR)
    def predict(path,depth):
        labels=path.split('|')
        for k in range(min(depth,len(labels)),0,-1):
            v=levels[k].get('|'.join(labels[-k:]))
            if v is not None:
                return v
        return base
    return predict


def forecast(states):
    states['will_shoot']=states.next_action.eq('Field goal attempt').astype(int)
    states['will_score']=states.remaining.gt(0).astype(int)
    predict=fit(states)
    test=states[states.season.gt(FIT_END)].copy()
    assert set(test.season)=={2025,2026}
    assert not set(test.game_id)&set(states.loc[states.season.le(FIT_END),'game_id'])
    rates={}
    for depth in (0,1,10):
        rates[depth]={h:predict(h,depth) for h in test.history.unique()}
        for j,key in enumerate(['shot','points','score']):
            test[f'{key}{depth}']=test.history.map({h:v[j] for h,v in rates[depth].items()})
    test.to_csv(DERIVED/'league_sequence_predictions.csv.gz',index=False)
    scores=[]
    for (year,scope),g in test.groupby(['season','scope']):
        for depth,model in zip((0,1,10),MODELS):
            shot=(g[f'shot{depth}']-g.will_shoot)**2
            points=(g[f'points{depth}']-g.remaining)**2
            bas=1 if depth==10 else 0
            delta_shot=paired_games(g.game_id,shot-(g[f'shot{bas}']-g.will_shoot)**2)
            threat=(g[f'score{depth}']-g.will_score)**2
            delta_threat=paired_games(g.game_id,threat-(g[f'score{bas}']-g.will_score)**2)
            delta_points=paired_games(g.game_id,points-(g[f'points{bas}']-g.remaining)**2)
            scores.append(dict(season=year,scope=scope,model=model,states=len(g),games=g.game_id.nunique(),
                brier=shot.mean(),score_brier=threat.mean(),score_difference=delta_threat['difference'],
                score_low=delta_threat['lower'],score_high=delta_threat['upper'],rmse=np.sqrt(points.mean()),baseline=MODELS[1 if depth==10 else 0],
                brier_difference=delta_shot['difference'],brier_low=delta_shot['lower'],brier_high=delta_shot['upper'],
                mse_difference=delta_points['difference'],mse_low=delta_points['lower'],mse_high=delta_points['upper']))
    pd.DataFrame(scores).to_csv(OUT/'sequence_scores.csv',index=False)
    by_path=test.groupby('history').agg(states=('will_shoot','size'),actual_shot=('will_shoot','mean'),
        actual_points=('remaining','mean'),actual_score=('will_score','mean'),pred_score=('score10','first'),pred_shot=('shot10','first'),pred_points=('points10','first')).reset_index()
    by_path['depth']=by_path.history.str.count(r'\|')+1
    examples=[]
    for _,group in by_path.groupby('depth'):
        common=group.sort_values(['states','history'],ascending=[False,True]).iloc[0]
        examples.append(dict(events=common.history.split('|'),states=int(common.states),predShot=float(common.pred_shot),
            predPoints=float(common.pred_points),predScore=float(common.pred_score),actualScore=float(common.actual_score),actualShot=float(common.actual_shot),actualPoints=float(common.actual_points)))
    return rows(pd.DataFrame(scores)),examples


def pooled_misses(misses,boards,audit):
    combined=[]
    for scope in ('both','regular','playoffs'):
        m=misses if scope=='both' else misses[misses.scope.eq(scope)]
        b=boards if scope=='both' else boards[boards.scope.eq(scope)]
        a=audit if scope=='both' else audit[audit.scope.eq(scope)]
        usable=a[a.states.gt(0)]
        groups=[dict(rebound=bool(k),misses=len(v),later_points=int(v.remaining.sum()),scored_after=int(v.remaining.gt(0).sum()))
                for k,v in m.groupby('off_rebound')]
        combined.append(dict(scope=scope,flow=groups,board_n=len(b),board_points=int(b.remaining.sum()),
            seasons=sorted(int(y) for y in m.season.unique()),games=int(m.game_id.nunique()),qualifiedGames=len(usable),
            checkedGames=int(a.status.eq('score matches').sum()),scheduled=len(a)))
    return combined


def paths(shots):
    lengths=shots.history_length.clip(upper=10)
    blocks=[]
    for length,g in shots.groupby(lengths):
        counts=g.groupby('history').points.agg(attempts='size',makes=lambda v:v.gt(0).sum(),points='sum')
        most=counts.sort_values(['attempts','history'],ascending=[False,True]).head(3)
        blocks.append(dict(length=int(length),attempts=len(g),sequences=[dict(events=h.split('|'),attempts=int(r.attempts),
            makes=int(r.makes),points=int(r.points)) for h,r in most.iterrows()]))
    return blocks


def main():
    audit=pd.read_csv(OUT/'event_game_checks.csv')
    states,shots,misses,boards=[read_all(k) for k in ['states','shots','misses','boards']]
    scores,examples=forecast(states)
    situations=[]
    for (season,scope,sit),g in states.groupby(['season','scope','situation']):
        situations.append(dict(season=season,scope=scope,situation=sit,states=len(g),next_shots=int(g.will_shoot.sum()),
            points=int(g.remaining.sum()),scoring_turns=int(g.remaining.gt(0).sum())))
    pd.DataFrame(situations).to_csv(OUT/'situations_by_season.csv',index=False)
    weighted=pd.DataFrame(situations).groupby('situation')[['states','next_shots','points','scoring_turns']].sum().reset_index()
    next_counts=states.groupby(['situation','next_action']).size().rename('states').reset_index()
    next_counts.to_csv(OUT/'next_action.csv',index=False)
    coverage=audit.groupby(['season','scope']).agg(scheduled_games=('game_id','size'),score_checked=('status',lambda a:a.eq('score matches').sum()),
        retained_games=('turns',lambda a:a.gt(0).sum()),turns=('turns','sum'),decisions=('states','sum'),shots=('shots','sum'),
        misses=('misses','sum'),boards=('offensive_boards','sum')).reset_index()
    coverage.to_csv(OUT/'coverage.csv',index=False)
    partial=pooled_misses(misses,boards,audit)
    path_counts=paths(shots)
    miss_by=misses.groupby(['season','scope','off_rebound']).remaining.agg(misses='size',points='sum',scored_after=lambda a:a.gt(0).sum())
    miss_by.to_csv(OUT/'misses_by_season.csv')
    boards.groupby(['season','scope']).remaining.agg(boards='size',points='sum').to_csv(OUT/'boards_by_season.csv')
    data=dict(manifestSha256=manifest_digest(), playManifestSha256=digest(MANIFEST.read_text(encoding='utf-8').encode()),
        sources=provenance(),misses=partial,situations=rows(weighted),nextActions=rows(next_counts),scores=scores,forecasts=examples,
        histories=path_counts,shotValue=quality(),coverage=rows(coverage))
    write_json(SITE/'plays.json',data)
    write_report(data)
    print('PLAYS_EXPORTED',data['sources'],partial[0],rows(weighted),flush=True)


def write_report(data):
    pool=data['misses'][0]
    sit={r['situation']:r for r in data['situations']}
    total=sum(r['misses'] for r in pool['flow'])
    rebound=next(r for r in pool['flow'] if r['rebound'])
    rows_out=[
        '# WNBA play situations and expected points','',
        f"From 1997 through 2026, the WNBA Stats schedule lists {pool['scheduled']:,} regular season and playoff games. Both final scores and the recorded scoring snapshots passed the checks in {pool['checkedGames']:,}. Complete, traceable turns contributed misses in {pool['games']:,}.",
        '', '| How the team got the ball | Decision points | Shot on next event | Points to end of turn |',
        '| :--- | ---: | ---: | ---: |']
    for r in sorted(sit.values(),key=lambda s:s['points']/s['states'],reverse=True):
        rows_out.append(f"| {r['situation']} | {r['states']:,} | {r['next_shots']/r['states']:.1%} | {r['points']/r['states']:.3f} |")
    rows_out+=[
        '', f"Of {total:,} verified missed field goals, {rebound['misses']:,} ({rebound['misses']/total:.1%}) were followed by an offensive rebound. Across all retained offensive rebounds, teams then scored {pool['board_points']/pool['board_n']:.2f} more points on average.",
        '', '## What the forecasts measure','',
        'A decision is recorded when a team gains control after a defensive rebound, turnover, opponent basket or final made free throw, or regains control after an offensive rebound. The shot target is whether the next substantive recorded event is a field goal attempt. Its complement includes fouls, turnovers, free throws and period endings. Scoring threat is the probability of at least one more point before the turn ends. The points target is all subsequent ordinary points through the end of that team’s turn. Groups can overlap when an offensive rebound keeps the same turn alive. The data describe the situations in which teams got the ball. They cannot identify the effect of calling a specific play.',
        '',
        'Each sequence begins at a confirmed change of control. The model uses at most the last ten recorded actions already visible at the decision, in order. It fits through 2024. Both phases of 2025 and 2026 are scored on identical decision points for the league average, the last action model and the longer history model. Shot probability, scoring threat and expected points share the prior structure and use different outcomes. For a suffix seen n times, the posterior mean is the observed total plus 40 times its parent estimate, divided by n + 40. The parent drops the oldest action. Unseen suffixes take their parent’s estimate. For both binary outcomes this is a Beta prior. For points it is the mean of a distribution over turn rewards with a Dirichlet prior. The prior strength is fixed. Game resampling compares paired differences in Brier error and squared points error. These are historical tests in previously examined seasons.',
        '', '| 2026 games | History | Decision points | Shot Brier | Scoring threat Brier | Points RMSE |',
        '| :--- | :--- | ---: | ---: | ---: | ---: |']
    for r in data['scores']:
        if r['season']==2026:
            rows_out.append(f"| {r['scope']} | {r['model']} | {r['states']:,} | {r['brier']:.6f} | {r['score_brier']:.6f} | {r['rmse']:.4f} |")
    rows_out+=['', '## Location and movement','',
        'The shot map gives observed attempts, make rate and field goal points per attempt. The location forecast summarizes the joint model’s predicted probabilities of zero, two and three points across the actual attempts in each court area. Training uses 2022 to 2024 and model selection uses 2025. This is shot value given an attempt. The event model also includes situations that end without a shot.',
        '',
        'The expected goals idea from hockey carries over as two distinct questions. How likely is a shot to happen next? Once taken, how valuable is it? In basketball the possible field goal rewards are zero, two and three. The sequence model borrows information across related recorded histories when observations are scarce. All fitted observations and scores in this project come from the WNBA.',
        '',
        'The archive gives locations at shot attempts. It cannot show every successful pass, dribble, cut or defender position. The action display counts only events within a single turn. Shorter histories are shown at their actual length. In the ten or more group only the final ten events are shown. The gap in shot density immediately inside the three point line is consistent with an incentive to shoot a three. Release coordinates alone do not show whether the shooter deliberately stepped back.',
        '', '## Source accounting and exclusions','',
        'The shot explorer uses one provider per season. WNBA Stats supplies 120,948 attempts in 1997 through 2001. ESPN supplies 274,074 in 2002 through 2010 and 507,707 in 2011 through 2026. The recent release contains 511,169 field goal attempts before setting aside 3,462 from special games. The public explorer therefore has 902,729 regular season and playoff attempts. The separate league event files supply histories and a score check. They add zero attempts to that total.',
        '',
        'Event order comes from the published order index. The schedule must agree with both teams’ points and the running scoreboard on scoring rows where it is available. A period needs an end marker and an ordered, valid clock. Before 2006 the regulation clock uses two twenty minute halves. Later seasons use four ten minute quarters, with five minute overtime periods. Unresolved transfers, jumps, reviews that overturn a call, special free throws and unsupported live events discard open turns. Play can resume at the next confirmed change of control. Missed shots require an identifiable rebound to connect to another live attempt. Midseries dead ball rebounds do not create a second chance. The public miss dropdown preserves the earlier ESPN study samples under their own names. Its all seasons options use the WNBA Stats reconstruction.',
        '', '## Files and references','',
        '[Season coverage](coverage.csv) · [Each game and final score](event_game_checks.csv) · [Shot source counts](shot_sources.csv) · [Play situations](situations_by_season.csv) · [Misses](misses_by_season.csv) · [Rebounds](boards_by_season.csv) · [Location value](location_value.csv) · [Forecasts and intervals](sequence_scores.csv) · [Source manifest](../../../public_atlas/play_manifest.json)',
        '',
        '[WNBA Stats event documentation](https://github.com/sportsdataverse/wehoop-wnba-stats-data/blob/main/docs/datasets/pbp.md) · [Hockey shot quality and empirical Bayes](https://spectrum.library.concordia.ca/id/eprint/988845/) · [Basketball possession value with tracking](https://www.lukebornn.com/papers/cervone_ssac_2014.pdf)']
    (OUT/'README.md').write_text('\n'.join(rows_out)+'\n',encoding='utf-8',newline='')


if __name__=='__main__':
    main()
