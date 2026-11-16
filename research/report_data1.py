"""Write the current research report and secondary robustness tables."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from data1_cpu import distance_model,score

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1'


def md(d):
    d=d.copy()
    for c in d:
        if pd.api.types.is_float_dtype(d[c]):d[c]=d[c].map(lambda x:f'{x:.6f}' if np.isfinite(x) else '—')
    rows=[list(d.columns)]+[['---']*len(d.columns)]+d.astype(str).values.tolist()
    return '\n'.join('| '+' | '.join(str(x).replace('|','/') for x in row)+' |' for row in rows)


def main():
    source=json.loads((OUT/'source_audit.json').read_text());selection=json.loads((OUT/'selection_receipt.json').read_text());usage=json.loads((OUT/'compute_usage.json').read_text())
    metrics=pd.read_csv(OUT/'metrics.csv');boot=pd.read_csv(OUT/'game_bootstrap.csv');points=pd.read_csv(OUT/'points_metrics.csv')
    regions=pd.read_csv(OUT/'cpu/league_regions.csv');regions['attempt_share']=regions.attempts/regions.attempts.sum();regions['made_basket_share']=regions.makes/regions.makes.sum()
    s=pd.read_csv(HERE/'data/data1/model_shots.csv.gz',dtype={'player_id':str,'team_id':str})
    rolling=[]
    for fold,(cut,end) in {'july':('2025-07-01','2025-07-21'),'august':('2025-07-21','2025-08-10')}.items():
        train=s[s.scope.eq('regular')&s.date.lt(cut)];val=s[s.scope.eq('regular')&s.date.ge(cut)&s.date.lt(end)]
        rolling.append({'fold':fold,'model':'Distance baseline','train_shots':len(train),**score(val.made,distance_model(train,val))})
        for task in sorted((OUT/'experiments').glob('*/task.json')):
            r=json.loads(task.read_text());c=r.get('config',{})
            if c.get('fold')!=fold or r.get('status')!='complete':continue
            if r['family']=='Bayesian HSGP':
                rolling.append({'fold':fold,'model':'Context GP' if c.get('context') else 'Player GP','train_shots':len(train),'sampling_checks_pass':r['diagnostics']['sampling_checks_pass'],**r['validation']})
            elif r['family']=='GPU tree comparison':
                for name,m in r['selected'].items():
                    rolling.append({'fold':fold,'model':name,'train_shots':len(train),**{k:v for k,v in m.items() if k in ['shots','brier','log_loss','auc','mean_prediction','observed']}})
    pd.DataFrame(rolling).to_csv(OUT/'rolling_origin.csv',index=False)
    arc=json.loads((OUT/'cpu/arc_review.json').read_text())
    cv=pd.read_csv(OUT/'spatial_cv.csv');cv_rows=[]
    for (model,buffer),a in cv.groupby(['model','buffer_ft']):cv_rows.append({'model':model,'buffer_ft':buffer,'shots':int(a.shots.sum()),'brier':np.average(a.brier,weights=a.shots),'log_loss':np.average(a.log_loss,weights=a.shots)})
    pd.DataFrame(cv_rows).to_csv(OUT/'spatial_cv_pooled.csv',index=False)
    billing=usage.get('modal_billing',{})
    billing_table=md(pd.DataFrame([{'resource':k,'USD before credits':v} for k,v in billing.get('by_resource',{}).items()]))
    selected=selection['selected_model'];later=metrics[(metrics.split=='test')&(metrics.model==selected)].iloc[0]
    baseline=metrics[(metrics.split=='test')&(metrics.model=='Distance baseline')].iloc[0]
    ci=boot[(boot.split=='test')&(boot.model==selected)].iloc[0]
    gp_d=selection['gp_diagnostics'];gp_table=pd.read_csv(OUT/'gp_validation_selection.csv')
    diagnostics=pd.read_csv(OUT/'gp_diagnostics.csv')
    numerical=json.loads((OUT/'numerical_checks.json').read_text())
    report=f'''# WNBA shot study — Data (1) update

Kevin Yamada · November 15, 2026

The current [interactive page](https://kevinyamada.github.io/wnba-shot-atlas/) describes recorded shot locations and compares conditional make and field goal point predictions. **Every basketball input comes from the supplied Data (1).zip.** This update replaces the older public-download results. Git history retains the previous work; it is not mixed into these results.

**{selected}** is selected using August 10–26 validation log loss. On the previously examined August 27–September 11 benchmark, its Brier score is **{later.brier:.6f}**, versus **{baseline.brier:.6f}** for the distance baseline. The paired game-bootstrap difference is **{ci.brier_difference:.6f}**, with 95% interval **[{ci.lower:.6f}, {ci.upper:.6f}]**. Negative differences favor the selected model. This interval includes zero, so these games do not clearly distinguish its error from the distance baseline. These are modest within-season comparisons, not evidence of performance in a new season.

## Source, scope and known conflicts

Original archive: `Data (1).zip`, 1,937,912,926 bytes. SHA-256: `{source['archive_sha256']}`. All 45 files were read and inventoried. See the [complete archive and literature review](ARCHIVE_REVIEW.md), [45-file manifest](results/archive_manifest.csv), and [source audit](results/data1/source_audit.json).

The original WNBA event table has 121,342 records and 42,193 attempts in 312 games. Standard regular-season descriptive totals are **38,535 attempts, 16,926 makes, 38,533 FG points, 286 games**. The All-Star game and standalone Cup final are excluded, as are playoffs from descriptive regular-season maps. The half-court view contains 38,441 attempts; 94 longer attempts remain in the season totals. Free throws are outside this target.

All 624 game/team combinations agree with the supplied boxes for FGA, FGM and FG points. An independent outer player join, including zero-attempt boxes, reproduces **18 player/game FGA disagreements in eight games**. Makes and FG points agree. No missed shot is silently reassigned. Descriptive maps retain the raw events with this caveat; every primary shot model and its within-season player histories excludes all eight games. That post-game quality restriction is not a feature available to a live forecaster. There are also **88 shot-score-update conflicts**, affecting 27 regular-season games. Score margin and sequence-derived features are excluded from the primary shot comparison. Correct season totals do not validate possessions or event ordering. The separate team-level [event-based EPV extension](POSSESSION_VALUE.md) applies its own conservative period and control checks.

| Interval | Attempts | Games | Use |
| --- | ---: | ---: | --- |
| May 16–Aug 9 | 25,751 | 191 | Parameters and preprocessing |
| Aug 10–26 | 5,995 | 45 | Settings, model selection, separate calibration |
| Aug 27–Sep 11 | 5,626 | 42 | Reused later-game benchmark |
| Sep 14–Oct 10 | 3,311 | 24 | Reused playoff transfer benchmark |

No games cross temporal splits. All models stay fitted through August 9; there is no unequal refit using validation outcomes. The original project already examined the later and playoff samples. They are **not untouched tests**. The supplied college 2026 files are not extra WNBA seasons. A new season test requires new supplied WNBA data.

## Coordinates and descriptive findings

For home shots let sign = 1, otherwise −1. Use x = 41.75 − sign × coordinate_x and y = sign × coordinate_y. The basket is (0,0); x points toward half court and y sideways. Display bounds are x ∈ [−5.25,41.75], y ∈ [−25,25]. Recorded locations are on a whole-foot grid. The court convention uses radius 22 + 1.75/12 ft, corner y = ±22 ft and their geometric intersection. Geometry is an explicit analytic convention, not an authoritative missed-shot value label.

Signed distance is the shortest distance to the arc or finite corner segment. There are **508** attempts in [−2,0) ft and **4,380** in (0,2] ft. Areas estimated on a 0.05 ft half-court grid are **153.8** and **166.425** sq ft. The outside/inside density ratio is **{arc['outside_inside_density_ratio']:.6f}**; a 2,000-resample game bootstrap over 286 games gives **[{arc['game_bootstrap_95_interval'][0]:.6f}, {arc['game_bootstrap_95_interval'][1]:.6f}]**. The 140 attempts recorded exactly on the line are excluded from this ratio, but the histogram puts them in the first outside bin. This binning is not official three-point classification.

One hundred artificial half-foot coordinate perturbations give ratios **{arc['coordinate_sensitivity_ratio_range'][0]:.3f}–{arc['coordinate_sensitivity_ratio_range'][1]:.3f}**. This is a sensitivity range, not a confidence interval or observed player movement. The sparse inside band describes shot selection; it does not demonstrate that players stepped backwards or identify a causal reward effect.

Every website square groups actual events by x/y, team and athlete. Frequency uses attempts per square foot on a log color scale. Raw make rates stripe cells with fewer than 20 attempts. Leaders use actual FG points, show tied leaders and reflect scoring volume rather than shooting skill. Player names and team labels are read from the same supplied boxes. The GP map sets player effect to zero and contextual inputs to training means. Its pointwise intervals and interval-width map express model uncertainty for that reference, not a player ability ranking or a simultaneous credible band.

### Where attempts and made baskets occur

{md(regions[['region','attempts','makes','points','attempt_share','made_basket_share','make_rate']])}

These are explicitly defined geometric regions, not authoritative two/three-point attempt labels. Attempt share answers where recorded shots are taken; made-basket share answers where made baskets occur; make rate conditions on taking a shot in that region. Those denominators answer different questions. [Team regions](results/data1/cpu/team_regions.csv), [player regions](results/data1/cpu/player_regions.csv) and the interactive squares retain count-based comparisons. Differences mix opportunity, role, selection and shooting; they are not causal player skill estimates.

## Model definitions and selection

The distance baseline bins radius at 0,4,8,12,16,20,22+1.75/12,24,28,100 ft and uses Beta(1,1)-smoothed make counts. The constant baseline is the training make rate. Spatial logistic uses additive cubic splines and their tensor interactions; contextual logistic adds standardized context and one-hot shooter/team effects. C is selected from 0.1,1,10 using validation loss. Contextual logistic does not automatically improve predictions, as its reported validation error shows.

IDW averages smoothed rates in the 16 nearest populated two-foot cells, with powers 1,2,3 selected on validation. Kriging instead uses smoothed cell logits. Ordinary/universal kriging use fitted exponential residual variograms of training cells with at least 20 attempts, removing approximate sampling noise; universal kriging includes distance trend. Gaussian transformed-rate kriging is an approximation to a binary likelihood. SPDE represents a Matérn-like field on an extended triangular mesh, using a binomial conditional Laplace fit. Range 4/8/16 ft and sigma 0.3/0.7/1.5 are selected on validation with 3 ft spacing. This is not INLA or integration over SPDE hyperparameters. The [mesh refinements](results/data1/cpu/mesh_refinement.csv) compare 3,2,1.5 ft at fixed selected hyperparameters; local predictions can change even if aggregate loss barely changes.

The Bayesian GP uses a noncentered two-dimensional Matérn-5/2 spectral approximation. For modes ω and anisotropic lengths ℓ, spectral density is η² × 4πΓ(3.5)5^2.5/Γ(2.5) × product(ℓ)/(5 + sum((ωℓ)²))^3.5. Product sine bases are normalized by the domain half-widths. The Bernoulli/binomial likelihood uses logit p = intercept + spatial field + optional player effect + optional context. It assumes conditionally independent attempts given those effects; within-game dependence and unmeasured defenders or shot difficulty are not fully modeled. Grouping identical location/player trials is likelihood-equivalent up to parameter-independent binomial constants; contextual models retain individual trials.

Default priors are intercept Normal(0,1), independent truncated-Normal(8,3) lengths between 3 and 20 ft, amplitude HalfNormal(1), player SD HalfNormal(0.5), standardized context coefficients Normal(0,0.35). Player effects sum to zero and are rescaled to preserve their marginal SD; the effects are correlated under this constraint. New-player effects are integrated over their distribution. Posterior predictions average inverse-logit probabilities, not logits. Four vectorized NUTS chains initially use target acceptance 0.96 and depth limit 11. Longer wide-domain replications revealed divergences, so the remaining precision fits use target acceptance 0.99 and 6,000 warmup steps per chain. Divergent fits are retained but never promoted. Main fits use 3,000 warmup and 3,000 retained draws per chain; longer replications use 6,000 or 8,000 retained draws. Up to 3,000 evenly spaced retained draws form reported predictions, giving all chains equal representation.

Sensitivity checks vary basis 24/32/40 per axis, lower length bound 1 vs 3 ft, player SD prior 0.25/0.5/1, amplitude prior 0.5/1/2, radial asinh coordinate warp and domain half-widths (36,38) vs (48,50). A finite basis on a bounded domain is not the exact stationary GP. Independent closed-form Matérn comparisons at fixed locations are in [numerical checks](results/data1/numerical_checks.json); these check length 8 ft and do not replace empirical basis/domain/length sensitivity.

Only fits with rank R-hat < 1.01, minimum bulk ESS ≥ 400, zero divergences and zero depth-limit hits are eligible. **{int(diagnostics.sampling_checks_pass.eq(True).sum())} of {len(diagnostics)}** saved GP runs pass. Failed diagnostics are retained and excluded from promotion; a successful process alone does not establish valid sampling. Within each configuration the representative uses the most retained draws, then highest bulk ESS, never the best predictive seed. Configuration selection uses validation log loss. Independent replication differences are in [stability results](results/data1/gp_replication_stability.csv).

Selected GP: **{selection['selected_gp_id']}**. Maximum R-hat **{gp_d['max_rhat']:.6f}**, minimum bulk ESS **{gp_d['minimum_bulk_ess']:.1f}**, divergences **0**, depth-limit hits **0**. [Selection receipt](results/data1/selection_receipt.json) records the choice before new later-period scores are calculated. [Posterior predictive checks](results/data1/gp_predictive_check.csv) compare simulated training make totals by distance with observed totals; they assess in-sample fit, not forecast accuracy.

GPU CatBoost and XGBoost compare spatial-only and contextual features. Each of three main seeds searches nine depth/regularization combinations per binary family and nine joint-outcome configurations, with early stopping on validation only. Main family predictions average the three selected seed fits. CatBoost depths 4/6/8, XGBoost depths 3/5/7, penalties 3/10/30, learning rate .035, maximum 2,500 trees, early-stopping patience 150. XGBoost uses minimum child weight 30, row subsample .85 and column subsample .9. Categorical ID levels are learned from training, with unknown levels handled explicitly. CatBoost GPU training is nondeterministic despite a fixed seed.

Context fields are period, seconds remaining in that period, home status, strictly lagged eligible regular-season player counts, fixed 2022–2024 regular-season-coded box counts, and shooter/team IDs for trees/logistic. Rate priors use (makes+22)/(attempts+50), with log(1+attempts) for volume. Histories are constant within a game and use earlier games only; playoff histories freeze at regular-season end. All earlier eligible regular attempts, including longer shots outside the half-court modeling view, enter history counts. During validation and later-game evaluation, these covariates update after each completed earlier game, including earlier games in that same evaluation interval. Parameters stay fixed: this is sequential game prediction with available history, not a simultaneous forecast of an entire future block. The 2022–2024 player sums also match all 1,404 corresponding supplied game/team FGA, FGM and three-point-make totals. Past box season_type=2 includes specially coded games; this is a fixed pre-2025 history definition, not future information. Period clock is not a shot clock. Current-game boxes, descriptions, scoring labels, assists, score margin, salaries, protected attributes and full-2025 aggregates are not predictors.

The equal-weight ensemble averages distance, SPDE, selected GP, CatBoost context and XGBoost context. A separate Platt transformation fits intercept and slope to validation predictions, with logistic C=1000. Its validation score would be in-sample and is omitted. It is a secondary comparator, not a model promoted by comparing its fitted validation error with out-of-sample rows.

## Identical-shot temporal comparisons

### Validation — settings and primary choice

{md(metrics[metrics.split.eq('validation')].sort_values('log_loss')[['model','shots','brier','log_loss','auc']])}

### Later regular-season benchmark

{md(metrics[metrics.split.eq('test')].sort_values('log_loss')[['model','shots','brier','log_loss','auc']])}

### Playoff transfer benchmark

{md(metrics[metrics.split.eq('playoffs')].sort_values('log_loss')[['model','shots','brier','log_loss','auc']])}

[Calibration bins](results/data1/calibration.csv), [paired game-bootstrap differences](results/data1/game_bootstrap.csv), and [all eligible GP specifications](results/data1/all_gp_benchmarks.csv) remain inspectable. The bootstrap samples whole games with replacement, uses 2,000 replicates and pools errors by shot count. Intervals are conditional on fitted models and the observed games; they do not include model-selection uncertainty or guarantee transfer to another season. Multiple model comparisons are exploratory, not multiplicity-adjusted hypothesis tests.

## Observed-outcome expected FG points

The source lacks authoritative 2/3 attempt values for every miss. Joint models directly estimate P(0),P(2),P(3), so P(make)=P(2)+P(3) and E[FG points]=2P(2)+3P(3). No inferred geometric miss labels or external corrected attempt values enter the calculation. This target is the observed location/context-dependent scoring mix conditional on an attempt. It does not identify a counterfactual shot type, free-throw reward, or future possession value.

{md(points[points.split.eq('test')].sort_values('rmse')[['model','shots','rmse','mae','mean_expected','mean_observed']])}

The distance outcome baseline adds one pseudocount to each of 0/2/3 in the same radial bins. Joint logistic uses its multiclass validation loss to choose C. Joint GPU models use multiclass validation loss, then average their three seed probability vectors. [Point metrics](results/data1/points_metrics.csv) and [paired MSE intervals](results/data1/points_game_bootstrap.csv) report all periods. The joint GPU model only slightly improves later-game point RMSE over the distance outcome baseline (1.155226 vs 1.155618); its paired MSE difference interval includes zero. Joint logistic is worse than the distance baseline on this benchmark. These results do not establish a clear expected-points improvement or optimal basketball decision-making.

## Spatial transfer and rolling-origin checks

Only the 25,751 early-season training shots enter spatial cross-validation. Fixed regions divide x at 16 ft and y at 0. Hold out each region, then remove training locations within 0,2,4 ft of any held-out location. Every measured nearest separation strictly exceeds its buffer. Games may occur on both sides. This tests missing-area transfer, not future-game prediction; four regions do not cover every possible partition.

All fold-specific outcomes, rate estimates, trends and variograms are refitted within the retained training area. Settings are fixed for this diagnostic: IDW power 2, spatial logistic C=1, SPDE range 8/sigma .7/spacing 3 and GP defaults with location only. GP folds omit player effects and histories so held-out-location labels cannot leak through those summaries. A GP row is pooled only when all four folds pass sampling diagnostics. These location-only CV results do not spatially validate the contextual temporal winner.

{md(pd.DataFrame(cv_rows).pivot(index='model',columns='buffer_ft',values='brier').reset_index().rename(columns={0:'0 ft',2:'2 ft',4:'4 ft'}))}

The distance baseline has the lowest pooled Brier score at 0 and 2 ft; universal kriging has the lowest at 4 ft. Spatial GP 4 ft results are omitted because not all four fits pass sampling checks. The GP is not uniformly better at missing-area transfer. Nonmonotonic scores across buffers can occur because the retained training set and extrapolation change.

[Rolling-origin comparisons](results/data1/rolling_origin.csv) train before July 1 or July 21 and validate on the following supplied interval. They assess consistency earlier in the same season. Context CatBoost improves on distance in both intervals. The July contextual GP and August player GP fail diagnostics; their flagged rows remain visible for transparency and do not support conclusions about reliable Bayesian performance. These checks do not become a new season or erase the reused-benchmark limitation.

## GPU execution and cost

Completed Modal results ran on verified **NVIDIA H100 80GB** GPUs, up to four concurrently. A later H100 request was assigned H200 hardware; those four higher-acceptance workers were stopped before completing results. The completed-run allocation lower bound is **US${usage['measured_gpu_usd_lower_bound']:.2f}**, across **{usage['successful_runs']} successful runs**, including **{usage['boosting_candidates_fitted']} boosting candidates**, GP prior/basis/domain/warp checks, buffered spatial folds and independent posterior replications. Diagnostic failures still consume compute and remain recorded. The initial small pilot did not pass the strict R-hat threshold and was not promoted.

XGBoost 3.0.2 initially hit a native CUDA virtual-memory failure. It was stopped, and the working study pinned 2.1.4 after a separate H100 smoke check. Native jobs run in an isolated subprocess, preventing automatic replay of a full search after a native crash. After observing actual run times, later workers use a 1,800-second hard timeout (1,700 seconds for the child) and a US$2.10 full-timeout reservation, allowing more concurrent jobs within the same ceiling. On coordinator restart, every already submitted call is recovered by its ID before further work, preventing duplicate fits. A US$4.10 reservation remained in the budget guard for the earlier unrecovered task. It is a conservative guard, not an extra invoice item.

The lower-bound meter multiplies measured in-function allocation time by US$0.001097 per H100 second; it excludes pre-function startup, CPU, RAM, storage, and credits. The separate project-filtered Modal usage export in [compute record](results/data1/compute_usage.json) reports **US${billing.get('total_usd_before_credits',0):.2f}** gross resource usage before credits, including interrupted work and CPU/RAM/startup.

{billing_table}

The original scheduler targeted US$22 measured GPU work with a US$32 guarded GPU limit and **US$40** total ceiling. **The user then reported only US$1 of remaining Modal credit. All study apps were stopped and zero active tasks were confirmed.** This later instruction supersedes the earlier minimum-spend target: the completed-result timer remains below US$20, and no claim is made that it reached that target. Gross billed GPU usage is a separate measure. The final four higher-acceptance fits are interrupted, unavailable for inference, and not counted as successful results. All remaining analysis and verification runs on the desktop CPU. The budget-stop record disables further paid runs. Usage is not a claim about cash charged after credits.

GPU image: Python 3.12, NumPy 2.2.6, pandas 2.2.3, SciPy 1.15.3, scikit-learn 1.6.1, JAX 0.6.2, NumPyro 0.18.0, ArviZ 0.21.0, CatBoost 1.2.8, XGBoost 2.1.4. CPU reference analysis ran with Python 3.13 and the versions in requirements.txt. Seeded bootstrap checks are reproducible in the same numerical environment; GPU inference and tree fits can vary slightly across hardware/runtime versions.

## Reproduce and verify

Raw source files, extracted paper text, individual predictions, posterior arrays, browser profiles and full workspace billing exports are excluded from Git. Public tables contain aggregates, source hashes, diagnostics and sanitized run metadata. The original archive is never changed.

```powershell
# From the repository root, with the supplied archive and installed dependencies.
py -3.13 -m pip install -r research/requirements.txt
py -3.13 research/audit_archive.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/review_archive_text.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/audit_additional_tables.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/prepare_data.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/source_crosscheck.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/review_history.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/run_comparisons.py
# Modal SDK must be installed and authenticated in the chosen interpreter.
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; $env:NO_COLOR='1'
# Historical GPU invocation, disabled by the current compute_stop.json.
# Do not restart paid work under the current credit limit.
# python -m modal run --detach research/modal_study.py --stage full
py -3.13 research/check_numerics.py
py -3.13 research/verify_methods.py
py -3.13 research/summarize_data1.py
# Refresh project-filtered Modal billing (using an interpreter with Modal SDK).
py -3.13 research/billing_data1.py --modal-python <path-to-modal-python>
py -3.13 research/report_data1.py
py -3.13 research/export_site_data.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
# Publish reviewed files, wait for Pages to build, THEN verify the finished result.
py -3.13 research/check_site.py --url https://kevinyamada.github.io/wnba-shot-atlas/ --final
py -3.13 research/evaluate_predictions.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
```

Serving the website alone needs no raw data or Python analysis dependencies: run `python -m http.server 8001` from the root and open http://localhost:8001/.

The [final verification record](results/data1/final_verification.json) is generated after analysis and publication. It independently reopens all original archive members, reconstructs source labels and lagged features, checks metrics and cell aggregates, and compares the live data artifact with the verified local file. A final metadata-only commit may add that record; its `analysis_commit` identifies the analyzed implementation. Subsequent read-only checks verify the latest GitHub/Pages commit.

## Additional desktop modelling

The [desktop follow-up](LOCAL_FOLLOWUP.md) investigates the source disagreements using the files already in the archive, then compares a matched CPU refit with the original training cutoff and tests the effect of retaining disputed games in identity-free models. Those checks are separate from the frozen primary table and use no additional cloud GPU work.

## Research implications

The [desktop event-based possession-value extension](POSSESSION_VALUE.md) now reconstructs a strict subset of ordinary scoring episodes with free throws and offensive-rebound continuation, and compares CPU mean, Markov, spline and context models. Its source screening, rewards, timing and results are independently verified. This does not change the frozen primary shot comparison. Full spatial expected threat still requires validated nonshot action locations and outcomes absent from this archive. Real shot clock, defensive pressure and tracking are unavailable. The [research-group questions](DATA_REQUESTS.md) are a prepared draft only. The archive's papers inform methods and data requirements; none supplies additional model observations.
'''
    (HERE/'summary.md').write_text(report,encoding='utf-8')
    selected_dir=OUT/'experiments'/selection['selected_gp_id']
    (OUT/'gp_predictive_check.csv').write_bytes((selected_dir/'predictive_check.csv').read_bytes())
    print('REPORT_WRITTEN',selected,'late Brier',later.brier,'difference interval',ci.lower,ci.upper)


if __name__=='__main__':main()
