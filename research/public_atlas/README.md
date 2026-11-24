# Public WNBA Shot Atlas

The explorer covers 30 recorded seasons from 1997 to 2026. The build uses only the public wehoop releases pinned in [the source manifest](source_manifest.json). Each pin records its release tag, asset ID, checksum and byte size.

| Seasons | Shot release | Game scope |
| --- | --- | --- |
| 1997 to 2001 | WNBA Stats via wehoop | League game ID distinguishes regular season and playoffs |
| 2002 to 2026 | ESPN via wehoop | Completed games in the ESPN schedule |
| 2022 to 2026 | ESPN play by play and player and team boxes via wehoop | Public shot and possession benchmarks |

The site combines regular games and playoffs at startup. Free throws, exhibitions and the cup final are excluded from shot totals. Long shots and unknown locations stay in attempts, makes and points. The court area overview beside the map uses the map's filters and lists attempts, share of shots, make rate and points per shot for each area. Its other half and unknown location rows make the areas add up to all attempts. Selecting an area outlines it on the court and lists its makes, points and the leaders by observed field goal points. When two seasons are compared, the overview shows attempts or attempts per 100 shots for both. Shots recorded exactly at the basket through 2010 are kept with unknown locations because of the provider pileups there. The early shot release uses tenths of a foot. ESPN coordinates use the attacking team's basket and are checked against the raw coordinate pair. Early player and team IDs are linked only where the published crosswalk has a unique high confidence match. Historical team labels follow the name history of the recorded provider ID.

Shot type groups come from the recorded subtype or play type text. Layups include finger rolls. Dunks, hooks, runners, tips and jump shots are distinct. Generic labels remain in Other field goal. Model comparisons by shot type use identical attempts within each group. Uncertain missed shot values remain unknown.

The court uses three line eras. From 1997 to 2003 the documented radius was 19 ft 9 in and the lane was 12 ft. Only the front of that earliest arc is drawn, and the early line density uses that front region. The early geometric corner classification is approximate. The lane widened to 16 ft and the arc moved to 20 ft 6¼ in for 2004. The arc moved to 22 ft 1¾ in for 2013. Rule references are in [court_rules.json](court_rules.json).

## Reproduce on CPU

From the repository root with Python 3.13, install the packages listed below. Chrome and websocket client are needed for the browser check.

```sh
python -m pip install numpy pandas scipy scikit-learn catboost xgboost websocket-client
python research/public_atlas/fetch.py
python research/public_atlas/build.py
python research/public_atlas/analyze.py
python research/public_atlas/shot_models.py
python research/public_atlas/reconstruct.py
python research/public_atlas/possession_value.py
python research/public_atlas/publish_study.py
python research/public_atlas/verify.py
python research/public_atlas/reference_audit.py
python research/public_atlas/shot_form.py
python research/public_atlas/form_context.py
python research/public_atlas/form_reference.py
python research/public_atlas/publish_form.py
python research/public_atlas/verify_form.py
python research/public_atlas/play_sources.py
python research/public_atlas/league_turns.py
python research/public_atlas/play_value.py
python research/public_atlas/verify_plays.py
python research/public_atlas/shot_timing.py
python research/public_atlas/verify_timing.py
python research/public_atlas/recount.py --live
python research/public_atlas/check_findings.py
python research/public_atlas/shot_mix.py
python research/public_atlas/verify_shot_mix.py
python research/public_atlas/check_browser.py
```

The same four new steps are available in VS Code under Terminal, Run Task, with names that start with WNBA public. Each writes its details to the results folder and prints a short summary.

The restore step checks the pinned bytes and reports any upstream changes. An explicit refresh creates a new source snapshot using the same release file list. Raw and derived rows stay in the local cache. Each derived shot carries the source file season and original CSV line number.

## Results

A separate check compares the ESPN shot tables with the WNBA Stats shot release on confidently matched games in 2025 and 2026. Its [source pins](reference_manifest.json), [season totals](../results/public_atlas/official_reference_summary.csv) and [game differences](../results/public_atlas/official_reference_games.csv) keep both versions visible. They agree on attempts, makes and points in 661 of 662 games. ESPN records one additional miss in game 401857099, where the ESPN team box also has one fewer attempt than its shot release. The prediction sample excludes that game through the box score check.

- [Recount of games, attempts, makes and points from the raw files](../results/public_atlas/recount/README.md)
- [Shot mix and conversion across seasons](../results/public_atlas/shot_mix/README.md)
- [How soon teams shoot after a change of possession](../results/public_atlas/plays/timing/README.md)
- [Shot sources, next shot probability and expected points from play histories](../results/public_atlas/plays/README.md)
- [Shot type at the same distance, rolling tests and source agreement](../results/public_atlas/shot_form/README.md)
- [Data coverage, shot counts and arc patterns](../results/public_atlas/eda.md)
- [Prediction, remaining points and recovery results](../results/public_atlas/study.md)
- [Shot prediction metrics and court surfaces](../results/public_atlas/shot_models/)
- [Possession metrics and source checks](../results/public_atlas/possession/)

The original public benchmark models train on 2022 to 2024 regular season games, select settings on the 2025 regular season, and score 2026 regular season and playoff games separately. The game level bootstrap compares errors on identical shots or states. The earlier study used full posterior sampling for some fits. This edition uses CPU Laplace inference conditional on the selected Matérn and mesh hyperparameters. Court intervals concern modelled probabilities. Play sequences support remaining points forecasts and rebound summaries. The releases used here lack the action locations needed to value individual passes or movement.

## Recount and open data questions

`recount.py` reads only the raw CSV files and shares no code with `build.py`. On 23 November 2026 it reproduced 902,729 attempts, 389,216 makes and 858,999 field goal points in 6,982 games with shot records. All 39 comparisons with the saved reports, the local site files and the live site files showed no difference. `check_findings.py` rescored the saved 2026 shot forecasts, the shot type test and the possession forecasts from raw outcomes, and recounted the first shot timing result with a simpler scan of the raw play by play (32.4% after a steal and 0.72% after an opponent basket, against the published 32.7% and 0.7%).

The recount found one location error, which is now corrected. In 2002 the ESPN shot and player files give the Portland Fire team ID 132052, while the schedule lists 12. The build could not confirm which basket those 1,791 attempts were aimed at, so all of them had an unknown location. The build and the recount now treat the two IDs as the same team in 2002. This placed 1,221 attempts on the mapped half and 2 on the other half. The remaining 568 sit exactly at the basket and stay with the unknown locations under the rule for seasons through 2010. Across all seasons 811,637 attempts are now mapped, 1,461 are on the other half and 89,631 have unknown locations. Before the correction those counts were 810,416, 1,459 and 90,854. Attempts, makes and points did not change.

The recount also found three things the published numbers do not yet reflect. None changes the attempt total.

- 45 ESPN rows in regular season and playoff games carry a score of 2 or 3 under a turnover, foul, not available or no shot label. The team box agrees with counting them as made baskets in 21 of the 23 team games that have a box. They are outside the totals.
- 34 completed games in the ESPN schedule from 2002 on have no shot rows. On games from 2003 on where both teams have a box, the shot feed has 3,632 fewer attempts than the boxes (0.5%).
- 26 attempts with no team ID appear under a team label that reads Unknown team / San Antonio / Connecticut in the all seasons team filter.

The 2026 shot forecasts were trained on 2022 to 2024 and predict makes about one percentage point too low on average in 2026, when the league shot better. The longer play histories did not beat the last recorded event on the 2026 regular season next shot test.
