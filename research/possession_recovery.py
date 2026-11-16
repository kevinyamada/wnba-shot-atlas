"""Recover ordinary tails of source-clean periods after explicit resynchronization.

The frozen primary reconstruction is never rewritten. Special/review sequences
remain excluded; recovery begins after the final hazard and a corroborated live
miss -> defensive rebound. A second-rebound policy supplies a stricter check.
"""
from pathlib import Path
from collections import Counter
import argparse,hashlib,json,time,zipfile
import numpy as np
import pandas as pd
from possession_reconstruction import FT,SPECIAL_FT,SPECIAL_FOUL,TURNOVERS,seconds,FEATURES

HERE=Path(__file__).resolve().parent;BASE=HERE/'results/data1';OLD=HERE/'data/data1/possession'
OUT=BASE/'recovery';PRIVATE=HERE/'data/data1/recovery'
SOFT={'special_free_throw_or_foul','overturned_review'}
HAZARDS=SPECIAL_FT|SPECIAL_FOUL|{215,279}
POLICIES={'first_rebound':1,'second_rebound':2}


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def is_fga(r):return bool(r['shooting_play']) and 'free throw' not in str(r['type_text']).lower()


def restarts(frame):
    """No policy uses a future reward or an estimated movement location."""
    rows=frame.sort_values('game_play_number',kind='stable').to_dict('records')
    danger=[i for i,r in enumerate(rows) if int(r['type_id']) in HAZARDS]
    if not danger:return []
    last=danger[-1];hazard=rows[last];hazard_clock=seconds(hazard['clock_display_value'])
    result=[];miss=None
    for i in range(last+1,len(rows)):
        r=rows[i];tid=int(r['type_id']);team=int(r['team_id']) if pd.notna(r['team_id']) else None
        if is_fga(r):
            miss=r if int(r['score_value'])==0 else None
            continue
        if tid==155:
            live=miss is not None and pd.notna(miss['team_id']) and int(miss['team_id'])!=team
            live=live and seconds(r['clock_display_value'])<hazard_clock and seconds(r['clock_display_value'])<=seconds(miss['clock_display_value'])
            corroboration=None
            if live:
                for next_row in rows[i+1:]:
                    nt=int(next_row['type_id'])
                    if is_fga(next_row) or nt in FT or nt in TURNOVERS or nt==11:
                        if pd.notna(next_row['team_id']) and int(next_row['team_id'])==team:corroboration=next_row
                        break
                    if nt in {155,615,402,412}:break
            if live and corroboration is not None:
                result.append({'last_hazard_source_row':int(hazard['source_row']),'last_hazard_play':int(hazard['game_play_number']),
                    'last_hazard_type':int(hazard['type_id']),'last_hazard_clock':hazard_clock,
                    'miss_source_row':int(miss['source_row']),'miss_play':int(miss['game_play_number']),
                    'restart_source_row':int(r['source_row']),'restart_play':int(r['game_play_number']),
                    'restart_seconds':seconds(r['clock_display_value']),'restart_team_id':team,
                    'corroboration_source_row':int(corroboration['source_row']),'corroboration_play':int(corroboration['game_play_number'])})
            miss=None
        elif tid in set(FT)|TURNOVERS|{11,156,615,402,412}:miss=None
    return result


def qualify(events,periods,episodes,states,policy):
    required=POLICIES[policy];groups={k:g for k,g in events.groupby(['game_id','period_number'],sort=False)}
    episode_starts={(int(r.game_id),int(r.period_number),int(r.start_source_row)):r for r in episodes.itertuples() if r.start_reason=='defensive_rebound' and r.start_anchored}
    manifests=[];anchors={}
    for r in periods.itertuples():
        flags=set(str(r.flags).split('|')) if pd.notna(r.flags) and r.flags else set()
        candidate=bool(flags) and flags<=SOFT and r.scope!='special'
        record={'policy':policy,'game_id':r.game_id,'period_number':r.period_number,'scope':r.scope,
                'original_period_flags':'|'.join(sorted(flags)),'candidate_period':candidate,'qualified_restarts':0,
                'status':'original_clean' if not flags and r.scope!='special' else 'out_of_scope' if r.scope=='special' else 'hard_period_exclusion'}
        if candidate:
            possible=[]
            for a in restarts(groups[r.game_id,r.period_number]):
                e=episode_starts.get((r.game_id,r.period_number,a['restart_source_row']))
                if e is not None and int(e.offense_team_id)==a['restart_team_id']:possible.append(a)
            record['qualified_restarts']=len(possible)
            if len(possible)>=required:
                chosen=possible[required-1];record.update(chosen);record['status']='tail_available';anchors[r.game_id,r.period_number]=chosen
            else:record['status']='no_supported_restart'
        manifests.append(record)
    order=events.set_index('source_row').game_play_number.to_dict();new_episodes=set()
    for r in episodes.itertuples():
        a=anchors.get((r.game_id,r.period_number))
        flags=set(str(r.flags).split('|')) if pd.notna(r.flags) and r.flags else set()
        if a is not None and flags<=SOFT and r.start_anchored and r.scope!='special' and order[r.start_source_row]>=a['restart_play']:
            new_episodes.add(r.episode_id)
    selected=states[states.eligible | (states.episode_id.isin(new_episodes)&states.seconds_remaining.gt(2))].copy()
    selected['cohort']=np.where(selected.eligible,'original','recovered');selected['recovery_eligible']=True;selected['recovery_policy']=policy
    return selected,pd.DataFrame(manifests)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args();started=time.monotonic()
    OUT.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    parent=json.loads((BASE/'possession/reconstruction_audit.json').read_text(encoding='utf-8'))
    assert args.source.name=='Data (1).zip' and digest(args.source)==parent['archive_sha256']
    frozen=[OLD/'all_states.csv.gz',OLD/'all_episodes.csv.gz',OLD/'event_ledger.csv.gz',OLD/'model_states.csv.gz',OLD/'models.joblib',OLD/'predictions.csv.gz',HERE.parent/'assets/data.json']
    hashes={str(p.relative_to(HERE.parent)):digest(p) for p in frozen}
    with zipfile.ZipFile(args.source) as z:
        name=next(n for n in z.namelist() if n.endswith('/original/wehoop_wnba_pbp.csv'));events=pd.read_csv(z.open(name),low_memory=False)
    events['source_row']=np.arange(len(events))+2
    periods=pd.read_csv(BASE/'possession/period_quality.csv').fillna({'flags':''})
    episodes=pd.read_csv(OLD/'all_episodes.csv.gz',float_precision='round_trip')
    states=pd.read_csv(OLD/'all_states.csv.gz',dtype={'offense_team_id':str,'defense_team_id':str},float_precision='round_trip')
    policy={'only_data_source':'Data (1).zip','archive_sha256':parent['archive_sha256'],'rule_version':'last-hazard-live-rebound-v1',
        'primary_recovery_policy':'first_rebound','sensitivity_policy':'second_rebound','hazard_type_ids':sorted(HAZARDS),
        'rule':'Only periods whose original flags are special_free_throw_or_foul and/or overturned_review. Exclude everything through the final hazard. Restart after a later-clock ordinary missed field goal followed by an opposite-team defensive rebound, corroborated by that team’s next offensive action. The original parser must also anchor an episode at that rebound. Keep all individual episode exclusions.',
        'hard_exclusions_unchanged':True,'special_points_remain_separate':True,'no_source_rows_edited':True,
        'selection_limit':'Eligibility is retrospective and the original possession IDs are inferred. These are recorded ordinary-event tails, not an authoritative possession feed or new season test.',
        'design_freeze':'This rule and the first/second restart comparison are fixed before recovery model fitting or scoring.',
        'original_frozen_input_hashes':hashes,'compute':'desktop CPU only'}
    (OUT/'recovery_rule_receipt.json').write_text(json.dumps(policy,indent=2),encoding='utf-8')
    summaries=[];manifests=[];cover=[]
    for name in POLICIES:
        selected,manifest=qualify(events,periods,episodes,states,name)
        assert not selected.state_id.duplicated().any() and selected.seconds_remaining.gt(2).all()
        assert set(states.loc[states.eligible,'state_id'])<=set(selected.state_id)
        proof=selected.merge(events[['source_row','home_team_id','home_score','away_score']],on='source_row',validate='many_to_one')
        sign=np.where(proof.offense_team_id.astype(int).eq(proof.home_team_id),1,-1)
        assert np.array_equal(proof.score_margin.to_numpy(),sign*(proof.home_score-proof.away_score).to_numpy())
        selected.to_csv(PRIVATE/f'{name}_states.csv.gz',index=False);manifests.append(manifest)
        summary=selected.groupby(['cohort','split','stage']).agg(states=('state_id','size'),episodes=('episode_id','nunique'),games=('game_id','nunique'),mean_remaining_points=('remaining_points','mean'),mean_period_seconds=('seconds_remaining','mean')).reset_index()
        summary.insert(0,'policy',name);summaries.append(summary)
        added=selected[selected.cohort.eq('recovered')]
        cover.append({'policy':name,'candidate_periods':int(manifest.candidate_period.sum()),'periods_with_restart':int(manifest.status.eq('tail_available').sum()),
            'periods_with_added_states':len(added[['game_id','period_number']].drop_duplicates()),'added_states':len(added),'added_entry_states':int(added.stage.eq('entry').sum()),
            'total_states':len(selected),'total_entry_states':int(selected.stage.eq('entry').sum()),'original_entry_states':int(selected.cohort.eq('original').loc[selected.stage.eq('entry')].sum())})
    first=pd.read_csv(PRIVATE/'first_rebound_states.csv.gz');second=pd.read_csv(PRIVATE/'second_rebound_states.csv.gz')
    assert set(second.state_id)<=set(first.state_id)
    pd.concat(manifests,ignore_index=True).to_csv(OUT/'recovery_periods.csv',index=False)
    pd.concat(summaries,ignore_index=True).to_csv(OUT/'recovery_cohorts.csv',index=False);pd.DataFrame(cover).to_csv(OUT/'recovery_coverage.csv',index=False)
    # A complete hazard catalog is evidence of which types were covered, not
    # a claim that every hazardous play has an authoritative interpretation.
    catalog=events[events.type_id.isin(HAZARDS)][['source_row','game_id','period_number','game_play_number','clock_display_value','type_id','type_text','score_value']].copy()
    catalog.merge(manifests[0][['game_id','period_number','status','restart_source_row']],on=['game_id','period_number'],validate='many_to_one').to_csv(OUT/'hazard_catalog.csv',index=False)
    assert hashes=={str(p.relative_to(HERE.parent)):digest(p) for p in frozen}
    result={'only_data_source':'Data (1).zip','archive_sha256':parent['archive_sha256'],'original_frozen_artifacts_unchanged':True,
        'coverage':cover,'hazard_types':catalog.groupby(['type_id','type_text']).size().reset_index(name='rows').to_dict('records'),
        'all_expanded_state_margins_match_source_snapshots':True,'second_restart_is_subset_of_first':True,'elapsed_seconds':time.monotonic()-started,
        'completed_utc':pd.Timestamp.now(tz='UTC').isoformat()}
    (OUT/'reconstruction_receipt.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RECOVERY_RECONSTRUCTION_COMPLETE',json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
