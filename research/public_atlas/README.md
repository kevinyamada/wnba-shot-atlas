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
python research/public_atlas/why_distance.py
python research/public_atlas/shooters.py
python research/public_atlas/verify_models.py
python research/public_atlas/expected_points.py
python research/public_atlas/team_value.py
python research/public_atlas/team_possessions.py
python research/public_atlas/verify_teams.py
python research/public_atlas/team_regions_2025.py
python research/public_atlas/score_future.py --season 2026
python research/public_atlas/test_release_checks.py
python research/public_atlas/predict_surface.py
python research/public_atlas/prediction_pack.py
python research/public_atlas/predict_2027.py
python research/public_atlas/verify_prediction.py
python research/public_atlas/methods_lab.py
python research/public_atlas/heldout_spatial.py
python research/public_atlas/verify_lab.py
python research/public_atlas/start_points.py
python research/public_atlas/verify_starts.py
python research/public_atlas/against_packs.py
python research/public_atlas/report_figures.py
python research/public_atlas/write_report.py
python research/public_atlas/check_browser.py
```

These steps are also available in VS Code under Terminal, Run Task, with names that start with WNBA public. Each writes its details to the results folder and prints a short summary. The task WNBA public: runner keeps a terminal open in VS Code. While it is open, a step started with `python research/public_atlas/vscode_runner.py --send shooters.py` prints there.

The restore step checks the pinned bytes and reports any upstream changes. An explicit refresh creates a new source snapshot using the same release file list. Raw and derived rows stay in the local cache. Each derived shot carries the source file season and original CSV line number.

## Results

A separate check compares the ESPN shot tables with the WNBA Stats shot release on confidently matched games in 2025 and 2026. Its [source pins](reference_manifest.json), [season totals](../results/public_atlas/official_reference_summary.csv) and [game differences](../results/public_atlas/official_reference_games.csv) keep both versions visible. They agree on attempts, makes and points in 661 of 662 games. ESPN records one additional miss in game 401857099, where the ESPN team box also has one fewer attempt than its shot release. The prediction sample excludes that game through the box score check.

- [Methods lab: kriging, an areal CAR model, a Gaussian process, the SPDE mesh and ensembles on one question](../results/public_atlas/methods_lab/README.md)
- [Where the points come from after a steal, a rebound or an opponent's basket](../results/public_atlas/plays/starts/README.md)
- [The research report](../../REPORT.md), written from the results files by `write_report.py`
- [What a team controls: shot quality and shot making on offence and defence](../results/public_atlas/teams/README.md)
- [Whole possessions: turnovers, offensive rebounds and free throws for and against each team](../results/public_atlas/teams/POSSESSIONS.md)
- [League expected points per shot](../results/public_atlas/expected_points/README.md)
- [Why distance is hard to beat](../results/public_atlas/why_distance/README.md)
- [Shooters against expectation, with pooling and intervals](../results/public_atlas/shooters/README.md)
- [Predictions for 2027, written before the season](../results/public_atlas/prediction_2027/README.md)
- [A Bayesian court surface for 2027 from the mesh model](../results/public_atlas/prediction_2027/SURFACE.md)
- [The 2027 season as an untouched test](PROSPECTIVE_2027.md)
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

## Use for teams

The site and the studies are organised around questions a WNBA staff could act on.

- Where do we and our opponents shoot, and what are those shots worth? The court, the area overview and `expected_points.py`.
- Are we getting good shots or making hard ones, and what do we allow? `team_value.py` gives four numbers for every team season from 2016 to 2026, adjusted for opponents.
- What happens on whole possessions? `team_possessions.py` adds turnovers, offensive rebounds and free throws, for and against.
- Why is a steal worth so much? `start_points.py` splits the points after each way of getting the ball into layups, other shots, free throws and second chances.
- Which of those numbers should we trust? The same study compares alternating games. Shot quality taken repeats at 0.84 and opponents' shot making at 0.29.
- Which shooters beat expectation, and from where? `shooters.py`, with pooling and intervals, overall and by court area.
- How do possessions start, and what do they yield? The team report and the play studies.

The main page is written for a reader with no statistics background. Team and shooter charts use points a game or makes per 100 shots, with the words better, worse, more and fewer in place of signed numbers. Ranges are called likely ranges. Model names and technical detail live in the Methods lab tab and the research report.

The page always opens on all seasons and every team. "Copy link to this view" makes a link that opens the current view once, and a reload returns to the default. The link names are `season`, `team`, `player`, `games`, `type`, `compare`, `side` and `colour`. For example, `?season=2026&team=17` opens the 2026 Las Vegas Aces. Values the data do not hold are ignored.

The public files hold shot locations and event order. They hold no passes, cuts, defender positions or lineups on the floor, so they cannot value individual actions or defensive pressure. That needs tracking data from the league or a team.

## Recount and open data questions

`recount.py` reads only the raw CSV files and shares no code with `build.py`. It reproduces 902,770 attempts, 389,257 makes and 859,086 field goal points in 6,982 games with shot records, with 811,678 mapped, 1,461 on the other half and 89,631 with unknown locations. Every comparison with the saved reports and the site files shows no difference. `check_findings.py` rescored the saved 2026 shot forecasts, the shot type test and the possession forecasts from raw outcomes, and recounted the first shot timing result with a simpler scan of the raw play by play (32.4% after a steal and 0.72% after an opponent basket, against the published 32.7% and 0.7%).

Three corrections came out of the recount on 23 November 2026.

- Portland Fire, 2002. The ESPN shot and player files give the team ID 132052, while the schedule lists 12. The build could not confirm which basket those 1,791 attempts were aimed at, so all of them had an unknown location. The build and the recount now treat the two IDs as the same team in 2002. This placed 1,221 attempts on the mapped half and 2 on the other half. The other 568 sit exactly at the basket and stay unknown under the rule for seasons through 2010.
- Made baskets under the wrong label. 45 ESPN rows carry a score of 2 or 3 under a turnover, foul, not available or no shot label. A row now counts as a made basket when the team box for that game still has that many makes to account for. This restored 41 makes worth 87 points: 28 in 2012, 4 in 2018, 1 in 2019 and 8 in the 2023 playoffs. One 2012 row has no team box and three 2024 rows are not supported by the box, so those four stay out. The benchmark training seasons did not change. The shot type test gained five eligible games.
- Shots with no team. 26 attempts with no team ID appeared under a label that joined Unknown team with two real team names. They now appear as Unknown team.

Before these corrections the totals were 902,729 attempts, 389,216 makes and 858,999 points, with 810,416 mapped, 1,459 on the other half and 90,854 unknown.

Still open: 34 completed games in the ESPN schedule from 2002 on have no shot rows, and on games from 2003 on where both teams have a box the shot feed has about 0.5% fewer attempts than the boxes. The 2026 benchmark forecasts were trained on 2022 to 2024 and predict makes about one percentage point too low in 2026, when the league shot better. The longer play histories did not beat the last recorded event on the 2026 regular season next shot test.

The held-out court diagnostic replays the published training settings for 2024–26 and checks each model’s seasonal Brier score. In a two-foot cell, its standardized error is observed minus expected makes divided by the square root of the sum of p(1−p) over shots. The two-sided Moran test compares absolute departures from the cell-permutation mean −1/(n−1), using edge-sharing cells and 9,999 shuffles. The pooled mesh result is the primary test. Annual values describe each season. Regional calibration uses every eligible shot and holds the forecasts fixed while resampling complete games within seasons. The annual ranges and default game reveal describe one region at a time. The pooled seven-region comparison also uses simultaneous 95% bands. For each of 2,000 season-stratified game bootstrap draws, take the largest absolute departure from the observed gap across the seven regions, after dividing each departure by that region’s bootstrap standard deviation. Use the 95th percentile of these maxima as a common multiplier for the seven standard errors. These approximate ranges are conditional on the fitted forecasts. The game compares whole makes per 100 for both players, using the unrounded observed rate to decide the winner.
