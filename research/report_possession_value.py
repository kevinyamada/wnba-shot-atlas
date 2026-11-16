"""Render the audited desktop EPV results without adding observations."""
from pathlib import Path
from prose import clean_markdown
import json
import pandas as pd

HERE=Path(__file__).resolve().parent;OUT=HERE/'results/data1/possession'


def table(a):
    def fmt(v):return f'{v:.6f}' if isinstance(v,float) else str(v)
    return '| '+' | '.join(a.columns)+' |\n| '+' | '.join(['---']*len(a.columns))+' |\n'+'\n'.join('| '+' | '.join(fmt(v) for v in row)+' |' for row in a.itertuples(index=False,name=None))


def main():
    a=json.loads((OUT/'reconstruction_audit.json').read_text(encoding='utf-8'));s=json.loads((OUT/'model_selection_receipt.json').read_text(encoding='utf-8'))
    d=json.loads((OUT/'markov_diagnostics.json').read_text(encoding='utf-8'));metrics=pd.read_csv(OUT/'metrics.csv');boot=pd.read_csv(OUT/'game_bootstrap.csv')
    cohorts=pd.read_csv(OUT/'state_summary.csv');entry=metrics[metrics.stage.eq('entry')][['split','model','states','games','rmse','mae','mean_prediction','mean_observed']]
    pair=boot[boot.stage.eq('entry')&boot.model.isin([s['selected_model'],'Markov EPV'])][['split','model','mse_difference','lower','upper']]
    text=f'''# Event based possession value: source limited prototype

This extension estimates **remaining recorded ordinary points in a reconstructed control episode** at its entry, after a missed field goal, or after a live offensive rebound. It is a coarse expected possession value (EPV) model. It does not estimate spatial expected threat (xT), pass values, player skill, or the causal effect of choosing an action. All basketball observations come exclusively from **Data (1).zip**, SHA256 `{a['archive_sha256']}`. Computation ran on the user's desktop CPU in the VS Code checkout; no additional Modal work was used. The primary shot model comparison remains fixed.

## Source reconciliation and coverage

The original 2025 event table has {a['events']:,} records in {a['games']} games. Recorded scoring values, including free throws, independently match **all 624 supplied game/team final scores**. The ledger conserves **{a['ordinary_episode_points']:,} ordinary points + {a['special_free_throw_points']} special free throw points = 51,073**. Scoreboard differences do not supply the reward target.

There are {a['episodes']:,} inferred episodes before exclusions. These are computational control episodes, not an official count of statistical possessions: administration, empty period end intervals, and uncertain transitions can create additional ledger episodes. Sixteen eligible intervals end at a jump ball change without an intermediate assigned event; one follows a turnover at the same clock. Their recorded reward is zero, but an official separate possession is not established. These intervals remain visible rather than being relabelled with invented actions. No authoritative possession IDs are provided. Correct total rewards do not establish every real boundary.

Strict screening retains **{a['clean_periods']} of {a['periods']} periods ({100*a['clean_periods']/a['periods']:.1f}%)**, yielding **{a['eligible_entry_states']:,} episode entry states** and **{a['eligible_states']:,} total model states**. Whole periods are excluded for inconsistent score snapshots or cumulative scores, special retention/technical/flagrant/take foul windows, overturned reviews, uncertain jump ball winners, invalid clocks, or missing period ends. Individually uncertain or incomplete episodes are also excluded. State clocks must exceed two seconds. This is a retrospectively source qualified subset; quality and completeness are not guaranteed when predicting a new live event. It is not representative of all league possessions by construction.

The jump ball team field is checked against the explicit winner name or the third actor's team in the supplied game roster. **{a['validated_jump_ball_winner_rows']} of {a['jump_ball_winner_rows']}** have confirming evidence. The remaining 61 lack both usable evidence fields; their periods remain excluded. Team level EPV uses neither shooter identity nor player histories, so the eight disputed shooter attribution games are not automatically excluded here. A period from such a game must independently pass these control and score checks. The primary player context shot models still exclude all eight.

{table(cohorts)}

## Reconstruction rules

- A defensive rebound, ordinary turnover, confirmed jump ball change, completed made field goal, or made final ordinary free throw can anchor the next episode. Initial period ownership inferred without an anchor is excluded.
- A missed field goal keeps the current episode open. A live offensive rebound continues it. A dead ball rebound between nonfinal free throws does not create a new live offensive rebound state.
- A made basket is held pending through same clock administration so a same team ordinary one of one free throw can join its and one sequence. A missed final free throw waits for the rebound; an offensive rebound can extend the episode again.
- Offensive fouls do not duplicate the separately recorded turnover. Special free throws are recorded once in a separate reward lane and never treated as an ordinary automatic change of control. Their periods are excluded from fitting.
- Period ends terminate the ledger episode. Unexplained ownership changes, incomplete/overlapping free throw sequences and conflicting rebound ownership are flagged, not silently repaired.

An episode can legitimately exceed four points. In game **401736170, period 4**, Chicago gains a defensive team rebound at 4:58, misses a layup at 4:38, retrieves the rebound at 4:37, makes two points at 4:36, misses its and one free throw, retrieves the rebound at 4:33, then makes three at 4:26. This is five ordinary points within one continuing episode (original CSV rows **98512 to 98520**). Two other clean five point traces were inspected: game 401736231 period 3 and game 401736340 period 1. Rewards are not capped to force a convenient distribution.

## Predictors and timing

Features are restricted to `{', '.join(s['features'])}`. A post miss or post rebound state knows that already recorded event. The label includes only scoring recorded later in the same episode. Score margin is the prefix sum of prior recorded points; every retained state's margin agrees with the archive scoreboard at its anchor. Episode entry features are captured at the boundary before the next action, not from the next action's future clock or outcome. Actual game truncated prefix checks and synthetic scenarios test this timing independently.

There is no true shot clock, pass completion log, movement endpoint, defensive pressure, player tracking, or trustworthy nonshot spatial coordinate in the model. The period clock is not described as a shot clock. No future episode duration, terminal action, total reward, quality flag, actor ID, or event text enters the feature allowlist. All three state types are pooled in fitting with state type observed as a predictor; their correlated rows are evaluated separately and bootstrapped by whole game.

## Models and frozen selection

Training ends August 9, 2025. August 10 to 26 entry state mean squared error selects settings and the model family. Later regular games and playoffs are scored only after this choice is written to the selection receipt. The archive's 2025 benchmark periods have already been examined in previous work; these are **reused chronological benchmarks**, not a fresh season or an untouched final test. No additional season is needed for this limited implementation, but a genuinely new season evaluation requires new supplied WNBA data.

The baseline is the training mean for each state type. A shrunk empirical state mean and Markov model group by state type, entry start reason, period clock interval and home/away. Clock boundaries are 2, 5, 24, 60, 120, 300 and 601 seconds. The Poisson spline uses clock splines and the other allowed context. Context boosting uses Poisson loss with CPU histogram trees; its four depth/penalty candidates use 300 trees, learning rate 0.04 and minimum leaf size 100. The Poisson objective is a nonnegative conditional mean fitting loss; it does not assert that bounded, dependent basketball scores follow a Poisson distribution. No distributional prediction intervals are claimed.

**{s['selected_model']}** was selected on validation entry MSE, using **{s['selected_settings'][s['selected_model']]}**. All settings and software versions are in the [selection receipt](results/data1/possession/model_selection_receipt.json). Total CPU fitting and evaluation time was {s['elapsed_seconds']:.1f} seconds. The explicit Markov model remains visible for interpretability; its better later game score does not replace the validation selected family.

For the Markov model, each selected event state leads to the next selected state in that episode, with the intervening observed reward; the last leads to an absorbing terminal state. The fitted equation is **V = r + PV**, solved as **V = (I − P)⁻¹r**. A positive absorbing pseudocount regularizes each row toward its training state type mean. It is a modelling prior, not an extra observed basketball transition. Selected alpha is {d['alpha']:.0f}; the model has {d['states']} states, spectral radius {d['transition_spectral_radius']:.6f}, maximum Bellman residual {d['bellman_residual_max']:.3g}, positive absorption in every row, and finite nonnegative values. Independent transition reconstruction and iterative value iteration verify the linear solve.

## Entry state results

Lower RMSE/MAE is better. These are errors in remaining ordinary points, not shooting probability scores.

{table(entry)}

Paired differences below are model MSE minus the training stage mean baseline; intervals resample whole games 2,000 times. They describe uncertainty conditional on this screened cohort. They do not cover reconstruction uncertainty, selection uncertainty, source error bias, or a new season.

{table(pair)}

The selected context model's later game and playoff intervals include zero. It does not establish a reliable improvement over the simple baseline. The Markov comparison improves on the baseline in the later regular subset, while its playoff interval includes zero; this is a descriptive secondary comparison on reused data. No winner is chosen from these later results. [All state type metrics](results/data1/possession/metrics.csv), [calibration bins](results/data1/possession/calibration.csv), [game intervals](results/data1/possession/game_bootstrap.csv), and [clock bin aggregates](results/data1/possession/value_summary.csv) are public. Mean curves are observed cohort aggregates, not counterfactual forecasts for changing the clock or choosing another action. Sparse bins are labelled with their sample size; no uncertainty band is invented.

## What this supports

This completes a reproducible, audited **event based EPV prototype** with normal free throws and offensive rebound continuation. It supports conditional remaining point estimates at recorded event states. It cannot assign reliable value to unrecorded passes or movement, estimate a spatial transition policy, or allocate causal action credit to individual players. Full spatial xT requires validated nonshot action locations and outcomes that this archive does not contain. Tracking is one possible richer source, but is not claimed to be required by every xT formulation.

Method references only: [Cervone et al., *A Multiresolution Stochastic Process Model for Predicting Basketball Possession Outcomes*](https://arxiv.org/abs/1408.0777) motivates EPV; its optical tracking framework is not reproduced here. [Karun Singh's xT explanation](https://karun.in/blog/expected-threat.html) uses spatial action transitions absent from this archive. [NBA statistical glossary](https://www.nba.com/stats/help/glossary): offensive rebounds extend the same statistical possession. [FIBA statisticians' manual](https://assets.fiba.basketball/image/upload/documents-corporate-fiba-statisticians-manual-2024-v2.pdf) and [pbpstats boundary implementation](https://pbpstats.readthedocs.io/en/latest/_modules/pbpstats/resources/possessions/possession.html) inform boundary caveats. These references provide no additional model observations, corrected scores, or official possession labels.

## Reproduce and verify on the desktop

Use Python 3.13 with the recorded CPU dependencies, in the VS Code checkout:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
py -3.13 research/possession_reconstruction.py --source "$env:USERPROFILE/Downloads/Data (1).zip"
py -3.13 -c "import sys; sys.path.insert(0,'research'); import possession_models; possession_models.main()"
py -3.13 research/report_possession_value.py
py -3.13 research/publish_data1.py --source "$env:USERPROFILE/Downloads/Data (1).zip"
py -3.13 research/verify_possession_value.py --source "$env:USERPROFILE/Downloads/Data (1).zip" --final
```

The final verifier runs after publication and the primary source and desktop follow up checks. It rereads the ZIP, checks every ledger reward, every retained target, prefix feature timing, chronological splits, all metrics/intervals, saved model inference, the Markov transition matrix and value iteration, published aggregates and live asset bytes. Eight synthetic scenarios check difficult free throw and rebound cases without adding observations. [Final EPV verification](results/data1/possession/final_possession_verification.json). Raw events, per state predictions and saved weights remain in ignored `research/data/`.
'''
    text+='\n## Subsequent recovery extension\n\nThe [ordinary-tail recovery study](RECOVERY.md) now adds qualified states after a period’s final hazardous event and a corroborated live restart. It retains all original states and artifacts, compares fixed-setting CPU refits, and checks a stricter second restart. The counts and model table in this original report remain the frozen strict reference. The [meeting walkthrough](https://kevinyamada.github.io/wnba-shot-atlas/meeting/) presents both scopes.\n'
    (HERE/'POSSESSION_VALUE.md').write_text(clean_markdown(text),encoding='utf-8')
    print('WROTE_POSSESSION_REPORT',flush=True)


if __name__=='__main__':main()
