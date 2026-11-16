"""Resolve what can be checked inside Data (1), without external corrections."""
from pathlib import Path
import argparse
import csv
import io
import json
import re
import zipfile
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1/followup'
PRIVATE=HERE/'data/data1/followup'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.source) as z:
        def read(suffix):return pd.read_csv(z.open(next(n for n in z.namelist() if n.endswith(suffix))),low_memory=False)
        d=read('/original/wehoop_wnba_pbp.csv')
        boxes=read('/WNBA_player/wnba_player_box.csv');teams=read('/WNBA_Team/wnba_team_box.csv')
        parsed_name=next(n for n in z.namelist() if n.endswith('/original/parsed/wehoop_wnba_pbp_parsed.csv'))
        reader=csv.reader(io.TextIOWrapper(z.open(parsed_name),encoding='utf-8-sig',newline=''))
        header=next(reader);parsed_rows=[r for r in reader if len(r)==len(header)]
        parsed=pd.DataFrame(parsed_rows,columns=header)
    d['source_row']=np.arange(len(d))+2
    shot=d.shooting_play.eq(True)&~d.type_text.str.contains('free throw',case=False,na=False)
    rows=[]
    orders={'export order':['game_id','game_play_number'],'sequence number':['game_id','sequence_number'],
            'period and clock':['game_id','period_number','start_quarter_seconds_remaining','sequence_number']}
    for name,columns in orders.items():
        a=d.sort_values(columns,ascending=[True,True,False,True] if name=='period and clock' else True,kind='stable').copy()
        old=a.groupby('game_id')[['home_score','away_score']].shift().fillna(0)
        dh=a.home_score-old.home_score;da=a.away_score-old.away_score
        expected=a.score_value.where(a.scoring_play.eq(True),0)
        conflict=~np.isclose(dh+da,expected)
        team_expected_home=expected.where(a.team_id.eq(a.home_team_id),0)
        team_expected_away=expected.where(a.team_id.eq(a.away_team_id),0)
        side_conflict=~(np.isclose(dh,team_expected_home)&np.isclose(da,team_expected_away))
        fga=a.shooting_play.eq(True)&~a.type_text.str.contains('free throw',case=False,na=False)
        rows.append({'order':name,'duplicate_game_sort_keys':int(a.duplicated(columns).sum()),'all_event_score_conflicts':int(conflict.sum()),
                     'field_goal_score_conflicts':int((conflict&fga).sum()),'team_specific_score_conflicts':int(side_conflict.sum()),
                     'affected_games':int(a.loc[conflict,'game_id'].nunique())})
        a.loc[conflict,['source_row','game_id','game_play_number','sequence_number','period_number','clock_display_value','text','score_value','home_score','away_score']].to_csv(PRIVATE/(name.replace(' ','_')+'_score_conflicts.csv'),index=False)
    pd.DataFrame(rows).to_csv(OUT/'ordering_diagnostics.csv',index=False)
    s=d[shot].copy();p=boxes[boxes.season.eq(2025)].copy()
    totals=s.groupby(['game_id','athlete_id_1']).agg(event_attempts=('scoring_play','size'),event_makes=('scoring_play','sum')).reset_index()
    totals=totals.merge(p[['game_id','athlete_id','athlete_display_name','field_goals_attempted','field_goals_made']],left_on=['game_id','athlete_id_1'],right_on=['game_id','athlete_id'],validate='one_to_one')
    differences=totals[totals.event_attempts.ne(totals.field_goals_attempted)].copy()
    differences['attempt_difference']=differences.event_attempts-differences.field_goals_attempted
    differences.to_csv(OUT/'attempt_discrepancy_examples.csv',index=False)
    names=p.set_index(['game_id','athlete_id']).athlete_display_name.to_dict()
    rosters={key:dict(zip(a.athlete_display_name,a.athlete_id.astype(int))) for key,a in p.groupby(['game_id','team_id'])}
    extracted=[];matches=[]
    for r in s.itertuples():
        text=str(r.text).strip();m=re.match(r'^(.+?) (?:makes|misses) ',text)
        if m:name=m.group(1).strip()
        else:
            m=re.match(r'^.+? blocks (.+?)\s*[\'’]s\s',text)
            name=m.group(1).strip() if m else None
        roster=rosters.get((r.game_id,r.team_id),{})
        candidates=[aid for n,aid in roster.items() if name==n]
        inferred=candidates[0] if len(candidates)==1 else None
        matches.append({'source_row':r.source_row,'game_id':r.game_id,'game_play_number':r.game_play_number,'athlete_id':int(r.athlete_id_1),
                        'box_name':names.get((r.game_id,r.athlete_id_1)),'text_name':name,'text_id':inferred,
                        'exact_unique_roster_match':inferred is not None,'agrees':inferred==int(r.athlete_id_1) if inferred is not None else None})
    identities=pd.DataFrame(matches)
    identities.to_csv(PRIVATE/'text_actor_review.csv',index=False)
    disagree=identities[identities.exact_unique_roster_match&identities.agrees.eq(False)]
    disagree.to_csv(OUT/'text_actor_disagreements.csv',index=False)
    aliases=identities[~identities.exact_unique_roster_match].groupby(['athlete_id','box_name','text_name'],dropna=False).size().reset_index(name='records')
    aliases.to_csv(OUT/'unmatched_display_names.csv',index=False)
    # Only exact textual statements are called explicit. Absence of 'three
    # point' is not promoted to an authoritative two point attempt label.
    lower=s.text.fillna('').str.lower()
    explicit_three=lower.str.contains(r'\bthree[ -]point\b',regex=True)
    explicit_two=lower.str.contains(r'\btwo[ -]point\b',regex=True)
    s['three_text']=explicit_three.astype(int)
    tally=s.groupby(['game_id','team_id']).three_text.sum().reset_index()
    t=teams[teams.season.eq(2025)][['game_id','team_id','three_point_field_goals_attempted']]
    tally=tally.merge(t,on=['game_id','team_id'],how='outer',validate='one_to_one')
    tally['difference']=tally.three_text-tally.three_point_field_goals_attempted
    tally.to_csv(OUT/'text_three_point_reconciliation.csv',index=False)
    # Diagnose the rejected derived export without using it as model data.
    season=pd.to_numeric(parsed['season'],errors='coerce');games=pd.to_numeric(parsed.game_id,errors='coerce')
    valid=parsed[season.eq(2025)&games.isin(d.game_id.unique())].copy()
    parsed_diagnostics={'columns':list(parsed.columns),'well_formed_records':len(parsed),'matching_2025_original_game_records':len(valid)}
    for c in ['game_id','game_play_number','athlete_id_1','score_value']:
        if c in valid:valid[c]=pd.to_numeric(valid[c],errors='coerce')
    comparable=[c for c in ['text','athlete_id_1','score_value'] if c in valid]
    if not valid.duplicated(['game_id','game_play_number']).any():
        joined=d[['game_id','game_play_number']+comparable].merge(valid[['game_id','game_play_number']+comparable],on=['game_id','game_play_number'],suffixes=('_original','_parsed'))
        parsed_diagnostics['matching_export_position_keys']=len(joined)
        parsed_diagnostics['position_key_field_disagreements']={c:int((~(joined[c+'_original'].eq(joined[c+'_parsed'])|(joined[c+'_original'].isna()&joined[c+'_parsed'].isna()))).sum()) for c in comparable}
    result={'only_data_source':'Data (1).zip','ordering':rows,'field_goal_attempts':len(s),'player_attempt_discrepancies':len(differences),'affected_player_attempt_games':int(differences.game_id.nunique()),'text_actor_exact_matches':int(identities.exact_unique_roster_match.sum()),
            'text_actor_disagreements':len(disagree),'text_actor_unresolved':int((~identities.exact_unique_roster_match).sum()),
            'explicit_three_point_attempts':int(explicit_three.sum()),'explicit_two_point_attempts':int(explicit_two.sum()),
            'neither_explicit_value':int((~explicit_three&~explicit_two).sum()),'three_point_team_box_mismatches':int(tally.difference.ne(0).sum()),
            'parsed_export_diagnostics':parsed_diagnostics,'raw_archive_modified':False,
            'interpretation':'Internal checks, not automatic corrections. No description, score update or inferred shot value is added to model predictors.'}
    (OUT/'archive_investigation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
