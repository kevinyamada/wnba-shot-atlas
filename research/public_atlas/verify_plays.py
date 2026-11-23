"""Independently check controls, rewards, historical sources, forecast errors and public totals."""
import json
from collections import defaultdict

import numpy as np
import pandas as pd

from benchmark import paired_games
from build import DERIVED, RESULTS, SITE, ZONES, write_json
from fetch import YEARS, digest, manifest_digest
from league_turns import INPUT, OUT
from play_sources import DIRECTORY, MANIFEST, main as check_pins
from play_value import FIT_END, PRIOR, MODELS


def equal(actual,expected):
    np.testing.assert_allclose(actual,expected,rtol=1e-9,atol=1e-11)


def source_stats(data):
    primary=pd.read_csv(RESULTS/'season_coverage.csv')
    included=pd.read_csv(OUT/'shot_sources.csv')
    included=included[included.scope.isin(['regular','playoffs'])]
    fields=['attempts','makes','points','mapped']
    sx=primary.set_index(['season','phase']).sort_index()
    dx=included.set_index(['season','scope']).sort_index()
    assert list(sx.index)==list(dx.index)
    equal(sx[fields],dx[fields])
    for band in data['sources']['bands']:
        rows=included[included.season.between(band['start'],band['end'])]
        assert rows.provider.eq(band['source']).all() and rows.attempts.sum()==band['attempts']
    assert sum(r['attempts'] for r in data['sources']['bands'])==primary.attempts.sum()==data['sources']['regularPlayoffs']
    assert data['sources']['recentRegularPlayoffs']+data['sources']['recentSpecial']==data['sources']['recentAllRecorded']
    assert np.array_equal(sx.index.get_level_values(0).unique(),YEARS)


def point_surface(data):
    cols=['split','source_row','game_id','made','points','Pr(2) Joint boosted','Pr(3) Joint boosted']
    p=pd.read_csv(DERIVED/'shot_predictions.csv.gz',usecols=cols)
    p=p[p.split.isin(['test','playoffs'])].copy()
    z=pd.read_csv(DERIVED/'shots_2026.csv.gz',usecols=['game_id','source_row','zone','scope','points','made'])
    f=p.merge(z,on=['game_id','source_row','made','points'],validate='one_to_one')
    assert len(f)==len(p)
    for r in data['shotValue']:
        phase=f if r['scope']=='both' else f[f.scope.eq(r['scope'])]
        v=phase[phase.zone.eq(ZONES.index(r['area']))]
        assert (len(v),v.made.sum(),v.points.sum())==(r['attempts'],r['makes'],r['points'])
        equal([len(v)/len(phase),v.points.mean()],[r['share'],r['observed']])
        # The previous benchmark stores its component probabilities as decimal float32 values.
        np.testing.assert_allclose((2*v['Pr(2) Joint boosted']+3*v['Pr(3) Joint boosted']).mean(),
                                   r['expected'],rtol=0,atol=1e-7)


def check_season(y,summary):
    names=['states','shots','misses','boards','turns']
    saved={name:pd.read_csv(INPUT/f'{name}_{y}.csv.gz') for name in names}
    audit=pd.read_csv(OUT/'event_game_checks.csv').query('season==@y').set_index('game_id')
    schedule=pd.read_csv(DIRECTORY/f'wnba_schedule_{y}.csv.gz').set_index('game_id')
    games=schedule.index.astype(str).str[2].isin(['2','4'])
    assert set(schedule[games].index)==set(audit.index)
    eligible=audit[audit.turns.gt(0)].index
    fields=['game_id','period','order_index','team_id','person_id','is_field_goal','action_type','sub_type','description',
            'shot_result','shot_value','seconds_remaining','score_home','score_away']
    raw=pd.read_csv(DIRECTORY/f'wnba_play_by_play_{y}.csv.gz',usecols=fields,low_memory=False)
    raw=raw[raw.game_id.isin(eligible)].sort_values(['game_id','order_index']).copy()
    assert not raw.duplicated(['game_id','order_index']).any()
    ids=['game_id','period','turn']
    turns=saved['turns']
    assert not turns.duplicated(ids).any()
    assert turns.end_order.ge(turns.turn).all()
    raw['home']=raw.game_id.map(schedule.home_team_id)
    raw['away']=raw.game_id.map(schedule.away_team_id)
    raw['kind']=raw.action_type.fillna('').str.lower()
    fg=raw.is_field_goal.eq(1)
    ft=raw.kind.eq('free throw')
    # Official scoring snapshots carry positive running scores on credited free throws;
    # historical non-scoring rows use blanks or pairs of zeros.
    ft_made=ft & (raw.score_home.fillna(0)+raw.score_away.fillna(0)).gt(0) & ~raw.description.fillna('').str.match(r'(?i)^\s*miss\b')
    raw['reward']=np.where(fg & raw.shot_result.eq('Made'),raw.shot_value,np.where(ft_made,1,0))
    raw['h_pts']=raw.reward.where(raw.team_id.eq(raw.home),0).groupby(raw.game_id).cumsum()
    raw['a_pts']=raw.reward.where(raw.team_id.eq(raw.away),0).groupby(raw.game_id).cumsum()
    final=raw.groupby('game_id')[['h_pts','a_pts']].last()
    equal(final,schedule.loc[final.index,['home_pts','away_pts']])
    ix=raw.set_index(['game_id','order_index'])
    def lookup(df,name):
        return ix.reindex(pd.MultiIndex.from_arrays([df.game_id,df[name]]))
    def tally(df,name):
        src=lookup(df,name)
        assert src.period.notna().all()
        return np.where(df.team.to_numpy()==src.home.to_numpy(),src.h_pts.to_numpy(),src.a_pts.to_numpy())
    begin=tally(turns,'turn')
    end=tally(turns,'end_order')
    equal(end-begin,turns.points)
    turns=turns.assign(end_points=end)
    for name in ('states','misses','boards'):
        v=saved[name].merge(turns[ids+['team','end_order','end_points']],on=ids,validate='many_to_one')
        assert len(v)==len(saved[name]) and v.order.between(v.turn,v.end_order).all()
        equal(v.end_points-tally(v,'order'),v.remaining)
    shots=saved['shots'].merge(turns[ids+['team','end_order']],on=ids,validate='many_to_one')
    assert len(shots)==len(saved['shots']) and shots.order.gt(shots.turn).all() and shots.order.le(shots.end_order).all()
    s=lookup(shots,'order')
    assert s.is_field_goal.eq(1).all()
    equal(s.team_id,shots.team)
    equal(s.reward,shots.points)
    assert not shots.duplicated(['game_id','order']).any()
    m=saved['misses']
    miss_keys=set(zip(m.game_id,m.order))
    assert miss_keys==set(zip(shots.loc[shots.points.eq(0),'game_id'],shots.loc[shots.points.eq(0),'order']))
    decisive=raw[fg | ft | raw.kind.isin(['rebound','turnover','jump ball','violation'])
                 | (raw.kind.eq('period') & raw.sub_type.str.lower().eq('end'))].copy()
    decisive['effective_team']=decisive.team_id.where(decisive.team_id.isin(set(schedule.home_team_id)|set(schedule.away_team_id)),decisive.person_id)
    following=decisive.groupby(['game_id','period'])[['kind','effective_team','order_index']].shift(-1)
    lookup_next=following.set_index(pd.MultiIndex.from_arrays([decisive.game_id,decisive.order_index]))
    nxt=lookup_next.reindex(pd.MultiIndex.from_arrays([m.game_id,m.order]))
    own=lookup(m,'order').team_id.to_numpy()
    is_board=nxt.kind.eq('rebound').to_numpy() & (nxt.effective_team.to_numpy()==own)
    assert np.array_equal(is_board,m.off_rebound.to_numpy())
    s=saved['states']
    assert not s.duplicated(ids+['order']).any()
    # Recover the very next substantive event using raw source positions, independently of the turn parser.
    decisions=s.merge(turns[ids+['team','end_order']],on=ids,validate='many_to_one')
    live=raw.loc[fg | ft | raw.kind.isin(['rebound','turnover','foul']) |
                 (raw.kind.eq('period') & raw.sub_type.str.lower().eq('end'))].copy()
    assert raw.order_index.between(0,99999).all()
    key=live.game_id.to_numpy(dtype='int64')*100000+live.order_index.to_numpy(dtype='int64')
    decision_key=decisions.game_id.to_numpy(dtype='int64')*100000+decisions.order.to_numpy(dtype='int64')
    at=np.searchsorted(key,decision_key,side='right')
    source_clock=lookup(decisions,'order').seconds_remaining.to_numpy()
    kind=live.kind.to_numpy()
    clock=live.seconds_remaining.to_numpy()
    # A foul at exactly the time of an opponent make belongs to that scoring sequence.
    while True:
        skip=decisions.situation.eq('Opponent basket').to_numpy() & (kind[at]=='foul') & (clock[at]==source_clock)
        if not skip.any():
            break
        at[skip]+=1
    assert np.array_equal(live.game_id.to_numpy()[at],decisions.game_id.to_numpy())
    assert np.array_equal(live.period.to_numpy()[at],decisions.period.to_numpy())
    effective=np.where(live.team_id.isin(set(schedule.home_team_id)|set(schedule.away_team_id)),live.team_id,live.person_id)
    labels=np.select([live.is_field_goal.to_numpy()[at]==1,kind[at]=='foul',kind[at]=='free throw',kind[at]=='turnover',
                      kind[at]=='period',(kind[at]=='rebound')&(effective[at]==decisions.team.to_numpy())],
                     ['Field goal attempt','Foul','Free throw','Turnover','Period end','Offensive rebound'],'Defensive rebound')
    assert np.array_equal(labels,decisions.next_action.to_numpy()), (y,decisions.loc[labels!=decisions.next_action,['game_id','order','next_action']].head().to_dict('records'))
    # Check ordered prefixes against raw plays before the shot, including rare histories with ten actions.
    all_key=raw.game_id.to_numpy(dtype='int64')*100000+raw.order_index.to_numpy(dtype='int64')
    candidate=pd.concat([shots.sample(min(125,len(shots)),random_state=y),
        shots[shots.history_length.ge(10)].head(100)]).drop_duplicates(['game_id','order'])
    anchors=s.sort_values('order').drop_duplicates(ids).set_index(ids).situation
    for r in candidate.itertuples():
        anchor=anchors.loc[(r.game_id,r.period,r.turn)]
        trace=[anchor]
        begin=np.searchsorted(all_key,r.game_id*100000+r.turn,side='right')
        stop=np.searchsorted(all_key,r.game_id*100000+r.order)
        for event in raw.iloc[begin:stop].itertuples():
            if event.is_field_goal==1:
                trace.append('Made shot' if event.reward else 'Missed shot')
            elif event.kind=='free throw':
                trace.append('Made free throw' if event.reward else 'Missed free throw')
            elif event.kind=='foul':
                trace.append('Foul')
            elif event.kind=='rebound' and r.team in (event.team_id,event.person_id):
                trace.append('Offensive rebound')
        earlier=iter(trace)
        assert all(any(event==label for event in earlier) for label in r.history.split('|')), (y,r.game_id,r.order,r.history,trace)
    for df in [shots,s]:
        collected=df.history.str.count(r'\|')+1
        equal(collected,df.history_length.clip(upper=10))
    for r in summary:
        if r['season']==y:
            phase=audit[audit.scope.eq(r['scope'])]
            assert len(phase)==r['scheduled_games'] and phase.status.eq('score matches').sum()==r['score_checked']
            for name,public in [('states','decisions'),('shots','shots'),('misses','misses'),('boards','boards'),('turns','turns')]:
                assert saved[name].scope.eq(r['scope']).sum()==r[public]
    return saved


def check_models(data,states):
    p=pd.read_csv(DERIVED/'league_sequence_predictions.csv.gz')
    keys=['season','scope','game_id','period','turn','order','history','situation','next_action','remaining']
    expected=states[states.season.gt(FIT_END)][keys].merge(p,on=keys,validate='one_to_one')
    assert len(expected)==len(p)==states.season.gt(FIT_END).sum()
    equal(p.will_shoot,p.next_action.eq('Field goal attempt'))
    equal(p.will_score,p.remaining.gt(0))
    train=states[states.season.le(FIT_END)].assign(target=lambda f:f.next_action.eq('Field goal attempt').astype(int))
    blocks=train.groupby('history').agg(n=('target','size'),shots=('target','sum'),pts=('remaining','sum'),scores=('remaining',lambda x:x.gt(0).sum()))
    accum=defaultdict(lambda:np.zeros(4))
    for key,r in blocks.iterrows():
        seq=tuple(key.split('|'))
        for k in range(1,len(seq)+1):
            accum[seq[-k:]]+=r[['n','shots','pts','scores']].to_numpy(dtype=float)
    root=np.array([train.target.mean(),train.remaining.mean(),train.remaining.gt(0).mean()])
    for h,g in p.groupby('history'):
        sequence=tuple(h.split('|'))
        posterior=root.copy()
        for depth in range(0,len(sequence)+1):
            if depth:
                counts=accum.get(sequence[-depth:])
                if counts is not None:
                    posterior=(counts[1:]+PRIOR*posterior)/(counts[0]+PRIOR)
            for check in ([0] if depth==0 else [])+([1] if depth==1 else [])+([10] if depth==len(sequence) else []):
                equal(g[f'shot{check}'],posterior[0])
                equal(g[f'points{check}'],posterior[1])
                equal(g[f'score{check}'],posterior[2])
    for row in data['scores']:
        g=p[p.season.eq(row['season'])&p.scope.eq(row['scope'])]
        depth=(0,1,10)[MODELS.index(row['model'])]
        ref=1 if depth==10 else 0
        assert len(g)==row['states'] and g.game_id.nunique()==row['games']
        s=(g[f'shot{depth}']-g.will_shoot)**2
        t=(g[f'points{depth}']-g.remaining)**2
        threat=(g[f'score{depth}']-g.will_score)**2
        equal([s.mean(),np.sqrt(t.mean()),threat.mean()],[row['brier'],row['rmse'],row['score_brier']])
        for metric,delta in [('brier',s-(g[f'shot{ref}']-g.will_shoot)**2),('mse',t-(g[f'points{ref}']-g.remaining)**2),('score',threat-(g[f'score{ref}']-g.will_score)**2)]:
            interval=paired_games(g.game_id,delta)
            equal([interval[k] for k in ['difference','lower','upper']],[row[metric+s] for s in ['_difference','_low','_high']])
    for row in data['forecasts']:
        g=p[p.history.eq('|'.join(row['events']))]
        assert len(g)==row['states']
        equal([g.shot10.mean(),g.points10.mean(),g.will_shoot.mean(),g.remaining.mean(),g.score10.mean(),g.will_score.mean()],
              [row['predShot'],row['predPoints'],row['actualShot'],row['actualPoints'],row['predScore'],row['actualScore']])
    return len(p)


def main():
    check_pins()
    data=json.loads((SITE/'plays.json').read_bytes())
    assert (data['manifestSha256'],data['playManifestSha256'])==(manifest_digest(),digest(MANIFEST.read_text(encoding='utf-8').encode()))
    source_stats(data)
    point_surface(data)
    states,misses,boards,shots=[],[],[],[]
    for year in YEARS:
        s=check_season(year,data['coverage'])
        states.append(s['states'])
        misses.append(s['misses'])
        boards.append(s['boards'])
        shots.append(s['shots'][['history','history_length','points']])
        print('EVENT_LEDGER_VERIFIED',year,flush=True)
    states,misses,boards,shots=map(pd.concat,[states,misses,boards,shots])
    for r in data['misses']:
        m=misses if r['scope']=='both' else misses[misses.scope.eq(r['scope'])]
        b=boards if r['scope']=='both' else boards[boards.scope.eq(r['scope'])]
        assert [b.remaining.sum(),len(b),m.game_id.nunique()]==[r['board_points'],r['board_n'],r['games']]
        for item in r['flow']:
            g=m[m.off_rebound.eq(item['rebound'])]
            assert [len(g),g.remaining.sum(),g.remaining.gt(0).sum()]==[item['misses'],item['later_points'],item['scored_after']]
    for r in data['situations']:
        g=states[states.situation.eq(r['situation'])]
        assert [len(g),g.next_action.eq('Field goal attempt').sum(),g.remaining.sum(),g.remaining.gt(0).sum()]==[r[k] for k in ['states','next_shots','points','scoring_turns']]
    for r in data['nextActions']:
        assert ((states.situation==r['situation'])&(states.next_action==r['next_action'])).sum()==r['states']
    for group in data['histories']:
        subset=shots[shots.history_length.clip(upper=10).eq(group['length'])]
        assert len(subset)==group['attempts']
        for r in group['sequences']:
            g=subset[subset.history.eq('|'.join(r['events']))]
            assert [len(g),g.points.sum(),g.points.gt(0).sum()]==[r['attempts'],r['points'],r['makes']]
    n=check_models(data,states)
    record=dict(seasons=len(YEARS),pinnedLeagueFiles=2*len(YEARS),decisionStates=len(states),
        verifiedAttempts=len(shots),verifiedMisses=len(misses),verifiedBoards=len(boards),
        heldOutPredictions=n,manifestSha256=data['playManifestSha256'])
    write_json(OUT/'verification.json',record)
    print('PLAY_STUDY_VERIFIED',record,flush=True)


if __name__=='__main__':
    main()
