"""Report desktop modelling and internally checked source discrepancies."""
from pathlib import Path
from prose import clean_markdown
import json
import pandas as pd
from report_data1 import md

HERE=Path(__file__).resolve().parent
OUT=HERE/'results/data1/followup'


def main():
    metrics=pd.read_csv(OUT/'local_metrics.csv');paired=pd.read_csv(OUT/'local_game_bootstrap.csv')
    receipt=json.loads((OUT/'local_model_receipt.json').read_text(encoding='utf-8'))
    audit=json.loads((OUT/'archive_investigation.json').read_text(encoding='utf-8'))
    examples=pd.read_csv(OUT/'attempt_discrepancy_examples.csv')
    names=pd.read_csv(OUT/'unmatched_display_names.csv')
    text=pd.read_csv(OUT/'text_actor_disagreements.csv')
    cpu=paired[paired.split.eq('test')&paired.model.eq('CPU CatBoost refit')].iloc[0]
    hgb=paired[paired.split.eq('test')&paired.model.eq('Identity-free HGB included games')].iloc[0]
    cpu_playoff=paired[paired.split.eq('playoffs')&paired.model.eq('CPU CatBoost refit')].iloc[0]
    hgb_playoff=paired[paired.split.eq('playoffs')&paired.model.eq('Identity-free HGB included games')].iloc[0]
    report=f'''# Desktop follow up: source disagreements and additional models

All observations come from the accessible, unchanged **Data (1).zip**. Source SHA256: `{receipt['archive_sha256']}`. This follow up runs on the user's desktop CPU in the VS Code project checkout. It starts no Modal jobs and uses no external basketball data.

## What “source issues” means

The archive is readable. The issue is that some of its fields and files disagree. More access to the same archive does not identify which conflicting record is authoritative. We inspected the original events, both box files, and the overlapping well formed WNBA records in the parsed export.

For game `401736112`, original event shooter IDs give **Rhyne Howard 14 FGA** and **Te-Hina Paopao 6 FGA**. The supplied player boxes give **15 and 5**, respectively. Their makes and FG points agree. The archive gives no unique basis for deciding which of Paopao's recorded misses, if any, should be assigned to Howard. Neither version is silently corrected.

{md(examples[['game_id','athlete_display_name','event_attempts','field_goals_attempted','attempt_difference']])}

The full check still finds **18 player/game attempt differences across eight games**, while all 624 game/team FGA, FGM and FG point totals reconcile. Eight game exclusion is a conservative rule for player specific models; it does not mean every location or make/miss label in those games is unusable.

## Can another field or file resolve this internally?

{md(pd.DataFrame(audit['ordering']))}

`sequence_number` is numeric, but sorting by it produces more score update mismatches, not fewer. Sorting by period and game clock reproduces the export order count. These diagnostics compare each stored scoreboard update with the current row's recorded score value; they do not prove that every mismatch is an incorrect shot. Retrospective score corrections and inconsistent ordering remain possible. Score margin and possession sequences remain outside the primary model.

The parsed WNBA export contains two malformed records and college contamination. Its **118,109** well formed, matching 2025 original game rows have identical event text, first athlete ID and scored point value at the original game/play keys. It therefore supplies no independent correction to those fields. The parsed export stays outside modelling.

Among 42,193 field goals, the exact game/team roster name parser matches 42,171 descriptions and finds **one description/ID disagreement**:

{md(text[['source_row','game_id','game_play_number','athlete_id','box_name','text_name','text_id']])}

The other 22 descriptions use alternate first names relative to the box display names. They are parser nonmatches, not 22 established attribution errors:

{md(names)}

Names extracted from outcome descriptions are used only for this quality investigation, never as prediction features or automatic relabelling. Aggregate reconciliation alone cannot prove that every individual event is attributed correctly.

Explicit “three point” wording appears on 14,056 attempts and explicit “two point” wording on 8,729. Another **19,408** attempts have neither phrase. Some made threes are described merely as a running pullup or bank shot. Counting only explicit three point wording disagrees with supplied three point attempt totals in **484 game/team combinations**. Absence of the phrase is therefore not an authoritative two point label. The existing joint observed 0/2/3 model remains appropriate without guessing missed shot values.

## Additional desktop modelling

### Matched CPU reference and later cutoff refit

The three depth, regularization and tree count settings were frozen by the original GPU validation searches. For each seed, fit CatBoost on CPU through August 9 (25,751 attempts) and again through August 26 (31,746). Both CPU fits use the same algorithm, fixed tree counts, learning rate .035, Plain boosting and four threads. No later game early stopping or tuning occurs. Average the three seed predictions. The added validation games become training data for the refit, so no refit score is reported on those games.

This paired CPU comparison separates the effect of adding training games from CPU/GPU training differences. It is not a claim that CPU training reproduces the earlier GPU weights exactly. The frozen primary leaderboard and GP surface stay unchanged.

### Source exclusion sensitivity without shooter features

A separate HistGradientBoosting model uses only location, distance/angle, period, period clock, home status and team ID. It excludes shooter identity, names, player histories, outcome text, scoreboard/margin and inferred attempt values. Choose regularization from 5,20,80 on the existing 5,995 eligible validation attempts, with the same fixed capacity in every comparison (300 iterations, 15 leaves, depth limit 6, minimum leaf 100, 63 histogram bins, learning rate .05, no early stopping).

Then hold those settings fixed and compare training on the 25,751 eligible early attempts with training on all **26,686** early half court attempts. This adds **935 attempts in seven early games**, without relying on their uncertain shooter IDs. Both fits are scored on the same later game and playoff records. The eighth discrepant game contributes 134 separate validation attempts; those were not used for model selection. A bootstrap on that one game is degenerate and is explicitly not interpreted as a confidence interval.

### Later game results: identical 5,626 attempts

{md(metrics[metrics.split.eq('test')][['model','shots','brier','log_loss','auc']])}

### Playoffs: identical 3,311 attempts

{md(metrics[metrics.split.eq('playoffs')][['model','shots','brier','log_loss','auc']])}

### Paired game bootstrap changes

Negative differences favor the first model. Resample whole games 2,000 times; compare paired per shot Brier errors.

{md(paired[paired.split.isin(['test','playoffs'])][['split','model','baseline','brier_difference','lower','upper']])}

The later cutoff CPU CatBoost refit changes later game Brier by **{cpu.brier_difference:+.6f}**, with 95% game bootstrap interval **[{cpu.lower:.6f}, {cpu.upper:.6f}]**. It does not demonstrate improvement over its matched CPU reference. Including the seven player count discrepant training games changes the identity free model's later game Brier by **{hgb.brier_difference:+.6f}**, interval **[{hgb.lower:.6f}, {hgb.upper:.6f}]**. Its effect in this benchmark is small. This does not identify the correct shooter for any disputed attempt or prove that all source problems are harmless.

On the playoff sample, the CPU refit changes Brier by **{cpu_playoff.brier_difference:+.6f}**, interval **[{cpu_playoff.lower:.6f}, {cpu_playoff.upper:.6f}]**. Including the disputed early games in the identity free model changes playoff Brier by **{hgb_playoff.brier_difference:+.6f}**, interval **[{hgb_playoff.lower:.6f}, {hgb_playoff.upper:.6f}]**. Both playoff intervals are below zero, while the regular season intervals include zero. The benefit is therefore not uniform across evaluation periods. These conditional intervals do not include model selection uncertainty, and the exploratory comparisons are not adjusted for multiplicity.

These checks give no reason to promote a new primary model by choosing the best result on an already examined sample. They are sensitivity studies on reused 2025 data. Model complexity, a different training cutoff or additional fitting alone does not establish a general improvement. All current archive modelling requested in this follow up is completed locally; further GPU spending is unnecessary for these checks.

## Reproduce locally

Use the **WNBA: desktop CPU follow up** task in VS Code, or:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
py -3.13 -m pip install -r research/requirements.txt
py -3.13 research/investigate_archive.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/local_followup.py --source "$env:USERPROFILE\\Downloads\\Data (1).zip"
py -3.13 research/report_local_followup.py
```

Runtime: Python {receipt['python']}, CatBoost {receipt['catboost']}, scikit-learn {receipt['scikit_learn']}, four CPU threads. Completed in {receipt['elapsed_seconds']:.1f} seconds on this desktop. Saved local model weights and individual predictions stay in ignored `research/data/`. [Run receipt](results/data1/followup/local_model_receipt.json), [metrics](results/data1/followup/local_metrics.csv), [bootstrap comparisons](results/data1/followup/local_game_bootstrap.csv) and [source investigation](results/data1/followup/archive_investigation.json) remain reviewable. Final verification is rerun after publishing this follow up.
'''
    (HERE/'LOCAL_FOLLOWUP.md').write_text(clean_markdown(report),encoding='utf-8')
    print('LOCAL_FOLLOWUP_REPORT_WRITTEN',cpu.brier_difference,hgb.brier_difference)


if __name__=='__main__':main()
