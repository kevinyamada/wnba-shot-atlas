# Public WNBA Shot Atlas

The explorer covers 30 recorded seasons from 1997 to 2026. The build uses only the public wehoop releases pinned in [the source manifest](source_manifest.json). Each pin records its release tag, asset ID, checksum and byte size.

| Seasons | Shot release | Game scope |
| --- | --- | --- |
| 1997 to 2001 | WNBA Stats via wehoop | League game ID distinguishes regular season and playoffs |
| 2002 to 2026 | ESPN via wehoop | Completed games in the ESPN schedule |
| 2022 to 2026 | ESPN play by play and player and team boxes via wehoop | Public shot and possession benchmarks |

The site combines regular games and playoffs at startup. Free throws, exhibitions and the cup final are excluded from shot totals. Long shots and unknown locations stay in attempts, makes and points. Shots recorded exactly at the basket through 2010 are kept with unknown locations because of the provider pileups there. The early shot release uses tenths of a foot. ESPN coordinates use the attacking team's basket and are checked against the raw coordinate pair. Early player and team IDs are linked only where the published crosswalk has a unique high confidence match. Historical team labels follow the name history of the recorded provider ID.

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
python research/public_atlas/check_browser.py
```

The restore step checks the pinned bytes and reports any upstream changes. An explicit refresh creates a new source snapshot using the same release file list. Raw and derived rows stay in the local cache. Each derived shot carries the source file season and original CSV line number.

## Results

A separate check compares the ESPN shot tables with the WNBA Stats shot release on confidently matched games in 2025 and 2026. Its [source pins](reference_manifest.json), [season totals](../results/public_atlas/official_reference_summary.csv) and [game differences](../results/public_atlas/official_reference_games.csv) keep both versions visible. They agree on attempts, makes and points in 661 of 662 games. ESPN records one additional miss in game 401857099, where the ESPN team box also has one fewer attempt than its shot release. The prediction sample excludes that game through the box score check.

- [Shot sources, next shot probability and expected points from play histories](../results/public_atlas/plays/README.md)
- [Shot type at the same distance, rolling tests and source agreement](../results/public_atlas/shot_form/README.md)
- [Data coverage, shot counts and arc patterns](../results/public_atlas/eda.md)
- [Prediction, remaining points and recovery results](../results/public_atlas/study.md)
- [Shot prediction metrics and court surfaces](../results/public_atlas/shot_models/)
- [Possession metrics and source checks](../results/public_atlas/possession/)

The original public benchmark models train on 2022 to 2024 regular season games, select settings on the 2025 regular season, and score 2026 regular season and playoff games separately. The game level bootstrap compares errors on identical shots or states. The earlier study used full posterior sampling for some fits. This edition uses CPU Laplace inference conditional on the selected Matérn and mesh hyperparameters. Court intervals concern modelled probabilities. Play sequences support remaining points forecasts and rebound summaries. The releases used here lack the action locations needed to value individual passes or movement.
