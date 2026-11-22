# WNBA Shot Atlas public seasons

[Open the explorer](https://kevinyamada.github.io/wnba-shot-atlas/explore/) · [Season audit and findings](../results/public_atlas/eda.md) · [Original 2025 study](https://kevinyamada.github.io/wnba-shot-atlas/)

This edition uses 16 seasons of wehoop / ESPN shot records, schedules, team boxes, and player boxes. [The source manifest](source_manifest.json) records the release asset, byte length, date, and SHA256 for each of the 64 CSV files. The [wehoop documentation](https://wehoop.sportsdataverse.org/articles/wnba-womens-college-basketball-shot-charts.html) explains the shot data and coordinate system. The private Data (1).zip is used separately to compare the overlapping 2025 records.

## From inputs to results

| File | What it does |
| --- | --- |
| `fetch.py` | Restores and verifies the exact pinned files on disk. |
| `build.py` | Assigns games and shots, reconciles box scores, and exports one file per season for the explorer. |
| `geometry.py` and `court_rules.json` | Convert provider coordinates and define the court for each era. The explorer gets its court dimensions from the same file as the analysis. |
| `analyze.py` | Compares volume, accuracy, and points. It also repeats the main area comparisons on games whose two team boxes agree. |
| `verify.py` | Verifies the season files against the source rows, recounts each grouping, and checks the court rules and published totals. |

The project ran on the desktop CPU with Python 3.13, pandas, and NumPy. From the repository root:

```powershell
py -3.13 research/public_atlas/fetch.py
py -3.13 research/public_atlas/build.py --archive 'C:\Users\kevin\Downloads\Data (1).zip'
py -3.13 research/public_atlas/analyze.py
py -3.13 research/public_atlas/verify.py
```

The downloader requires the exact pinned asset bytes. Some upstream files can change if the provider rebuilds a release. Retain the downloaded snapshot for repeat runs. Use `fetch.py --refresh` to make a deliberate new snapshot. `build.py --seasons 2012 2013 2025` is the pilot command. Run the full build again before publishing season files.

## Definitions

- A row in the shot table represents a recorded field goal attempt with a recognized shooting play description and a score of zero, two, or three. The table keeps the source row number, coordinates, score, play description, game, team at the time, and shooter. Free throws and uncertain records are written separately. Repeated rows are flagged because the shot release does not give each play an identifier. Box scores can identify differences without deciding which apparent repeat is genuine.
- Made shots use the points scored. Misses only get a two or three point attempt label if the play type says so explicitly. A player may be unknown on an otherwise usable shot. A missing player box is reported as unavailable. Missing values do not become zero attempts.
- The schedule supplies the game type. Exhibition games and the Cup final are separate. The early Cup final in 2021 and the All Star Game in 2023 need game ID overrides because their schedule descriptions do not identify them. One duplicate 2011 game ID is removed from the schedule denominator after checking the date, teams, and scores against the entry with play records. Cancelled, postponed, and forfeited games without ordinary play do not supply shooting records.
- The provider coordinates describe a full court. We orient them to the shooting team’s basket using the home and away identifiers and verify the transform against the provider’s raw coordinate columns. Valid attempts beyond half court and ambiguous locations still count in the totals. The map uses bins 2.5 feet wide. Bins at the edges of the court can cover a smaller area.
- The position relative to the line is calculated from the arc and straight corner segments in that season. The 2011 media guide gives the early corner dimensions. The 2013 rule announcement and later rule books establish the wider arc. The corners extend from the baseline to where they intersect the arc. For whole foot positions, shots within about 0.71 feet of the line are flagged as close to the boundary. Any recorded value is kept separately.
- Rim means distance under 4 feet. Short two area means 4 to under 10 feet inside the line. Midrange area means the remaining inside area. Corner three area and Above the break describe geometry rather than the points awarded. The timeline uses the same physical square when a square is picked, and the selected season’s court geometry when an area is picked.
- Shot share is attempts in the selected area divided by all attempts under the filters. Make rate is makes divided by attempts. Points per shot is field goal points divided by attempts. The raw league comparison uses the same area, season, and game filter. On the court, accuracy and points are patterned when a cell has fewer than 12 attempts.

[Coverage by season](../results/public_atlas/season_coverage.csv) lists schedule and box coverage. [Team reconciliation](../results/public_atlas/team_game_audit.csv) identifies exact differences by game. [Season and zone totals](../results/public_atlas/season_zones.csv) and [the EDA](../results/public_atlas/eda_by_season.csv) report the observed counts and rates. The source rows, normalized event tables, and player reconciliation are kept in `research/data/public_wnba/` on the desktop. The published site contains grouped counts only.
