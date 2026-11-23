"""Reconstruct ordinary WNBA turns from the pinned league event order and final game scores."""
from collections import Counter
import re

import pandas as pd

from build import DERIVED, RESULTS
from fetch import YEARS
from play_sources import DIRECTORY, main as restore_sources

OUT=RESULTS/'plays'
INPUT=DERIVED/'league_turns'
ORDINARY_FT=re.compile(r'\b([1-3])\s+of\s+([1-3])\b',re.I)
SPECIAL=re.compile(r'technical|flagrant|clear path|away from play|transition take|defen(?:se|sive) (?:3|three) second|punch|double personal|double foul|hostile',re.I)
ADMIN={'timeout','substitution','instant replay','instantreplay','stoppage','ejection','game','no shot'}
STATES=['season','game_id','scope','period','turn','anchor_order','order','situation','history','history_length','next_action','remaining']
SHOTS=['season','game_id','scope','period','turn','order','history','history_length','points']
MISSES=['season','game_id','scope','period','turn','order','off_rebound','remaining']
BOARDS=['season','game_id','scope','period','turn','order','remaining']


def classify(r):
    action=str(r.action_type).strip().lower()
    sub=str(r.sub_type).strip().lower()
    text=str(r.description)
    if r.is_field_goal==1 and r.shot_result in ('Made','Missed'):
        return ('basket',int(r.shot_value)) if r.shot_result=='Made' else ('miss',0)
    if action in ('nan',''):
        if re.search(r'\bsteal\b',text,re.I):
            return 'steal_credit',0
        if re.search(r'\b(?:block|assist)\b',text,re.I):
            return 'admin',0
    if action=='free throw':
        if pd.isna(r.description):
            return 'unknown',0
        make=int(not bool(re.match(r'^\s*miss(?:ed)?\b',text,re.I)))
        series=ORDINARY_FT.search(sub) or ORDINARY_FT.search(text)
        if SPECIAL.search(sub+' '+text) or not series:
            return 'special_ft',make
        i,n=map(int,series.groups())
        return ('last_ft' if i==n else 'early_ft'),make
    if action=='period':
        return ('end' if 'end' in sub else 'start'),0
    if action=='rebound':
        return 'rebound',0
    if action=='turnover':
        return 'turnover',0
    if action=='foul':
        return ('special' if SPECIAL.search(sub+' '+text) else 'foul'),0
    if action in {'violation','jump ball','jumpball'}:
        return 'reset',0
    if action in ADMIN:
        return ('reset' if ('overturn' in sub+' '+text.lower() or action=='ejection') else 'admin'),0
    return 'unknown',0


class Period:
    def __init__(self, year, game, scope, period, home, away):
        self.base=(year,game,scope,period)
        self.other={home:away,away:home}
        self.out=[[],[],[],[],[]]
        self.excluded=Counter()
        self.turn=None
        self.last_miss=None
        self.pending=None

    def start(self,team,reason,r):
        self.turn=dict(team=team, anchor=r.order_index, start_sec=r.seconds_remaining, history=[reason], points=0, states=[],
            shots=[],misses=[],boards=[],waiting=None,loose=None,live=0,ft=None)
        self.last_miss=None
        self.pending=None
        self.state(reason,r)

    def state(self,reason,r):
        t=self.turn
        t['states'].append([r.order_index,reason,'|'.join(t['history'][-10:]),len(t['history']),'',t['points']])
        t['waiting']=len(t['states'])-1

    def clear(self,why):
        if self.turn is not None:
            self.excluded[why]+=1
        self.turn=None
        self.last_miss=None
        self.pending=None

    def next_event(self,action):
        t=self.turn
        if t is not None and t['waiting'] is not None:
            t['states'][t['waiting']][4]=action
            t['waiting']=None

    def close(self,r,reason):
        t=self.turn
        if t:
            # A transfer recorded at the final horn can create an empty, zero time turn.
            if (t['live'] or t['start_sec']>0) and t['ft'] is None and all(s[4] for s in t['states']):
                key=(*self.base,t['anchor'])
                self.out[4].append((*key,t['team'],r.order_index,reason,t['points']))
                for order,sit,hist,length,nxt,at in t['states']:
                    self.out[0].append((*key,t['anchor'],order,sit,hist,length,nxt,t['points']-at))
                for order,hist,length,p in t['shots']:
                    self.out[1].append((*key,order,hist,length,p))
                for order,board,at in t['misses']:
                    self.out[2].append((*key,order,board,t['points']-at))
                for order,at in t['boards']:
                    self.out[3].append((*key,order,t['points']-at))
        self.turn=None
        self.last_miss=None
        self.pending=None

    def play(self,r,kind,value):
        team=r.team_id
        if team not in self.other and r.person_id in self.other:
            team=r.person_id
        if kind=='steal_credit':
            t=self.turn
            if (t and t['waiting']==0 and not t['live'] and t['history']==['Opponent turnover']
                    and t['team']==team and t['start_sec']==r.seconds_remaining):
                t['history'][0]='Steal'
                t['states'][0][0:3]=[r.order_index,'Steal','Steal']
            return
        if kind=='admin' or kind=='start':
            return
        if kind in {'reset','unknown','special','special_ft'}:
            self.clear(kind)
            return
        if self.pending is not None:
            made=self.pending
            if kind=='foul' and r.seconds_remaining==made.seconds_remaining:
                return
            and_one=(kind=='last_ft' and team==made.team_id and r.seconds_remaining==made.seconds_remaining
                     and bool(re.search(r'1\s+of\s+1',str(r.sub_type)+' '+str(r.description),re.I)))
            self.pending=None
            if not and_one:
                self.close(made,'made shot')
                self.start(self.other[made.team_id],'Opponent basket',made)
        if kind=='end':
            self.next_event('Period end')
            self.close(r,'period end')
            return
        if kind=='foul':
            self.next_event('Foul')
            if self.turn:
                self.turn['history'].append('Foul')
                self.turn['live']+=1
            return
        if team not in self.other:
            self.clear('unknown_team')
            return
        if kind=='rebound':
            missed=self.last_miss
            if missed is None:
                self.clear('rebound_without_miss')
                return
            owner,dead=missed
            self.last_miss=None
            if dead:
                return
            if owner!=team:
                self.next_event('Defensive rebound')
                self.close(r,'defensive rebound')
                self.start(team,'Defensive rebound',r)
            elif self.turn and self.turn['team']==team:
                t=self.turn
                self.next_event('Offensive rebound')
                if t['loose'] is not None:
                    t['misses'][t['loose']][1]=True
                t['loose']=None
                t['history'].append('Offensive rebound')
                t['boards'].append((r.order_index,t['points']))
                t['live']+=1
                self.state('Offensive rebound',r)
            return
        if self.turn and self.turn['team']!=team:
            self.clear('unconfirmed_transfer')
        if self.last_miss is not None and kind in ('basket','miss') and self.turn:
            self.clear('missing_rebound')
        t=self.turn
        if t and kind in ('early_ft','last_ft'):
            match=ORDINARY_FT.search(str(r.sub_type)) or ORDINARY_FT.search(str(r.description))
            number,total=map(int,match.groups())
            if (number>1 and t['ft']!=(number,total)) or (number==1 and t['ft'] is not None):
                self.clear('incomplete_free_throws')
                t=None
            else:
                t['ft']=(number+1,total) if number<total else None
        if t and t['ft'] is not None and kind not in ('early_ft','last_ft'):
            self.clear('interrupted_free_throws')
            t=None
        if t:
            t['loose']=None
            t['live']+=1
            self.next_event({'basket':'Field goal attempt','miss':'Field goal attempt','turnover':'Turnover',
                             'early_ft':'Free throw','last_ft':'Free throw'}[kind])
            if kind in ('basket','miss'):
                t['shots'].append((r.order_index,'|'.join(t['history'][-10:]),len(t['history']),value))
            t['points']+=value
        self.last_miss=None
        if kind=='miss':
            self.last_miss=(team,False)
            if t:
                t['misses'].append([r.order_index,False,t['points']])
                t['loose']=len(t['misses'])-1
                t['history'].append('Missed shot')
        elif kind=='basket':
            if t:
                t['history'].append('Made shot')
            self.pending=r
        elif kind=='turnover':
            self.close(r,'turnover')
            reason='Steal' if re.search(r'\bsteal\b',str(r.description),re.I) else 'Opponent turnover'
            self.start(self.other[team],reason,r)
        elif kind in ('early_ft','last_ft'):
            if t:
                t['history'].append('Made free throw' if value else 'Missed free throw')
            if value==0:
                self.last_miss=(team,kind=='early_ft')
            if kind=='last_ft' and value:
                self.close(r,'last free throw')
                self.start(self.other[team],'Opponent free throw',r)


def season(year):
    events=pd.read_csv(DIRECTORY/f'wnba_play_by_play_{year}.csv.gz',low_memory=False)
    schedule=pd.read_csv(DIRECTORY/f'wnba_schedule_{year}.csv.gz')
    assert events.season.eq(year).all() and schedule.season.eq(year).all()
    schedule=schedule[schedule.game_id.astype(str).str[2].isin(['2','4'])].copy()
    assert schedule.game_id.is_unique
    schedule['scope']=schedule.game_id.astype(str).str[2].map({'2':'regular','4':'playoffs'})
    games=schedule.set_index('game_id')
    outputs=[[],[],[],[],[]]
    audit=[]
    frame=events[events.game_id.isin(games.index)]
    for gid,raw in frame.groupby('game_id',sort=False):
        g=games.loc[gid]
        records=list(raw.sort_values('order_index').itertuples(index=False))
        actions=[classify(r) for r in records]
        scores=Counter()
        bad=False
        score_conflict=False
        for r,(kind,val) in zip(records,actions):
            if val:
                if (kind=='basket' and val not in (2,3)) or r.team_id not in (g.home_team_id,g.away_team_id):
                    bad=True
                scores[r.team_id]+=val
                if pd.notna(r.score_home) and pd.notna(r.score_away):
                    if (scores[g.home_team_id],scores[g.away_team_id])!=(r.score_home,r.score_away):
                        score_conflict=True
        reason=''
        if raw.order_index.isna().any() or raw.order_index.duplicated().any():
            reason='ambiguous event order'
        elif bad or scores[g.home_team_id]!=g.home_pts or scores[g.away_team_id]!=g.away_pts:
            reason='score disagrees with schedule'
        elif score_conflict:
            reason='scoring snapshot conflict'
        elif any(b.period<a.period for a,b in zip(records,records[1:])):
            reason='period order'
        kept=[0,0,0,0,0]
        periods=0
        excluded_periods=0
        discarded=Counter()
        if not reason:
            offset=0
            for period,size in raw.groupby('period',sort=True).size().items():
                seq=records[offset:offset+size]
                codes=actions[offset:offset+size]
                offset+=size
                regulation=2 if year<2006 else 4
                duration=(1200 if year<2006 else 600) if period<=regulation else 300
                clock=[r.seconds_remaining for r in seq]
                if (not any(k=='end' for k,_ in codes) or not all(0<=sec<=duration for sec in clock)
                        or any(b>a for a,b in zip(clock,clock[1:]))):
                    excluded_periods+=1
                    continue
                periods+=1
                p=Period(year,int(gid),g.scope,int(period),int(g.home_team_id),int(g.away_team_id))
                for r,(kind,value) in zip(seq,codes):
                    p.play(r,kind,value)
                for i,rows in enumerate(p.out):
                    outputs[i].extend(rows)
                    kept[i]+=len(rows)
                discarded.update(p.excluded)
        audit.append(dict(season=year,game_id=gid,scope=g.scope,events=len(raw),status=reason or 'score matches',
            home_pts=g.home_pts,recorded_home=scores[g.home_team_id],away_pts=g.away_pts,recorded_away=scores[g.away_team_id],
            checked_periods=periods,excluded_periods=excluded_periods,discarded_partial_turns=sum(discarded.values()),
            states=kept[0],shots=kept[1],misses=kept[2],offensive_boards=kept[3],turns=kept[4]))
    for gid in games.index.difference(frame.game_id.unique()):
        audit.append(dict(season=year,game_id=gid,scope=games.loc[gid,'scope'],events=0,status='no event rows',
            states=0,shots=0,misses=0,offensive_boards=0,turns=0))
    turns=['season','game_id','scope','period','turn','team','end_order','end_reason','points']
    for rows,columns,name in zip(outputs,[STATES,SHOTS,MISSES,BOARDS,turns],['states','shots','misses','boards','turns']):
        values=pd.DataFrame(rows,columns=columns)
        values.to_csv(INPUT/f'{name}_{year}.csv.gz',index=False)
    print('LEAGUE_TURNS',year,'scheduled',len(schedule),'states/shots/misses/boards',*[len(r) for r in outputs],flush=True)
    return audit


def main():
    restore_sources()
    INPUT.mkdir(parents=True,exist_ok=True)
    OUT.mkdir(parents=True,exist_ok=True)
    audits=[]
    for year in YEARS:
        audits.extend(season(year))
    pd.DataFrame(audits).to_csv(OUT/'event_game_checks.csv',index=False)


if __name__=='__main__':
    main()
