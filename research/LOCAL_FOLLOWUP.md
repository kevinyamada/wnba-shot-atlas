# Desktop follow up: source disagreements and additional models

All observations come from the accessible, unchanged **Data (1).zip**. Source SHA256: `22a86860e179ce40ed34648c592bbd384297ddd5833000117973308a915a2120`. This follow up runs on the user's desktop CPU in the VS Code project checkout. It starts no Modal jobs and uses no external basketball data.

## What “source issues” means

The archive is readable. The issue is that some of its fields and files disagree. More access to the same archive does not identify which conflicting record is authoritative. We inspected the original events, both box files, and the overlapping well formed WNBA records in the parsed export.

For game `401736112`, original event shooter IDs give **Rhyne Howard 14 FGA** and **Te-Hina Paopao 6 FGA**. The supplied player boxes give **15 and 5**, respectively. Their makes and FG points agree. The archive gives no unique basis for deciding which of Paopao's recorded misses, if any, should be assigned to Howard. Neither version is silently corrected.

| game_id | athlete_display_name | event_attempts | field_goals_attempted | attempt_difference |
| --- | --- | --- | --- | --- |
| 401736112 | Rhyne Howard | 14 | 15.000000 | -1.000000 |
| 401736112 | Te-Hina Paopao | 6 | 5.000000 | 1.000000 |
| 401736137 | Jackie Young | 11 | 10.000000 | 1.000000 |
| 401736137 | Dana Evans | 7 | 8.000000 | -1.000000 |
| 401736145 | Myisha Hines-Allen | 9 | 8.000000 | 1.000000 |
| 401736145 | NaLyssa Smith | 3 | 4.000000 | -1.000000 |
| 401736155 | Courtney Williams | 17 | 16.000000 | 1.000000 |
| 401736155 | Natisha Hiedeman | 6 | 7.000000 | -1.000000 |
| 401736217 | Chelsea Gray | 11 | 10.000000 | 1.000000 |
| 401736217 | A'ja Wilson | 19 | 20.000000 | -1.000000 |
| 401736217 | Jackie Young | 9 | 8.000000 | 1.000000 |
| 401736217 | Dana Evans | 2 | 3.000000 | -1.000000 |
| 401736227 | Dana Evans | 11 | 10.000000 | 1.000000 |
| 401736227 | Kierstan Bell | 4 | 5.000000 | -1.000000 |
| 401736274 | Alyssa Thomas | 17 | 18.000000 | -1.000000 |
| 401736274 | Monique Akoa Makani | 11 | 10.000000 | 1.000000 |
| 401736355 | Kahleah Copper | 16 | 15.000000 | 1.000000 |
| 401736355 | Satou Sabally | 10 | 11.000000 | -1.000000 |

The full check still finds **18 player/game attempt differences across eight games**, while all 624 game/team FGA, FGM and FG point totals reconcile. Eight game exclusion is a conservative rule for player specific models; it does not mean every location or make/miss label in those games is unusable.

## Can another field or file resolve this internally?

| order | duplicate_game_sort_keys | all_event_score_conflicts | field_goal_score_conflicts | team_specific_score_conflicts | affected_games |
| --- | --- | --- | --- | --- | --- |
| export order | 0 | 165 | 88 | 165 | 39 |
| sequence number | 0 | 1318 | 393 | 1318 | 238 |
| period and clock | 0 | 165 | 88 | 165 | 39 |

`sequence_number` is numeric, but sorting by it produces more score update mismatches, not fewer. Sorting by period and game clock reproduces the export order count. These diagnostics compare each stored scoreboard update with the current row's recorded score value; they do not prove that every mismatch is an incorrect shot. Retrospective score corrections and inconsistent ordering remain possible. Score margin and possession sequences remain outside the primary model.

The parsed WNBA export contains two malformed records and college contamination. Its **118,109** well formed, matching 2025 original game rows have identical event text, first athlete ID and scored point value at the original game/play keys. It therefore supplies no independent correction to those fields. The parsed export stays outside modelling.

Among 42,193 field goals, the exact game/team roster name parser matches 42,171 descriptions and finds **one description/ID disagreement**:

| source_row | game_id | game_play_number | athlete_id | box_name | text_name | text_id |
| --- | --- | --- | --- | --- | --- | --- |
| 19889 | 401736371 | 43 | 4433630 | Rickea Jackson | Cameron Brink | 4433404.000000 |

The other 22 descriptions use alternate first names relative to the box display names. They are parser nonmatches, not 22 established attribution errors:

| athlete_id | box_name | text_name | records |
| --- | --- | --- | --- |
| 4399342 | Lexi Held | Alexa Held | 18 |
| 5279789 | Mamignan Toure | Migna Toure | 4 |

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

| model | shots | brier | log_loss | auc |
| --- | --- | --- | --- | --- |
| CPU CatBoost reference | 5626 | 0.232557 | 0.657610 | 0.633814 |
| CPU CatBoost refit | 5626 | 0.232582 | 0.657650 | 0.633899 |
| Distance reference | 5626 | 0.233794 | 0.660248 | 0.622539 |
| Distance refit | 5626 | 0.233814 | 0.660294 | 0.622539 |
| Identity free HGB excluded games | 5626 | 0.233371 | 0.659587 | 0.630327 |
| Identity free HGB included games | 5626 | 0.233369 | 0.659616 | 0.629961 |

### Playoffs: identical 3,311 attempts

| model | shots | brier | log_loss | auc |
| --- | --- | --- | --- | --- |
| CPU CatBoost reference | 3311 | 0.231721 | 0.655975 | 0.632979 |
| CPU CatBoost refit | 3311 | 0.231293 | 0.655055 | 0.633182 |
| Distance reference | 3311 | 0.232965 | 0.658571 | 0.620093 |
| Distance refit | 3311 | 0.233054 | 0.658762 | 0.620093 |
| Identity free HGB excluded games | 3311 | 0.234690 | 0.662536 | 0.623548 |
| Identity free HGB included games | 3311 | 0.234189 | 0.661510 | 0.624493 |

### Paired game bootstrap changes

Negative differences favor the first model. Resample whole games 2,000 times; compare paired per shot Brier errors.

| split | model | baseline | brier_difference | lower | upper |
| --- | --- | --- | --- | --- | --- |
| test | CPU CatBoost refit | CPU CatBoost reference | 0.000024 | -0.000263 | 0.000314 |
| test | Distance refit | Distance reference | 0.000020 | -0.000101 | 0.000135 |
| test | Identity free HGB included games | Identity free HGB excluded games | -0.000002 | -0.000512 | 0.000477 |
| playoffs | CPU CatBoost refit | CPU CatBoost reference | -0.000428 | -0.000756 | -0.000102 |
| playoffs | Distance refit | Distance reference | 0.000090 | -0.000034 | 0.000207 |
| playoffs | Identity free HGB included games | Identity free HGB excluded games | -0.000500 | -0.001024 | -0.000004 |

The later cutoff CPU CatBoost refit changes later game Brier by **+0.000024**, with 95% game bootstrap interval **[-0.000263, 0.000314]**. It does not demonstrate improvement over its matched CPU reference. Including the seven player count discrepant training games changes the identity free model's later game Brier by **-0.000002**, interval **[-0.000512, 0.000477]**. Its effect in this benchmark is small. This does not identify the correct shooter for any disputed attempt or prove that all source problems are harmless.

On the playoff sample, the CPU refit changes Brier by **-0.000428**, interval **[-0.000756, -0.000102]**. Including the disputed early games in the identity free model changes playoff Brier by **-0.000500**, interval **[-0.001024, -0.000004]**. Both playoff intervals are below zero, while the regular season intervals include zero. The benefit is therefore not uniform across evaluation periods. These conditional intervals do not include model selection uncertainty, and the exploratory comparisons are not adjusted for multiplicity.

These checks give no reason to promote a new primary model by choosing the best result on an already examined sample. They are sensitivity studies on reused 2025 data. Model complexity, a different training cutoff or additional fitting alone does not establish a general improvement. All current archive modelling requested in this follow up is completed locally; further GPU spending is unnecessary for these checks.

## Reproduce locally

Use the **WNBA: desktop CPU follow up** task in VS Code, or:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
py -3.13 -m pip install -r research/requirements.txt
py -3.13 research/investigate_archive.py --source "$env:USERPROFILE\Downloads\Data (1).zip"
py -3.13 research/local_followup.py --source "$env:USERPROFILE\Downloads\Data (1).zip"
py -3.13 research/report_local_followup.py
```

Runtime: Python 3.13.5, CatBoost 1.2.10, scikit-learn 1.9.1, four CPU threads. Completed in 93.9 seconds on this desktop. Saved local model weights and individual predictions stay in ignored `research/data/`. [Run receipt](results/data1/followup/local_model_receipt.json), [metrics](results/data1/followup/local_metrics.csv), [bootstrap comparisons](results/data1/followup/local_game_bootstrap.csv) and [source investigation](results/data1/followup/archive_investigation.json) remain reviewable. Final verification is rerun after publishing this follow up.
