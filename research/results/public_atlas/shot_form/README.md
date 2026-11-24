# What shot type adds to distance

From 3.5 feet up to 4.5 feet, players made 11,001 of 20,850 (52.8%) layups and 1,056 of 2,918 (36.2%) jump shots. Giving both groups the same mix of court spots, seasons and game types produced make rates of 49.5% and 40.9% across 136 shared groups.

On 353,293 shots in 2,595 future games across 11 season tests, adding the recorded shot type reduced Brier error by 0.19%. The paired 95% interval was 0.14% to 0.24%. Average error fell in 9 of 11 regular seasons and 10 of 11 playoffs.

| Test | Attempts | Distance Brier | With shot type | Relative drop in error | 95% interval |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Regular | 325,806 | 0.231809 | 0.231389 | 0.18% | 0.13% to 0.23% |
| Playoffs | 27,487 | 0.233038 | 0.232370 | 0.29% | 0.14% to 0.44% |

## How the comparison works

The first training season is 2013, when the current three point arc began. Each test from 2016 through 2026 uses the preceding three regular seasons for training. Both models see the same eligible shots in each test season. A shot needs verified coordinates on the attacking half and matching attempt, make and field goal point totals for both teams in its game. The coverage table accounts separately for each exclusion.

The distance model estimates make rate on a quarter foot grid. A Gaussian kernel with a one foot bandwidth gives nearer training shots more weight. Each estimate also borrows four attempts at the overall training rate. The second model estimates the same curve separately for each recorded shot family and borrows 50 attempts at the distance rate. A type with little evidence stays close to the distance estimate. A missing or generic label gets the distance estimate directly. Only the recorded action name determines the family. Descriptions, scoring flags, awarded points and assists never enter the predictors.

The primary score is the mean squared error of the predicted make chance (Brier score). Relative reduction is 100 times one minus the ratio of the two Brier scores. Intervals use 2,000 paired resamples of whole games within each season and phase, conditional on the fitted curves. The analysis uses previously examined public seasons. A future season would provide a prospective check.

Across bandwidths of 0.5, 1 and 2 feet and prior counts of 20, 50 and 100 varied one at a time, the pooled reduction ranged from 0.14% to 0.22%. Log loss and calibration bins are available with the scores.

The figure rounds each recorded distance to the nearest whole foot, grouping the lower bound inclusively and the upper bound exclusively. The shared spot check keeps only season, phase and exact coordinate combinations with at least five layups and five jumpers. It weights each combination by the product of the two counts divided by their sum. These observations describe shots players took. Defense, shot selection and the way scorers assign shot types can affect the comparison.

## A model that already knows the shooter

The earlier context model uses court location, player, team, game clock and the shooter’s prior record. Both versions use the same 2022 to 2024 training attempts and the same tree depth chosen in 2025. The extension adds the shot family with all other settings held fixed. The baseline reproduces the original saved probabilities within one millionth. Here the denominator for the percentage change is the context model’s Brier score.

| 2026 games | Shots | Context Brier | With type | Relative drop in error | 95% interval |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Playoffs | 2,927 | 0.228443 | 0.228436 | 0.00% | -0.22% to 0.23% |
| Regular | 44,478 | 0.229341 | 0.228833 | 0.22% | 0.14% to 0.31% |

## Agreement between the two feeds

Across 2025 and 2026, 86,774 attempts linked uniquely out of 90,087 ESPN attempts and 90,086 WNBA Stats attempts. The shot family agreed for 84,604 (97.50%) and the make or miss agreed for 86,774.

An event must have the same game, period, team side, clock to the recorded hundredth and uniquely mapped shooter in both releases. Duplicate keys are excluded on both sides. Type, result and coordinates play no part in matching. A second check substitutes the WNBA Stats type on the same linked evaluation shots while holding the ESPN location, model and observed result fixed. The releases cover the same games and can share underlying scoring decisions. They do not supply tracking data or defense at release.

A sensitivity check harmonizes three literal WNBA names after reviewing the recorded terms. Tip Layup Shot is treated as a tip. Turnaround Fadeaway shot and Fadeaway Bank shot are treated as jump shots. This brings agreement to 86,343 of 86,774 (99.50%). Other bank shots with unspecified form keep the original coding. This naming check changes only the second source comparison.

| Matched test shots | Attempts | ESPN reduction | WNBA Stats reduction | WNBA with aliases |
| :--- | ---: | ---: | ---: | ---: |
| 2025 playoffs | 3,258 | 0.23% | 0.21% | 0.22% |
| 2025 regular | 35,454 | 0.27% | 0.23% | 0.28% |
| 2026 playoffs | 2,916 | 0.18% | -0.00% | 0.18% |
| 2026 regular | 44,812 | 0.25% | 0.18% | 0.24% |

## Supporting tables

[Season scores](by_season.csv) · [Training windows](training_windows.csv) · [Coverage](coverage.csv) · [Shot families](families.csv) · [Shared spots](matched_spots.csv) · [Calibration](calibration.csv) · [Sensitivity](sensitivity.csv) · [Context comparison](context.csv) · [Event matching](provider_coverage.csv) · [Source agreement by result](provider_agreement.csv) · [Family disagreements](provider_confusion.csv) · [Recorded labels](label_differences.csv) · [Scores using both sources](provider_scores.csv)
