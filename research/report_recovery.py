"""Export source-backed recovery figures, a case pack and meeting materials."""
from pathlib import Path
import argparse,json,zipfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator,FormatStrFormatter
from possession_recovery import HAZARDS,digest

HERE=Path(__file__).resolve().parent;BASE=HERE/'results/data1';OUT=BASE/'recovery'


def md(a):
    def cell(v):return f'{v:.6f}' if isinstance(v,float) else str(v)
    return '| '+' | '.join(a.columns)+' |\n| '+' | '.join(['---']*len(a.columns))+' |\n'+'\n'.join('| '+' | '.join(map(cell,row))+' |' for row in a.itertuples(index=False,name=None))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args()
    rule=json.loads((OUT/'recovery_rule_receipt.json').read_text(encoding='utf-8'));fit=json.loads((OUT/'fit_receipt.json').read_text(encoding='utf-8'))
    assert args.source.name=='Data (1).zip' and digest(args.source)==rule['archive_sha256']
    coverage=pd.read_csv(OUT/'recovery_coverage.csv');cohorts=pd.read_csv(OUT/'recovery_cohorts.csv');metrics=pd.read_csv(OUT/'metrics.csv');boot=pd.read_csv(OUT/'game_bootstrap.csv');sensitivity=pd.read_csv(OUT/'policy_sensitivity.csv')
    periods=pd.read_csv(OUT/'recovery_periods.csv');first=coverage[coverage.policy.eq('first_rebound')].iloc[0];second=coverage[coverage.policy.eq('second_rebound')].iloc[0]
    with zipfile.ZipFile(args.source) as z:
        name=next(n for n in z.namelist() if n.endswith('/original/wehoop_wnba_pbp.csv'));events=pd.read_csv(z.open(name),low_memory=False)
    events['source_row']=np.arange(len(events))+2
    manifest=periods[periods.policy.eq('first_rebound')].set_index(['game_id','period_number'])
    catalog=events[events.type_id.isin(HAZARDS)].copy();notes=[];traces=[]
    for tid,g in catalog.groupby('type_id',sort=True):
        candidates=g[g.apply(lambda r:manifest.loc[(r.game_id,r.period_number),'candidate_period'],axis=1)]
        positive=candidates[candidates.apply(lambda r:manifest.loc[(r.game_id,r.period_number),'status']=='tail_available',axis=1)]
        same_last=positive[positive.apply(lambda r:manifest.loc[(r.game_id,r.period_number),'last_hazard_source_row']==r.source_row,axis=1)] if len(positive) else positive
        pool=same_last if len(same_last) else positive if len(positive) else candidates if len(candidates) else g
        seed=pool.sort_values('source_row').iloc[0];p=manifest.loc[(seed.game_id,seed.period_number)]
        frame=events[events.game_id.eq(seed.game_id)&events.period_number.eq(seed.period_number)].sort_values('game_play_number',kind='stable').reset_index(drop=True)
        case=f'type-{int(tid)}-row-{int(seed.source_row)}';indices=set()
        anchors=[int(seed.source_row)]+[int(p[c]) for c in ['last_hazard_source_row','restart_source_row','miss_source_row','corroboration_source_row'] if c in p and pd.notna(p[c])]
        for source_row in anchors:
            i=int(frame.index[frame.source_row.eq(source_row)][0]);indices.update(range(max(0,i-2),min(len(frame),i+4)))
        for r in frame.iloc[sorted(indices)].itertuples():
            traces.append({'case_id':case,'source_row':r.source_row,'game_id':r.game_id,'period_number':r.period_number,'game_play_number':r.game_play_number,
                'clock_display_value':r.clock_display_value,'type_id':r.type_id,'type_text':r.type_text,'team_id':r.team_id,'score_value':r.score_value,'home_score':r.home_score,'away_score':r.away_score})
        notes.append({'case_id':case,'type_id':int(tid),'type_text':seed.type_text,'hazard_source_row':int(seed.source_row),'game_id':int(seed.game_id),
            'period_number':int(seed.period_number),'status':p.status,'last_hazard_source_row':p.get('last_hazard_source_row',np.nan),
            'restart_source_row':p.get('restart_source_row',np.nan),'miss_source_row':p.get('miss_source_row',np.nan),'corroboration_source_row':p.get('corroboration_source_row',np.nan)})
    pd.DataFrame(notes).to_csv(OUT/'source_case_index.csv',index=False);pd.DataFrame(traces).to_csv(OUT/'source_case_events.csv',index=False)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white'})
    fig,ax=plt.subplots(figsize=(8.4,4.1));labels=['Original strict sample','First confirmed restart','Second restart · stricter'];values=[first.original_entry_states,first.total_entry_states,second.total_entry_states]
    ax.barh(labels,values,color=['#a1a9aa','#28677a','#7a9177']);ax.invert_yaxis();ax.set_xlim(0,max(values)*1.16)
    for i,v in enumerate(values):ax.text(v+200,i,f'{int(v):,}',va='center')
    ax.set_xlabel('Recorded episode-entry states, across all chronological splits');ax.set_title('More of the existing archive can be used after a clear restart',loc='left',pad=15)
    fig.tight_layout();fig.savefig(OUT/'recovery_coverage.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.6),sharey=True)
    labels=[]
    for i,(split,cohort) in enumerate([('test','all'),('test','original'),('playoffs','all'),('playoffs','original')]):labels.append(('Later games' if split=='test' else 'Playoffs')+' · '+('expanded sample' if cohort=='all' else 'original sample'))
    for ax,baseline,title in zip(axes,['Frozen context','Frozen clock'],['Does adding training records help?','Does it beat the simple clock rule?']):
        for i,(split,cohort) in enumerate([('test','all'),('test','original'),('playoffs','all'),('playoffs','original')]):
            r=boot[boot.policy.eq('first_rebound')&boot.split.eq(split)&boot.cohort.eq(cohort)&boot.stage.eq('entry')&boot.model.eq('Expanded context')&boot.baseline.eq(baseline)].iloc[0]
            ax.errorbar(r.mse_difference,i,xerr=[[r.mse_difference-r.lower],[r.upper-r.mse_difference]],fmt='o',color='#28677a',capsize=3)
        ax.axvline(0,color='#555',linewidth=1);ax.set_title(title,fontsize=11);ax.set_xlabel('Expanded-context error minus reference error\nNegative = lower squared error · 95% game-bootstrap interval',fontsize=8)
        ax.xaxis.set_major_locator(MaxNLocator(4));ax.xaxis.set_major_formatter(FormatStrFormatter('%.3f'));ax.tick_params(axis='x',labelsize=9)
    axes[0].set_yticks(range(4),labels);axes[0].invert_yaxis();fig.tight_layout();fig.savefig(OUT/'recovery_prediction_comparison.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8.5,4.3));x=np.arange(4);order=['train','validation','test','playoffs']
    for offset,cohort,color in [(-.17,'original','#aaa'),(.17,'recovered','#28677a')]:
        a=cohorts[cohorts.policy.eq('first_rebound')&cohorts.cohort.eq(cohort)&cohorts.stage.eq('entry')].set_index('split').loc[order]
        ax.bar(x+offset,a.mean_period_seconds,width=.34,color=color,label='Original' if cohort=='original' else 'Recovered tails')
    ax.set_xticks(x,['Training','Validation','Later games','Playoffs']);ax.set_ylim(0,600);ax.set_ylabel('Mean period seconds remaining at episode entry');ax.set_title('Recovered records come from later parts of periods',loc='left',pad=12);ax.legend(frameon=False)
    fig.tight_layout();fig.savefig(OUT/'recovery_clock_distribution.png',dpi=180);plt.close(fig)
    public={'source':{'only_data_source':'Data (1).zip','archive_sha256':rule['archive_sha256'],'compute':'desktop CPU only'},
        'coverage':coverage.to_dict('records'),'cohorts':cohorts.to_dict('records'),'metrics':metrics.to_dict('records'),
        'bootstrap':boot.to_dict('records'),'sensitivity':sensitivity.to_dict('records'),'rule':rule,'fit':fit,
        'limits':['Ordinary tails after the last special/review event; hazardous plays remain excluded.',
                  'Eligibility is retrospective, and inferred episodes are not official possession labels.',
                  'Added records skew toward later period clocks. These are reused 2025 benchmarks.',
                  'No pass or movement locations, causal player credit, or fresh-season claims are inferred.']}
    (HERE.parent/'assets/recovery.json').write_text(json.dumps(public,separators=(',',':'),allow_nan=False),encoding='utf-8')
    entry=metrics[metrics.policy.eq('first_rebound')&metrics.cohort.eq('all')&metrics.stage.eq('entry')&metrics.split.ne('validation')][['split','model','states','games','rmse','mae']]
    pair=boot[boot.policy.eq('first_rebound')&boot.cohort.eq('all')&boot.stage.eq('entry')&boot.model.eq('Expanded context')][['split','baseline','mse_difference','lower','upper']]
    text=f'''# Recovering ordinary event sequences from Data (1)

This is a conservative extension of the existing event-based possession-value prototype. It adds **{int(first.added_entry_states):,} recorded episode-entry states**, bringing the total from **{int(first.original_entry_states):,} to {int(first.total_entry_states):,}** ({100*first.added_entry_states/first.original_entry_states:.1f}% more). It uses no new basketball data and no paid GPU work. Original source rows, original model weights, original predictions, and `assets/data.json` remain unchanged.

## What changed

The original screening excluded a whole period if it contained any special-foul/free-throw or overturned-review event. Of 595 excluded source periods, 485 had only those soft exclusions. One is out of the standard-game scope, leaving **{int(first.candidate_periods)} candidate periods**. Hard score, ordering, clock and unknown-jump-winner exclusions remain in place.

We now exclude the hazardous sequence and use only a clearly observed **tail after the final hazard**. A restart requires an ordinary missed field goal after that hazard, an opposite-team defensive rebound at a strictly lower period clock, that team's next recorded offensive action as corroboration, and an episode anchored at that rebound by the original parser. A second policy waits for a second such restart. No special free throw is treated as an ordinary automatic transfer, and no ambiguous right to possession is guessed. Special-point rewards remain in the separate ledger.

The first policy has a supported restart in {int(first.periods_with_restart)} periods and adds usable states in **{int(first.periods_with_added_states)}**. All individual episode flags for unexplained transfers, incomplete free throws or uncertain ownership remain exclusions. A restart can exist while all following episodes still fail those checks. The stricter second policy adds **{int(second.added_entry_states):,} entry states**; its full state set is a subset of the first policy. These are partial-period tails, not recovered full quarters or official possession counts.

![Recovery coverage](results/data1/recovery/recovery_coverage.png)

## Evidence, rather than silent correction

The [complete hazard catalog](results/data1/recovery/hazard_catalog.csv) records every affected source row. The [case index](results/data1/recovery/source_case_index.csv) covers every observed hazard type with a deterministic source example; the [selected event snippets](results/data1/recovery/source_case_events.csv) show the recorded clocks, teams, event types and scores around hazards and restarts. Cases with no supported restart remain excluded. A case's selected hazard may precede another hazard in that period; the rule always waits until after the **last** one. These examples and synthetic tests validate handling and provenance, not an official interpretation of every overturned call.

All 624 game/team final scores, all ordinary episode rewards, the 299 separately audited special free-throw points, and retained source score margins are checked independently. All selected features and targets are copied from the frozen event reconstruction without relabelling. Future episode labels, final quality flags and restart eligibility never enter model predictors. Eligibility itself uses retrospective source completeness; it is not a live availability guarantee.

## Fixed-setting CPU comparisons

Training still ends August 9, 2025. The original context settings (300 Poisson-loss histogram trees, depth 3, L2 penalty 100, learning rate 0.04, minimum leaf 100), Markov alpha 1, and simple-clock prior strength 50 are fixed before recovery scoring. The first policy trains on {fit['fits'][0]['training_states']:,} states; the second on {fit['fits'][1]['training_states']:,}. No new parameter search or winner selection is performed. The CPU fits and evaluation took {fit['elapsed_seconds']:.1f} seconds. The original primary shot and EPV comparisons remain frozen.

“Frozen” means fitted on the original strict training subset; “expanded” means fitted with the additional qualified training tails using the same settings. Each row within a chosen policy, stage, split and evaluation cohort uses identical state keys and labels. Original-only evaluation isolates the training effect on unchanged cases; recovered-only evaluation describes the added cases. Neither creates a fresh season test.

{md(entry)}

For the expanded context model, the following paired differences use 2,000 whole-game bootstrap samples. Negative favours expanded context. Intervals describe uncertainty conditional on the chosen reconstructed subset, and do not cover boundary uncertainty, selection bias or a new season.

{md(pair)}

On the later regular benchmark, expanded context improves on frozen context on both the expanded sample and unchanged original sample. Its comparison with the frozen simple-clock model includes zero. Playoff differences also remain uncertain. The supported conclusion is a larger auditable sample and a modest conditional refit improvement, **not** a demonstrated general advantage over a simple clock rule. The [stricter-policy sensitivity](results/data1/recovery/policy_sensitivity.csv) compares refits on identical shared states rather than comparing errors from different samples.

![Paired prediction comparisons](results/data1/recovery/recovery_prediction_comparison.png)

## Coverage and interpretation

Recovered tails have less period time remaining on average. They do not represent a random sample of the excluded quarters. Average outcomes, team coverage and prediction difficulty can therefore change with the sampling rule. The earlier “485 exclusions” finding was a scope diagnosis, not a promise that all those periods could be used. No model is promoted by looking for the best reused-sample result.

![Period-clock distribution](results/data1/recovery/recovery_clock_distribution.png)

[Cohort counts and means](results/data1/recovery/recovery_cohorts.csv), [all metrics](results/data1/recovery/metrics.csv), [all paired intervals](results/data1/recovery/game_bootstrap.csv), [calibration](results/data1/recovery/calibration.csv), [period decisions](results/data1/recovery/recovery_periods.csv), [rule receipt](results/data1/recovery/recovery_rule_receipt.json), and [fit receipt](results/data1/recovery/fit_receipt.json) are public. Individual predictions and new model weights remain in ignored `research/data/`.

## Reproduce and final checks

Run from the desktop VS Code checkout, after the original study:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
py -3.13 research/test_possession_recovery.py
py -3.13 research/possession_recovery.py --source "$env:USERPROFILE/Downloads/Data (1).zip"
py -3.13 research/recovery_models.py
py -3.13 research/report_recovery.py --source "$env:USERPROFILE/Downloads/Data (1).zip"
py -3.13 research/verify_recovery.py --source "$env:USERPROFILE/Downloads/Data (1).zip" --live
```

The final command runs after publication. It independently reconstructs source restart evidence, every target and feature count, unchanged original rows, chronological splits, model inference, Markov values, metrics, intervals, shared-state sensitivity, case snippets and published assets. Twelve new synthetic tests cover every hazard type, technical and retained-possession sequences, dead-ball rebounds, same-clock exclusions, unsupported restarts and hard failures; the earlier eight parser tests also remain required. [Final recovery verification](results/data1/recovery/final_verification.json).

Full spatial pass and movement valuation remains beyond this archive. This extension deliberately estimates only ordinary recorded-event tails. It does not invent pass trajectories, movement endpoints, shot clock or causal action credit.
'''
    (HERE/'RECOVERY.md').write_text(text,encoding='utf-8')
    brief=f'''# Meeting brief: work completed with the existing archive

## What is ready

- The shooting-location study, prediction comparisons and event-based remaining-points prototype are implemented and audited using **only Data (1).zip**.
- Special situations no longer force us to discard an entire period when a later ordinary sequence has a clear, corroborated restart. The hazardous plays themselves remain excluded.
- This adds **{int(first.added_entry_states):,} episode-entry states**, increasing the sample from **{int(first.original_entry_states):,} to {int(first.total_entry_states):,}**. A stricter second-restart check adds **{int(second.added_entry_states):,}**. These are inferred episodes and partial-period tails, not official possession counts.
- CPU refits with the same model settings lower the context model's error on the later regular benchmark. They still do not clearly outperform a simple clock-based rule, and playoff gains remain uncertain.
- Source examples, three recovery charts, a printable meeting walkthrough and independent verification are available. All computations ran on the desktop CPU; Modal stayed off.

## What the findings mean

The project now uses more of the supplied archive, and we can explain much of the original prediction gain: knowing how little time remains matters. The added records come from later parts of quarters, so the expanded sample has a different mix of situations. We preserve the original results and compare models on identical cases. These comparisons are exploratory: reused 2025 games do not establish performance in a new season.

## A short update to say aloud

“I completed the first analysis using only the supplied archive. I then investigated why some records were excluded and why the model gains were small. I added a conservative way to resume after special events once an ordinary miss, rebound and following action clearly establish control. That gives us {int(first.added_entry_states):,} more episode-entry records without changing the source. The refitted context model improves on its previous version in the later regular sample, but it still performs about like a simple clock rule. My next question is what the group wants to learn beyond that, and whether richer action records are available for passes and movement.”

## Decisions and requests for the group

1. Confirm the authoritative play order, possession/correction fields and interpretation of overturned events. The current episodes remain inferred rather than official labels.
2. Clarify existing source discrepancies. For example, game **401736112** has **14** Rhyne Howard attempts in the event records and **15** in the supplied player box. Both versions remain preserved.
3. If the goal is to value passes and movement, ask whether another supplied dataset records actors, timestamps, start/end locations and action outcomes. Those missing actions cannot be created by additional model fitting.
4. Request another consistently recorded WNBA season only for a genuinely new evaluation after model choices are fixed. No extra basketball data has entered this project.

## Walkthrough

Open the [meeting page](https://kevinyamada.github.io/wnba-shot-atlas/meeting/) for the demo and a print-friendly view. Show the original court explorer, then the recovered sample and matched prediction comparisons, then one source discrepancy. Keep the distinction clear: verified calculations and a larger auditable sample are achieved; a general predictive advantage and full spatial action value are not established.

[Recovery methods and results](RECOVERY.md) · [Earlier diagnostic findings](MEETING_DIAGNOSTICS.md) · [Final recovery checks](results/data1/recovery/final_verification.json)
'''
    (HERE/'MEETING_BRIEF.md').write_text(brief,encoding='utf-8')
    print('RECOVERY_REPORT_AND_MEETING_BRIEF_READY',flush=True)
    print('SOURCE_CASE_TYPES',len(notes),'SOURCE_SNIPPET_ROWS',len(traces),flush=True)


if __name__=='__main__':main()
