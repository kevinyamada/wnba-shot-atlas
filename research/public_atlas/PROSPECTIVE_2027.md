# The 2027 season as an untouched test

Written on 23 November 2026, before any 2027 game. Every season through 2026 has already been examined, so results on them are historical comparisons. The 2027 season is the first chance to check the forecasts on games nobody has looked at.

## What is frozen

| Forecast | Frozen rule | Compared with |
| --- | --- | --- |
| Make chance of a shot | The six step model in `why_distance.py`, fitted on the 2022 to 2024 regular seasons with rounds chosen on 2025 | The distance only step from the same script |
| Shooter effect | Each player's pooled 2026 estimate from `shooters.py` added to the league expectation | The league expectation alone |
| League expectation | The distance and shot type curves in `shot_form.py`, fitted on the 2024 to 2026 regular seasons | Distance curve alone |
| First shot within six seconds | The rate by how the possession started in `shot_timing.py`, learned from games through 2024 | One league rate |

The data rules are frozen too: one shot feed per season, the field goal and special game rules in `build.py`, and the eligibility rule that a game needs both team boxes to match its shot records.

The fitted shot models are saved in the local cache as `why_distance_models.joblib`. They are also reproducible from the pinned files with a fixed seed. Record the Git commit that holds this file before scoring.

## What will be reported

1. Brier error and log loss for each forecast and its comparison, on the 2027 regular season and the 2027 playoffs separately.
2. The relative drop in Brier error with a 95% interval from resampling whole games.
3. Average predicted make chance minus the observed make rate, with no adjustment made from 2027 results.
4. The share of shots from each court area, added to the shot mix series.

A forecast counts as holding up if its interval for the drop in error lies above zero on the regular season. The historical sizes to compare with are about 1.9% for the six step model against distance and about 0.2% for the shooter effect.

## Predictions already written down

`predict_2027.py` wrote predictions on 24 November 2026 for the league shot mix and points per shot, for every team's four measures and their net, and for every shooter with at least 100 eligible attempts in 2026. They are in `research/results/public_atlas/prediction_2027/` and on the site under Prediction. When 2027 is complete, compare each with what happened: the error of the rule against the league average and against repeating 2026, and how many outcomes fall inside their 95% ranges.

## Rules for the test

- Pin the 2027 files in the source manifest and record its hash before any scoring.
- Counting games, attempts and location coverage is allowed first. Looking at makes by any feature is not.
- No change to models, features, tuning or data rules after 2027 results are seen. If a data rule has to change because the feed changed, report the result under both the old and the new rule.
- Score once. Any later refit, including one that adds 2025 and 2026 to training, is reported as a new historical comparison and labelled that way.
- Report the result whichever way it goes.

## When the files arrive

Add 2027 to the season range in `fetch.py` and the last season of the current court in `court_rules.json`, pin the files, then run the build. Score the shot models once with

```sh
python research/public_atlas/score_future.py --season 2027
```

The script loads the frozen models, applies the benchmark sample rules to 2027 and writes the results to `research/results/public_atlas/prospective/`. Run on 2026, it reproduces all 47,405 saved predictions exactly, which is the check that the frozen rule is the one being scored. It refuses to run for a season that has not been built.

The shooter, league expectation and first shot forecasts are rolling rules in `shooters.py`, `shot_form.py` and `shot_timing.py`. Extend their season ranges by one year and run them once. Their code must not change first.
