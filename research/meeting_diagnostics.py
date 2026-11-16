"""Desktop only diagnostics of frozen Data1 results; no new model fits."""
from pathlib import Path
from prose import clean_markdown
import argparse,hashlib,json,subprocess,time,zipfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent
BASE=HERE/'results/data1';EPV=BASE/'possession';PRIVATE=HERE/'data/data1/possession';OUT=BASE/'meeting'
STAGES={'entry':'Start of a team’s turn','after_miss':'After a missed field goal','after_offensive_rebound':'After an offensive rebound'}
COLORS={'Context boosting EPV':'#28677a','Markov EPV':'#b76639'}


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def md(a):
    def cell(v):return f'{v:.4f}' if isinstance(v,float) else str(v)
    return '| '+' | '.join(a.columns)+' |\n| '+' | '.join(['---']*len(a.columns))+' |\n'+'\n'.join('| '+' | '.join(map(cell,row))+' |' for row in a.itertuples(index=False,name=None))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args();started=time.monotonic()
    OUT.mkdir(parents=True,exist_ok=True)
    audit=json.loads((EPV/'reconstruction_audit.json').read_text(encoding='utf-8'))
    selection=json.loads((EPV/'model_selection_receipt.json').read_text(encoding='utf-8'));selected=selection['selected_model']
    assert args.source.name=='Data (1).zip' and digest(args.source)==audit['archive_sha256']
    frozen=[EPV/'model_selection_receipt.json',PRIVATE/'model_states.csv.gz',PRIVATE/'predictions.csv.gz',PRIVATE/'models.joblib',HERE.parent/'assets/data.json']
    hashes={str(p.relative_to(HERE.parent)):digest(p) for p in frozen}
    with zipfile.ZipFile(args.source) as z:
        def read(suffix):return pd.read_csv(z.open(next(n for n in z.namelist() if n.endswith(suffix))),low_memory=False)
        events=read('/original/wehoop_wnba_pbp.csv');teams=read('/WNBA_Team/wnba_team_box.csv')
    events['source_row']=np.arange(len(events))+2
    quality=pd.read_csv(EPV/'period_quality.csv').fillna({'flags':''});quality['passes']=quality['flags'].eq('')
    game=events.groupby('game_id',sort=True).agg(date=('game_date','first'),home_team_id=('home_team_id','first'),away_team_id=('away_team_id','first')).reset_index()
    game['date']=game.date.str[:10];quality=quality.merge(game,on='game_id',validate='many_to_one');quality['month']=quality.date.str[:7]
    source_period=events.assign(fga=events.shooting_play.astype(str).str.lower().eq('true')&~events.type_text.str.contains('free throw',case=False,na=False),
        normal_fta=events.type_id.isin([97,98,99,100,101,102]),special_fta=events.type_id.isin([103,104,105,106,107,108,157,165,166]))
    source_period=source_period.groupby(['game_id','period_number']).agg(events=('source_row','size'),recorded_points=('score_value','sum'),field_goal_attempts=('fga','sum'),ordinary_free_throws=('normal_fta','sum'),special_free_throws=('special_fta','sum')).reset_index()
    quality=quality.merge(source_period,on=['game_id','period_number'],validate='one_to_one')
    assert len(quality)==audit['periods'] and int(quality.passes.sum())==audit['clean_periods'] and quality.events.sum()==len(events) and quality.recorded_points.sum()==51073
    check_points=events.groupby(['game_id','team_id']).score_value.sum().reset_index().merge(teams[teams.season.eq(2025)][['game_id','team_id','team_score']],on=['game_id','team_id'],validate='one_to_one')
    assert len(check_points)==624 and check_points.score_value.eq(check_points.team_score).all()
    q=quality[quality.scope.ne('special')].copy();names=teams[teams.season.eq(2025)].groupby('team_id').team_display_name.first().to_dict()
    appearances=pd.concat([q.assign(team_id=q.home_team_id),q.assign(team_id=q.away_team_id)],ignore_index=True)
    coverage=appearances.groupby('team_id').agg(periods=('passes','size'),passing_periods=('passes','sum')).reset_index();coverage['team']=coverage.team_id.map(names);coverage['coverage_fraction']=coverage.passing_periods/coverage.periods
    coverage=coverage.sort_values('team');coverage.to_csv(OUT/'coverage_by_team.csv',index=False)
    month=q.groupby('month').agg(periods=('passes','size'),passing_periods=('passes','sum')).reset_index();month['coverage_fraction']=month.passing_periods/month.periods;month.to_csv(OUT/'coverage_by_month.csv',index=False)
    reasons=[]
    for reason in sorted({r for flags in quality['flags'] for r in flags.split('|') if r}):
        mask=quality['flags'].str.split('|',regex=False).map(lambda s:reason in s)
        reasons.append({'reason':reason,'periods':int(mask.sum()),'events':int(quality.loc[mask,'events'].sum())})
    reasons=pd.DataFrame(reasons).sort_values('periods',ascending=False);reasons.to_csv(OUT/'exclusion_reasons.csv',index=False)
    only_special_reviews=quality['flags'].map(lambda v:bool(v) and set(v.split('|'))<={'special_free_throw_or_foul','overturned_review'})
    comparisons=[]
    for scope,a in q.groupby('scope'):
        for passed,b in a.groupby('passes'):
            comparisons.append({'scope':scope,'passes_period_checks':bool(passed),'periods':len(b),'games':b.game_id.nunique(),
                'mean_recorded_points':b.recorded_points.mean(),'mean_fga':b.field_goal_attempts.mean(),'mean_ordinary_fta':b.ordinary_free_throws.mean(),
                'mean_special_fta':b.special_free_throws.mean(),'mean_events':b.events.mean()})
    pd.DataFrame(comparisons).to_csv(OUT/'period_comparison.csv',index=False)
    states=pd.read_csv(PRIVATE/'model_states.csv.gz',float_precision='round_trip');pred=pd.read_csv(PRIVATE/'predictions.csv.gz',float_precision='round_trip')
    pred=pred.merge(states[['state_id','seconds_remaining','offense_team_id','start_reason']],on='state_id',validate='one_to_one')
    assert not pred.state_id.duplicated().any() and len(pred)==len(states[states.split.ne('train')])
    originals=pd.read_csv(EPV/'game_bootstrap.csv');metrics=pd.read_csv(EPV/'metrics.csv');rows=[];spread=[]
    for split in ['validation','test','playoffs']:
        for stage in STAGES:
            a=pred[pred.split.eq(split)&pred.stage.eq(stage)]
            for model in ['Stage mean',selected,'Markov EPV']:
                v=a[model].to_numpy();spread.append({'split':split,'stage':stage,'model':model,'states':len(a),'mean_prediction':v.mean(),'sd_prediction':v.std(),
                    'prediction_05':float(np.quantile(v,.05)),'prediction_95':float(np.quantile(v,.95)),'mean_observed':a.remaining_points.mean(),'sd_observed':a.remaining_points.std(ddof=0)})
            for band in ['all','2_to_24_seconds','over_24_seconds']:
                b=a if band=='all' else a[a.seconds_remaining.le(24)] if band=='2_to_24_seconds' else a[a.seconds_remaining.gt(24)]
                assert len(b)>0
                for model in [selected,'Markov EPV']:
                    y=b.remaining_points.to_numpy();v=b[model].to_numpy();base=b['Stage mean'].to_numpy();difference=(v-y)**2-(base-y)**2
                    g=pd.DataFrame({'game':b.game_id,'difference':difference}).groupby('game').difference.agg(['sum','count'])
                    rng=np.random.default_rng(20261122);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
                    interval=np.quantile((w@g['sum'].to_numpy())/(w@g['count'].to_numpy()),[.025,.975])
                    rows.append({'split':split,'stage':stage,'clock_group':band,'model':model,'states':len(b),'games':len(g),
                        'baseline_rmse':float(np.sqrt(np.mean((base-y)**2))),'model_rmse':float(np.sqrt(np.mean((v-y)**2))),
                        'mse_difference':float(difference.mean()),'lower':float(interval[0]),'upper':float(interval[1]),'mean_observed':float(y.mean()),'mean_prediction':float(v.mean())})
                    if band=='all':
                        old=metrics[metrics.split.eq(split)&metrics.stage.eq(stage)&metrics.model.eq(model)].iloc[0]
                        assert np.isclose(rows[-1]['model_rmse'],old.rmse,atol=1e-12)
                        if split!='validation':
                            old=originals[originals.split.eq(split)&originals.stage.eq(stage)&originals.model.eq(model)].iloc[0]
                            assert np.allclose(interval,[old.lower,old.upper],atol=1e-12)
    results=pd.DataFrame(rows);results.to_csv(OUT/'model_by_stage_clock.csv',index=False);pd.DataFrame(spread).to_csv(OUT/'prediction_spread.csv',index=False)
    for _,a in results.groupby(['split','stage','model']):
        whole=a[a.clock_group.eq('all')].iloc[0];parts=a[a.clock_group.ne('all')]
        assert parts.states.sum()==whole.states and np.isclose(np.average(parts.mse_difference,weights=parts.states),whole.mse_difference,atol=1e-12)
    assert len(coverage)==13 and coverage.periods.sum()==2*len(q) and coverage.passing_periods.sum()==2*q.passes.sum()
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white'})
    fig,ax=plt.subplots(figsize=(8.8,5.7));ax.barh(coverage.team,coverage.coverage_fraction*100,color='#28677a');ax.invert_yaxis();ax.set_xlim(0,100)
    for i,r in enumerate(coverage.itertuples()):ax.text(r.coverage_fraction*100+1,i,f'{r.passing_periods}/{r.periods}',va='center',fontsize=9)
    ax.set_xlabel('Periods passing the strict checks (%)');ax.set_title('The screened sample covers teams unevenly\nRegular season + playoffs; both teams share each period’s source checks',loc='left',pad=12)
    fig.tight_layout();fig.savefig(OUT/'coverage_by_team.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11.5,5.8),sharex=True)
    descriptions={'all':'All entry states','2_to_24_seconds':'2 to 24 seconds left','over_24_seconds':'More than 24 seconds left'}
    for ax,split,title in zip(axes,['test','playoffs'],['Later regular season games','Playoffs']):
        a=results[results.split.eq(split)&results.stage.eq('entry')];positions=[];labels=[]
        for i,band in enumerate(descriptions):
            for j,model in enumerate([selected,'Markov EPV']):
                r=a[a.clock_group.eq(band)&a.model.eq(model)].iloc[0];y=i*2.5+j;positions.append(y);labels.append(('Context' if j==0 else 'Markov')+f' · n={r.states:,}')
                ax.errorbar(r.mse_difference,y,xerr=[[r.mse_difference-r.lower],[r.upper-r.mse_difference]],fmt='o',color=COLORS[model],capsize=3)
            ax.text(.02,i*2.5-.45,descriptions[band],transform=ax.get_yaxis_transform(),fontsize=9,va='center',color='#666')
        ax.set_yticks(positions,labels);ax.set_ylim(6.8,-.9);ax.axvline(0,color='#555',linewidth=1);ax.set_title(title);ax.set_xlabel('Error difference vs simple average\nNegative = lower error · 95% game bootstrap interval',fontsize=9)
    fig.suptitle('Does the model help throughout a period, or mostly near its end?',x=.03,ha='left',fontsize=13);fig.tight_layout(rect=(0,0,1,.95));fig.savefig(OUT/'entry_error_by_clock.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8.5,4.8));plot_metrics=pd.read_csv(OUT/'clock_baseline_metrics.csv') if (OUT/'clock_baseline_metrics.csv').exists() else metrics
    display_models=['Stage mean','Simple clock average',selected,'Markov EPV'] if (OUT/'clock_baseline_metrics.csv').exists() else ['Stage mean',selected,'Markov EPV']
    test=plot_metrics[plot_metrics.split.eq('test')&plot_metrics.model.isin(display_models)&plot_metrics.stage.ne('all_states')]
    x=np.arange(3)
    for i,model in enumerate(display_models):
        a=test[test.model.eq(model)].set_index('stage').loc[list(STAGES)];ax.bar(x+(i-(len(display_models)-1)/2)*.20,a.rmse,width=.20,label='Simple average' if model=='Stage mean' else 'Simple clock average' if model=='Simple clock average' else 'Context model' if model==selected else 'Markov model',color={'Stage mean':'#aaa','Simple clock average':'#7a9177',selected:'#28677a','Markov EPV':'#b76639'}[model])
    ax.set_xticks(x,['At entry','After a miss','After an offensive rebound']);ax.set_ylabel('Prediction error in points (RMSE; lower is better)');ax.set_title('Extra complexity does not help equally at every recorded state',loc='left',pad=12);ax.legend(loc='upper center',bbox_to_anchor=(.5,-.14),ncol=len(display_models),fontsize=8,frameon=False)
    fig.tight_layout(rect=(0,.05,1,1));fig.savefig(OUT/'error_by_state.png',dpi=180);plt.close(fig)
    assert hashes=={str(p.relative_to(HERE.parent)):digest(p) for p in frozen}
    report={'only_data_source':'Data (1).zip','archive_sha256':audit['archive_sha256'],'base_analysis_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip(),
        'no_new_model_fits':True,'no_cloud_compute':True,'frozen_inputs_unchanged':hashes,'all_periods':len(quality),'passing_periods':int(quality.passes.sum()),
        'excluded_periods':int((~quality.passes).sum()),'excluded_only_for_special_or_review_rules':int(only_special_reviews.sum()),
        'standard_game_periods':len(q),'standard_game_passing_periods':int(q.passes.sum()),'min_team_coverage':float(coverage.coverage_fraction.min()),'max_team_coverage':float(coverage.coverage_fraction.max()),
        'checks':['ZIP digest matches the exact supplied archive','All 624 team point totals independently reconcile','Every raw event belongs to exactly one audited period',
            'All team and monthly coverage denominators reconcile','All overall model errors match the frozen public metrics','Overall paired intervals reproduce the published bootstrap',
            'Clock subgroup counts and weighted error differences reconcile with their overall groups','Five frozen inputs are byte unchanged'],
        'limitations':['Exploratory subgroup diagnosis on reused 2025 data; no model reselection','Period screening is a parser scope/consistency restriction, not proof every excluded record is wrong',
            'Teams share each period quality label; this is data coverage, not team quality','Intervals condition on the reconstructed subset and do not measure boundary uncertainty'],
        'elapsed_seconds':time.monotonic()-started,'completed_utc':pd.Timestamp.now(tz='UTC').isoformat()}
    (OUT/'diagnostics_receipt.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    small=results[results.split.isin(['test','playoffs'])&results.stage.eq('entry')][['split','clock_group','model','states','model_rmse','baseline_rmse','mse_difference','lower','upper']]
    (HERE/'MEETING_DIAGNOSTICS.md').write_text(clean_markdown(f'''# Diagnostics before the meeting

All new calculations ran on the desktop CPU using only Data (1).zip. No models were refitted, no model settings were changed, and all five frozen inputs remain byte identical. This is an exploratory explanation of existing results, not a new test or selection exercise.

## What the data screening means

{len(quality)} periods are in the source; {int(quality.passes.sum())} pass the conservative period checks. Of the {int((~quality.passes).sum())} excluded periods, **{int(only_special_reviews.sum())} are excluded only because of special foul/free throw or overturned review rules**. Those events may be legitimate basketball events. Exclusion does not prove the whole period is wrong. Handling these cases more carefully is possible future work with the existing archive; their correctness must be established before changing the main sample.

Standard regular season/playoff games account for {len(q)} periods; {int(q.passes.sum())} pass. A period may pass while an individual episode inside it still fails an ownership or free throw sequence check. These coverage figures therefore describe period screening, not the final fraction of official possessions retained. No official possession denominator is available. Both teams share the period label; coverage differences are not team performance rankings.

![Period coverage by team](results/data1/meeting/coverage_by_team.png)

{md(reasons)}

Reasons overlap; do not sum that table as if each period had exactly one reason. [Monthly coverage](results/data1/meeting/coverage_by_month.csv) and [retained/excluded period summaries](results/data1/meeting/period_comparison.csv) describe how the screened sample differs. Recorded points include ordinary and special free throws in this descriptive comparison.

## Where predictions help or fail

Only the already selected context model and the fixed Markov comparison are diagnosed against the training state mean baseline. Groups are the three existing state types, with a period clock split at 24 seconds, an existing model bin boundary. Twenty four seconds here refers to **time left in the period**, not an observed shot clock. All groups are shown; none selects a new winner. Whole games are bootstrapped 2,000 times using the original seed and paired errors. Subgroup intervals are exploratory and unadjusted for multiple comparisons. They do not cover uncertainty in inferred possession boundaries.

![Entry error by clock](results/data1/meeting/entry_error_by_clock.png)

{md(small)}

![Error by recorded state](results/data1/meeting/error_by_state.png)

Different state types have different outcome distributions, so error differences between state types do not rank their difficulty or the causal value of an action. Compare models within the same state type and sample. [All subgroup results](results/data1/meeting/model_by_stage_clock.csv) include validation, later regular games and playoffs; [prediction spread](results/data1/meeting/prediction_spread.csv) shows how much the fixed predictions vary. Variation in predictions alone is not evidence of accuracy.

## Interpretation and next work

The current result remains an audited prototype with uncertain overall improvement for the validation selected model. The most useful next work is to explain the model's errors and improve supported event handling before paying for more model searches. More special case handling can potentially retain additional current archive periods, but cannot create the unrecorded passes and movement required for spatial action valuation. A genuinely new season is still needed for a fresh benchmark.

The [plain English meeting brief](MEETING_BRIEF.md) separates completed work, provisional findings, and concrete requests. The [run receipt](results/data1/meeting/diagnostics_receipt.json) records source and frozen input hashes. Final checks are saved in [verification](results/data1/meeting/final_verification.json) after publication.
'''),encoding='utf-8')
    if (OUT/'clock_baseline_metrics.csv').exists():
        clock=pd.read_csv(OUT/'clock_baseline_metrics.csv');clock_pairs=pd.read_csv(OUT/'clock_baseline_comparisons.csv')
        with (HERE/'MEETING_DIAGNOSTICS.md').open('a',encoding='utf-8') as f:
            f.write(clean_markdown('\n## Can a simple clock rule explain the gain?\n\nOne additional diagnostic baseline uses only recorded state type and the existing six period clock bins. It estimates training bin means, shrunk with a fixed 50 observation state type prior. It is fitted only through August 9. No settings are tuned against validation or later results. Its design follows the preceding diagnosis on already examined data, so it is explicitly exploratory and does not replace the originally selected model. The existing fitted models and published website data remain unchanged.\n\n'))
            f.write(clean_markdown(md(clock[clock.stage.eq('entry')][['split','model','states','rmse','mae']])))
            f.write(clean_markdown('\n\nHere differences compare each existing model with the simple clock average. Negative favours the existing model. Both the selected context model and Markov intervals include zero in later regular games and playoffs, so neither establishes an additional entry state improvement beyond this simple clock rule on these reused samples.\n\n'))
            f.write(clean_markdown(md(clock_pairs[clock_pairs.stage.eq('entry')&clock_pairs.split.ne('validation')][['split','model','mse_difference','lower','upper']])))
            f.write(clean_markdown('\n\n[Training bin values](results/data1/meeting/clock_baseline_training.csv), [settings receipt](results/data1/meeting/clock_baseline_receipt.json), and [all comparisons](results/data1/meeting/clock_baseline_comparisons.csv). The diagnostic recipe is in `meeting_clock_baseline.py`; it adds one inexpensive training only baseline, not a new search.\n'))
            f.write(clean_markdown('''\n## Reproduce on the desktop\n\nFrom the existing VS Code checkout after the main possession study:\n\n```powershell\n$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'\npy -3.13 research/meeting_clock_baseline.py\npy -3.13 research/meeting_diagnostics.py --source "$env:USERPROFILE/Downloads/Data (1).zip"\npy -3.13 research/verify_meeting_diagnostics.py --source "$env:USERPROFILE/Downloads/Data (1).zip" --live\n```\n\nThe last command checks published files and is run after publication. No Modal invocation or external basketball download is part of these commands.\n'''))
    print('MEETING_DIAGNOSTICS_COMPLETE',json.dumps(report,indent=2),flush=True)
    print(small.to_string(index=False),flush=True)


if __name__=='__main__':main()
