# What the public WNBA data show

[Season by season data review](eda.md)

## Shot predictions across seasons

Regular season games in 2022 through 2024 train the models. The 2025 regular season chooses model settings by log loss. The 2026 regular season and the 2026 playoffs are scored separately with settings fixed. Earlier games on the same date cannot affect a shooter's history. Models use the same mapped attempts with usable clocks and reconciled team and player counts. The data have already been used for descriptive work, and the final season is an out of time comparison.

The model with the lowest 2025 log loss is **XGBoost context**. Results include Brier score, log loss and calibration. Smaller errors are better. Paired intervals resample whole games with all their attempts.

| split | model | attempts | brier | log_loss | auc |
| --- | --- | --- | --- | --- | --- |
| playoffs | Calibrated average | 2927 | 0.22838 | 0.64900 | 0.62430 |
| playoffs | Five model average | 2927 | 0.22840 | 0.64906 | 0.62430 |
| playoffs | XGBoost context | 2927 | 0.22844 | 0.64902 | 0.62912 |
| playoffs | Joint boosted make probability | 2927 | 0.22867 | 0.64958 | 0.62522 |
| playoffs | CatBoost spatial | 2927 | 0.22876 | 0.64965 | 0.61730 |
| playoffs | Matérn GP | 2927 | 0.22901 | 0.65031 | 0.61903 |
| playoffs | XGBoost spatial | 2927 | 0.22916 | 0.65057 | 0.61708 |
| playoffs | SPDE | 2927 | 0.22933 | 0.65102 | 0.61616 |
| playoffs | Universal kriging | 2927 | 0.22975 | 0.65190 | 0.61679 |
| playoffs | Ordinary kriging | 2927 | 0.22978 | 0.65198 | 0.61653 |
| playoffs | IDW | 2927 | 0.23005 | 0.65254 | 0.61649 |
| playoffs | Context logistic | 2927 | 0.23032 | 0.65303 | 0.62387 |
| playoffs | Distance baseline | 2927 | 0.23041 | 0.65335 | 0.60597 |
| playoffs | CatBoost context | 2927 | 0.23042 | 0.65315 | 0.61638 |
| playoffs | Spatial logistic | 2927 | 0.23085 | 0.65409 | 0.60743 |
| playoffs | Joint logistic make probability | 2927 | 0.23214 | 0.65957 | 0.62336 |
| playoffs | Constant baseline | 2927 | 0.24358 | 0.68026 | 0.50000 |
| test | XGBoost context | 44478 | 0.22934 | 0.65068 | 0.64856 |
| test | Calibrated average | 44478 | 0.22954 | 0.65125 | 0.64747 |
| test | Joint boosted make probability | 44478 | 0.22968 | 0.65146 | 0.64732 |
| test | Five model average | 44478 | 0.22970 | 0.65161 | 0.64747 |
| test | CatBoost context | 44478 | 0.23029 | 0.65272 | 0.64363 |
| test | CatBoost spatial | 44478 | 0.23072 | 0.65377 | 0.64066 |
| test | Matérn GP | 44478 | 0.23073 | 0.65385 | 0.64059 |
| test | SPDE | 44478 | 0.23085 | 0.65410 | 0.64040 |
| test | Universal kriging | 44478 | 0.23089 | 0.65425 | 0.64020 |
| test | Ordinary kriging | 44478 | 0.23090 | 0.65426 | 0.64032 |
| test | XGBoost spatial | 44478 | 0.23109 | 0.65461 | 0.63685 |
| test | IDW | 44478 | 0.23129 | 0.65512 | 0.63787 |
| test | Distance baseline | 44478 | 0.23160 | 0.65574 | 0.63509 |
| test | Spatial logistic | 44478 | 0.23164 | 0.65578 | 0.63801 |
| test | Context logistic | 44478 | 0.23185 | 0.65622 | 0.64105 |
| test | Joint logistic make probability | 44478 | 0.23481 | 0.66406 | 0.63608 |
| test | Constant baseline | 44478 | 0.24803 | 0.68920 | 0.50000 |

The field goal points comparison predicts the probabilities of 0, 2 or 3 points, then multiplies those probabilities by their values. A missed shot always contributes zero points. Court geometry is not used to assign an official attempt value to a miss.

| split | model | attempts | rmse | mae |
| --- | --- | --- | --- | --- |
| validation | Constant outcomes | 37372 | 1.16825 | 1.12096 |
| validation | Distance outcomes | 37372 | 1.15357 | 1.08900 |
| validation | Joint logistic | 37372 | 1.15764 | 1.07698 |
| validation | Joint boosted | 37372 | 1.14995 | 1.08015 |
| test | Constant outcomes | 44478 | 1.17505 | 1.12630 |
| test | Distance outcomes | 44478 | 1.15859 | 1.09202 |
| test | Joint logistic | 44478 | 1.16757 | 1.07773 |
| test | Joint boosted | 44478 | 1.15491 | 1.08255 |
| playoffs | Constant outcomes | 2927 | 1.17904 | 1.12929 |
| playoffs | Distance outcomes | 2927 | 1.16088 | 1.09397 |
| playoffs | Joint logistic | 2927 | 1.16765 | 1.07055 |
| playoffs | Joint boosted | 2927 | 1.15613 | 1.08037 |

The shot type tables from the same runs score models on jump shots, layups and other recorded types. Those categories were used for evaluation. They were not supplied as predictors in the benchmark.

## Prediction in unfamiliar court areas

The four regions divide the court at 16 feet forward and down its centre. Each region is held out once. Training points are removed within 0, 2 or 4 feet of observed test locations. The same attempts are tested with every buffer.

| buffer_ft | model | attempts | brier | log_loss |
| --- | --- | --- | --- | --- |
| 0 | Distance baseline | 92055 | 0.23182 | 0.65626 |
| 0 | SPDE | 92055 | 0.23276 | 0.65828 |
| 0 | Universal kriging | 92055 | 0.23396 | 0.66049 |
| 0 | Matérn GP | 92055 | 0.23459 | 0.66225 |
| 0 | IDW | 92055 | 0.23461 | 0.66195 |
| 0 | Ordinary kriging | 92055 | 0.23588 | 0.66443 |
| 0 | Spatial logistic | 92055 | 0.26923 | 0.75090 |
| 2 | Distance baseline | 92055 | 0.23253 | 0.65775 |
| 2 | Universal kriging | 92055 | 0.23591 | 0.66460 |
| 2 | SPDE | 92055 | 0.23715 | 0.66736 |
| 2 | Ordinary kriging | 92055 | 0.23751 | 0.66782 |
| 2 | IDW | 92055 | 0.24082 | 0.67448 |
| 2 | Matérn GP | 92055 | 0.24269 | 0.68052 |
| 2 | Spatial logistic | 92055 | 0.24457 | 0.68365 |
| 4 | Matérn GP | 92055 | 0.24312 | 0.67960 |
| 4 | Ordinary kriging | 92055 | 0.25092 | 0.69538 |
| 4 | IDW | 92055 | 0.25160 | 0.69692 |
| 4 | Spatial logistic | 92055 | 0.25254 | 0.69878 |
| 4 | Universal kriging | 92055 | 0.25351 | 0.70116 |
| 4 | Distance baseline | 92055 | 0.25412 | 0.70229 |
| 4 | SPDE | 92055 | 0.25746 | 0.71019 |

The spatial methods reuse inverse distance weighting, ordinary and universal kriging, and the finite element SPDE model. The Matérn model uses a finite spectral basis and a conditional Laplace approximation on CPU. The SPDE report checks finer meshes with the fitted range and variance fixed. The refit checks add 2025 training games or include games with disputed shooter counts in a model that does not use shooter identity.

## What happens after a miss

The sequence reconstruction uses public play by play and checks the scoreboard, team boxes, play order and control changes. The sample covers clean sequences from 2022 to 2026. The rebound flow counts a miss followed by an offensive rebound as the next relevant event within the same sequence.

| year | split | rebound | misses | later_points | scored_after |
| --- | --- | --- | --- | --- | --- |
| 2025 | validation | False | 8038 | 33 | 16 |
| 2025 | validation | True | 3154 | 3461 | 1618 |
| 2026 | playoffs | False | 596 | 0 | 0 |
| 2026 | playoffs | True | 224 | 207 | 95 |
| 2026 | test | False | 9336 | 46 | 22 |
| 2026 | test | True | 3817 | 4295 | 2022 |

The possession models predict points remaining in a recorded sequence. The model selected on 2025 entry states is **Markov**. The simplest forecasts use means by stage or remaining time. The Markov model estimates state transitions and rewards. The other models fit clock splines or boosted trees.

| split | model | states | rmse | mae |
| --- | --- | --- | --- | --- |
| validation | Stage average | 23869 | 1.16314 | 1.10199 |
| validation | Clock average | 23869 | 1.15964 | 1.09630 |
| validation | State mean | 23869 | 1.15926 | 1.09509 |
| validation | Markov | 23869 | 1.15916 | 1.09462 |
| validation | Poisson spline | 23869 | 1.16320 | 1.09878 |
| validation | Context boosting | 23869 | 1.16015 | 1.09442 |
| test | Stage average | 28471 | 1.17041 | 1.10425 |
| test | Clock average | 28471 | 1.16650 | 1.09803 |
| test | State mean | 28471 | 1.16618 | 1.09680 |
| test | Markov | 28471 | 1.16609 | 1.09626 |
| test | Poisson spline | 28471 | 1.17074 | 1.10115 |
| test | Context boosting | 28471 | 1.16692 | 1.09602 |
| playoffs | Stage average | 1707 | 1.19470 | 1.12853 |
| playoffs | Clock average | 1707 | 1.18953 | 1.12123 |
| playoffs | State mean | 1707 | 1.18808 | 1.11876 |
| playoffs | Markov | 1707 | 1.18850 | 1.11849 |
| playoffs | Poisson spline | 1707 | 1.19293 | 1.12281 |
| playoffs | Context boosting | 1707 | 1.18718 | 1.11645 |

The recovery comparison uses confirmed defensive rebounds to restart eligible tails after a special sequence or overturned play. A stricter policy waits for a second such restart. Hard score and clock exclusions remain in force. The original and expanded fits are compared on the same states.

| policy | states | entry_states | games | periods |
| --- | --- | --- | --- | --- |
| first_rebound | 37390 | 23882 | 1007 | 1562 |
| second_rebound | 30389 | 19425 | 926 | 1334 |

The public releases used here support shot analysis and event based remaining points. Estimating the value of choosing a pass or movement would require action locations and a suitable comparison design.

## Files

- [Source checks and reproduction](../../public_atlas/README.md)
- [Shot prediction results](shot_models/)
- [Possession results and score audits](possession/)
