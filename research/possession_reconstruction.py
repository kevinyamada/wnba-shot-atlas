"""Conservative statistical control episodes from the supplied archive only.

This is a source-audited prototype, not an official possession feed or spatial
xT. Rewards are recorded scoring values, never unreliable scoreboard deltas.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import re
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1/possession'
PRIVATE=HERE/'data/data1/possession'
FT={97:(1,1),98:(1,2),99:(2,2),100:(1,3),101:(2,3),102:(3,3)}
SPECIAL_FT={103,104,105,106,107,108,157,165,166}
SPECIAL_FOUL={22,25,28,29,30,31,32,35,36,37,40,47,257}
TURNOVERS=set(range(62,73))|{74,75,76,78,84,86,87,88,89,90}
ADMIN={0,8,10,12,15,16,19,22,24,25,28,29,30,31,32,35,36,37,40,42,43,44,45,47,61,213,214,215,216,257,278,279,280,517,584}
SPECIAL_GAMES={401781604,401736430}
FEATURES=['period_number','seconds_remaining','elapsed_seconds','home','score_margin','points_so_far',
          'fga_so_far','fta_so_far','offensive_rebounds_so_far','stage','start_reason','offense_team_id','defense_team_id']


def seconds(clock):
    a,b=str(clock).split(':');return 60*float(a)+float(b)


class Reconstructor:
    def __init__(self):
        self.episodes=[];self.states=[];self.ledger=[];self.periods=[];self.counter=0

    def game(self,frame):
        records=frame.sort_values('game_play_number',kind='stable').to_dict('records')
        first=records[0];gid=int(first['game_id']);home=int(first['home_team_id']);away=int(first['away_team_id'])
        pair={home:away,away:home};scores={home:0,away:0};last_board=(0,0)
        cumulative={home:0,away:0}
        for r in records:
            r['_seconds']=seconds(r['clock_display_value'])
            t=r['team_id'];r['_team']=int(t) if pd.notna(t) else None
            r['_type']=int(r['type_id']);r['_points']=int(r['score_value'])
            assert r['_points']>=0
            r['_fga']=bool(r['shooting_play']) and 'free throw' not in str(r['type_text']).lower()
            delta=int(r['home_score'])+int(r['away_score'])-sum(last_board)
            r['_board_conflict']=delta!=r['_points']
            if r['_team'] in cumulative:cumulative[r['_team']]+=r['_points']
            r['_cumulative_conflict']=cumulative[home]!=int(r['home_score']) or cumulative[away]!=int(r['away_score'])
            last_board=(int(r['home_score']),int(r['away_score']))
        by_period=defaultdict(list)
        for r in records:by_period[int(r['period_number'])].append(r)
        for period,rows in sorted(by_period.items()):
            duration=600 if period<=4 else 300
            flags=set()
            if any(r['_board_conflict'] for r in rows):flags.add('score_snapshot_conflict')
            if any(r['_cumulative_conflict'] for r in rows):flags.add('cumulative_score_conflict')
            if any(r['_type'] in SPECIAL_FT|SPECIAL_FOUL for r in rows):flags.add('special_free_throw_or_foul')
            if any(r['_type'] in {215,279} for r in rows):flags.add('overturned_review')
            if any(r['_type']==615 and not r.get('jump_winner_validated',False) for r in rows):flags.add('unvalidated_jump_winner')
            if any(r['_seconds']<0 or r['_seconds']>duration for r in rows):flags.add('invalid_clock')
            if any(b['_seconds']>a['_seconds'] for a,b in zip(rows,rows[1:])):flags.add('clock_reversal')
            if not any(r['_type'] in {402,412} for r in rows):flags.add('missing_period_end')
            self.periods.append({'game_id':gid,'period_number':period,'rows':len(rows),'flags':'|'.join(sorted(flags)),
                                 'score_snapshot_conflicts':sum(r['_board_conflict'] for r in rows),
                                 'cumulative_score_conflicts':sum(r['_cumulative_conflict'] for r in rows),
                                 'scope':'special' if gid in SPECIAL_GAMES else 'playoffs' if int(first['season_type'])==3 else 'regular'})
            current=None;pending_make=None
            def boundary(team,reason,sec,row,anchor=True):
                return {'team':team,'reason':reason,'seconds':sec,'row':int(row),'scores':scores.copy(),'anchor':anchor}
            pending=boundary(None,'period_start',duration,rows[0]['source_row'],False)
            def snapshot(stage,r=None):
                if current is None:return
                sec=current['start_seconds'] if r is None else r['_seconds']
                score=current['_start_scores'] if r is None else scores
                earned=current['points']
                source=current['start_source_row'] if r is None else int(r['source_row'])
                self.states.append({'state_id':f"{current['episode_id']}:{len(current['_states'])}",
                    'episode_id':current['episode_id'],'source_row':source,'game_id':gid,'date':current['date'],'scope':current['scope'],'split':current['split'],
                    'period_number':period,'seconds_remaining':sec,'elapsed_seconds':max(0,current['start_seconds']-sec),
                    'home':int(current['offense_team_id']==home),'score_margin':score[current['offense_team_id']]-score[current['defense_team_id']],
                    'points_so_far':earned,'fga_so_far':current['fga'],'fta_so_far':current['fta'],
                    'offensive_rebounds_so_far':current['offensive_rebounds'],'stage':stage,'start_reason':current['start_reason'],
                    'offense_team_id':str(current['offense_team_id']),'defense_team_id':str(current['defense_team_id'])})
                current['_states'].append(len(self.states)-1)
            def start(team,b):
                nonlocal current,pending_make
                assert team in pair
                self.counter+=1;date=str(first['game_date'])[:10]
                scope='special' if gid in SPECIAL_GAMES else 'playoffs' if int(first['season_type'])==3 else 'regular'
                split='playoffs' if scope=='playoffs' else 'special' if scope=='special' else 'train' if date<'2025-08-10' else 'validation' if date<'2025-08-27' else 'test'
                current={'episode_id':f'{gid}-{period}-{self.counter}','game_id':gid,'date':date,'scope':scope,'split':split,
                         'period_number':period,'offense_team_id':team,'defense_team_id':pair[team],
                         'start_seconds':b['seconds'],'start_source_row':b['row'],'start_reason':b['reason'],
                         'start_anchored':bool(b['anchor']),'points':0,'fga':0,'fgm':0,'fta':0,'ftm':0,'turnovers':0,'offensive_rebounds':0,
                         '_flags':set(),'_states':[],'_start_scores':b['scores'].copy(),'_ft_next':0,'_ft_total':0}
                if not b['anchor']:current['_flags'].add('unanchored_start')
                pending_make=None;snapshot('entry')
            def close(reason,sec,row):
                nonlocal current,pending_make
                if current is None:return
                current['end_seconds']=sec;current['end_source_row']=int(row);current['end_reason']=reason
                current['duration_seconds']=current['start_seconds']-sec
                if current['duration_seconds']<0:current['_flags'].add('negative_duration')
                if current['_ft_next']:current['_flags'].add('incomplete_free_throw_series')
                ep_flags=current['_flags']|flags
                current['flags']='|'.join(sorted(ep_flags));current['eligible']=not ep_flags and current['scope']!='special'
                for index in current['_states']:
                    s=self.states[index];s['remaining_points']=current['points']-s['points_so_far'];s['episode_points']=current['points']
                    assert s['remaining_points']>=0
                    s['eligible']=bool(current['eligible'] and s['seconds_remaining']>2)
                    s['quality_flags']=current['flags']
                self.episodes.append({k:v for k,v in current.items() if not k.startswith('_')})
                current=None;pending_make=None
            def ensure(team,r):
                nonlocal pending
                if current is None:
                    if pending['team'] not in [None,team]:
                        pending=boundary(team,'unobserved_transfer',r['_seconds'],r['source_row'],False)
                    start(team,pending)
                elif current['offense_team_id']!=team:
                    current['_flags'].add('unobserved_transfer')
                    close('unobserved_transfer',r['_seconds'],r['source_row'])
                    start(team,boundary(team,'unobserved_transfer',r['_seconds'],r['source_row'],False))
            def finish_and_transfer(reason,r,at=None):
                nonlocal pending
                team=current['offense_team_id'];sec=r['_seconds'] if at is None else at['seconds'];row=r['source_row'] if at is None else at['row']
                saved=boundary(pair[team],reason,sec,row,True)
                if at is not None:saved['scores']=at['scores'].copy()
                close(reason,sec,row);pending=saved;start(saved['team'],saved)
            for r in rows:
                tid=r['_type'];team=r['_team'];sec=r['_seconds'];value=r['_points'];lane='none';assignment=None
                normal_ft=tid in FT
                if pending_make is not None:
                    and_one=normal_ft and FT[tid]==(1,1) and team==current['offense_team_id'] and sec==pending_make['seconds']
                    same_clock_admin=sec==pending_make['seconds'] and tid in ADMIN
                    if and_one:pending_make=None
                    elif not same_clock_admin:
                        old=pending_make.copy();finish_and_transfer('made_field_goal',r,old)
                if tid in SPECIAL_FT:
                    lane='special_free_throw'
                    if current is not None:assignment=current['episode_id']
                    assert team in pair or value==0
                    if team in scores:scores[team]+=value
                elif r['_fga']:
                    assert team in pair;ensure(team,r);assignment=current['episode_id'];lane='ordinary'
                    current['points']+=value;current['fga']+=1;current['fgm']+=int(value>0);scores[team]+=value
                    assert value in [0,2,3]
                    if value==0:snapshot('after_miss',r)
                    else:pending_make={'seconds':sec,'row':r['source_row'],'scores':scores.copy()}
                elif normal_ft:
                    assert team in pair;ensure(team,r);assignment=current['episode_id'];lane='ordinary'
                    number,total=FT[tid]
                    if number>1 and (current['_ft_next']!=number or current['_ft_total']!=total):current['_flags'].add('incomplete_free_throw_series')
                    if number==1 and current['_ft_next']:current['_flags'].add('overlapping_free_throw_series')
                    current['_ft_next']=number+1 if number<total else 0;current['_ft_total']=total
                    current['points']+=value;current['fta']+=1;current['ftm']+=int(value>0);scores[team]+=value
                    assert value in [0,1]
                    if number==total and value>0:finish_and_transfer('made_free_throw',r)
                elif tid==155 and team in pair:
                    if current is not None and current['_ft_next']:
                        current['_flags'].add('defensive_rebound_before_ft_series_end');assignment=current['episode_id']
                    else:
                        if current is not None:
                            if current['offense_team_id']==team:current['_flags'].add('defensive_rebound_same_owner')
                            close('defensive_rebound',sec,r['source_row'])
                        pending=boundary(team,'defensive_rebound',sec,r['source_row'],True);start(team,pending);assignment=current['episode_id']
                elif tid==156 and team in pair:
                    if current is not None and current['_ft_next']:
                        assignment=current['episode_id'];lane='dead_ball_rebound'
                        if current['offense_team_id']!=team:current['_flags'].add('dead_ball_rebound_other_team')
                    else:
                        ensure(team,r);assignment=current['episode_id'];current['offensive_rebounds']+=1;snapshot('after_offensive_rebound',r)
                elif (tid in TURNOVERS or (tid==11 and 'violation' in str(r['text']).lower())) and team in pair:
                    ensure(team,r);assignment=current['episode_id'];current['turnovers']+=1;finish_and_transfer('turnover',r)
                elif tid==615 and team in pair:
                    if current is None or current['offense_team_id']!=team:
                        if current is not None:close('jump_ball',sec,r['source_row'])
                        pending=boundary(team,'jump_ball',sec,r['source_row'],True);start(team,pending)
                    assignment=current['episode_id']
                elif tid in {402,412}:
                    if current is not None:assignment=current['episode_id'];close('period_end',sec,r['source_row'])
                else:
                    if current is not None:assignment=current['episode_id']
                    assert value==0,('unclassified scoring event',gid,r['source_row'],tid,value)
                self.ledger.append({'source_row':int(r['source_row']),'game_id':gid,'period_number':period,'team_id':team,
                                    'type_id':tid,'points':value,'reward_lane':lane,'episode_id':assignment})
            if current is not None:
                if pending_make is not None:
                    old=pending_make.copy();finish_and_transfer('made_field_goal',rows[-1],old)
                if current is not None:close('period_end',0,rows[-1]['source_row'])
        return scores


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    expected=json.loads((HERE/'results/data1/source_audit.json').read_text(encoding='utf-8'))
    h=hashlib.sha256()
    with args.source.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    assert args.source.name=='Data (1).zip' and h.hexdigest()==expected['archive_sha256']
    with zipfile.ZipFile(args.source) as z:
        def read(suffix):return pd.read_csv(z.open(next(n for n in z.namelist() if n.endswith(suffix))),low_memory=False)
        events=read('/original/wehoop_wnba_pbp.csv');teams=read('/WNBA_Team/wnba_team_box.csv');players=read('/WNBA_player/wnba_player_box.csv')
    events['source_row']=np.arange(len(events))+2
    p=players[players.season.eq(2025)]
    by_id={(int(r.game_id),int(r.athlete_id)):int(r.team_id) for r in p.itertuples()}
    by_name=defaultdict(set)
    for r in p.itertuples():by_name[int(r.game_id),r.athlete_display_name].add(int(r.team_id))
    roles=[];validated={}
    for r in events[events.type_id.eq(615)].itertuples():
        match=re.search(r'\((.*?) gains possession\)',str(r.text));name=match.group(1) if match else None
        candidates=by_name.get((int(r.game_id),name),set());name_team=next(iter(candidates)) if len(candidates)==1 else None
        id_team=by_id.get((int(r.game_id),int(r.athlete_id_3))) if pd.notna(r.athlete_id_3) else None
        team=int(r.team_id) if pd.notna(r.team_id) else None
        evidence=[v for v in [name_team,id_team] if v is not None]
        ok=bool(evidence) and all(v==team for v in evidence)
        validated[r.source_row]=ok
        roles.append({'source_row':r.source_row,'game_id':r.game_id,'team_id':team,'winner_name_team':name_team,'third_actor_team':id_team,'validated':ok})
    events['jump_winner_validated']=events.source_row.map(validated).fillna(False).astype(bool)
    pd.DataFrame(roles).to_csv(OUT/'jump_ball_role_audit.csv',index=False)
    builder=Reconstructor();score_rows=[]
    for gid,g in events.groupby('game_id',sort=True):
        scores=builder.game(g)
        for team,points in scores.items():score_rows.append({'game_id':gid,'team_id':team,'reconstructed_points':points})
    ledger=pd.DataFrame(builder.ledger);episodes=pd.DataFrame(builder.episodes);states=pd.DataFrame(builder.states);periods=pd.DataFrame(builder.periods)
    assert len(ledger)==len(events) and not ledger.source_row.duplicated().any()
    checks=pd.DataFrame(score_rows).merge(teams[teams.season.eq(2025)][['game_id','team_id','team_score']],on=['game_id','team_id'],how='outer',validate='one_to_one')
    checks['difference']=checks.reconstructed_points-checks.team_score
    assert len(checks)==624 and checks.difference.eq(0).all()
    checks.to_csv(OUT/'all_points_reconciliation.csv',index=False)
    ordinary=ledger[ledger.reward_lane.eq('ordinary')].groupby('episode_id').points.sum()
    assert episodes.set_index('episode_id').points.eq(ordinary.reindex(episodes.episode_id).fillna(0).to_numpy()).all()
    assert ledger.points.sum()==episodes.points.sum()+ledger.loc[ledger.reward_lane.eq('special_free_throw'),'points'].sum()
    states.to_csv(PRIVATE/'all_states.csv.gz',index=False);episodes.to_csv(PRIVATE/'all_episodes.csv.gz',index=False);ledger.to_csv(PRIVATE/'event_ledger.csv.gz',index=False)
    retained=states[states.eligible].copy();retained.to_csv(PRIVATE/'model_states.csv.gz',index=False)
    proof=retained.merge(events[['source_row','home_team_id','home_score','away_score']],on='source_row',validate='many_to_one')
    sign=np.where(proof.offense_team_id.astype(int).eq(proof.home_team_id),1,-1)
    assert np.array_equal(proof.score_margin.to_numpy(),sign*(proof.home_score-proof.away_score).to_numpy())
    periods.to_csv(OUT/'period_quality.csv',index=False)
    flags=Counter()
    for value in episodes['flags']:
        flags.update(str(value).split('|') if value else [])
    summary=episodes.groupby(['scope','split']).agg(episodes=('episode_id','size'),eligible_episodes=('eligible','sum'),ordinary_points=('points','sum'),mean_points=('points','mean'),max_points=('points','max')).reset_index()
    summary.to_csv(OUT/'episode_summary.csv',index=False)
    state_summary=retained.groupby(['split','stage']).agg(states=('state_id','size'),episodes=('episode_id','nunique'),games=('game_id','nunique'),mean_remaining_points=('remaining_points','mean')).reset_index()
    state_summary.to_csv(OUT/'state_summary.csv',index=False)
    entry=retained[retained.stage.eq('entry')]
    audit={'only_data_source':'Data (1).zip','archive_sha256':h.hexdigest(),'events':len(events),'games':int(events.game_id.nunique()),
           'all_624_team_scores_reconcile':True,'all_scoring_values_accounted_for_once':True,'ordinary_episode_points':int(episodes.points.sum()),
           'every_retained_state_margin_agrees_with_source_snapshot':True,
           'special_free_throw_points':int(ledger.loc[ledger.reward_lane.eq('special_free_throw'),'points'].sum()),
           'episodes':len(episodes),'periods':len(periods),'clean_periods':int(periods['flags'].eq('').sum()),
           'jump_ball_winner_rows':len(roles),'validated_jump_ball_winner_rows':sum(r['validated'] for r in roles),
           'eligible_states':len(retained),'eligible_entry_states':len(entry),'flag_counts':dict(flags),
           'cohorts':state_summary.to_dict('records'),'feature_allowlist':FEATURES,
           'exclusion_rule':'Whole periods with score-snapshot inconsistencies, special retention/technical/flagrant/take fouls or free throws, overturned reviews or clock problems; individual episodes with uncertain control or incomplete FT sequences. State clocks must exceed 2 seconds.',
           'target':'Remaining recorded ordinary points before the reconstructed control episode ends. Offensive rebounds continue the episode. Special free throws are audited separately.',
           'limitation':'No authoritative possession IDs are supplied. Reconciliation validates rewards and internal consistency, not every true possession boundary. No pass/movement locations are invented; this is event-based EPV, not full spatial xT.'}
    (OUT/'reconstruction_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print('RECONSTRUCTION_COMPLETE',json.dumps(audit,indent=2),flush=True)


if __name__=='__main__':main()
