# How soon does the first shot come?

In 30 WNBA seasons, a team took a shot within six game seconds on 32.7% of possessions after a steal and 0.7% after an opponent made a basket. The rate after a steal was higher in each of the 30 seasons. The difference was 32.0 first shots per 100 possessions, with a 95% game bootstrap interval from 31.7 to 32.3.

| Regular season and playoffs combined | Possessions | First shot by six seconds | Points from those shots | Points per 100 possessions |
| --- | ---: | ---: | ---: | ---: |
| After a steal | 98,400 | 32,209 | 42,844 | 43.5 |
| After an opponent basket | 334,784 | 2,329 | 2,792 | 0.8 |

## What enters the count

The study covers the 1997 through 2026 regular seasons and playoffs. It uses the pinned WNBA Stats play by play and schedule files distributed through wehoop. Its starting point is the existing reconstruction of complete possessions from games with verified scores, ordered events and a valid period clock. [Source manifest](../../../../public_atlas/play_manifest.json) · [Possession reconstruction](../README.md)

Each possession enters once. The five starts are a steal, another opponent turnover, a defensive rebound, an opponent made field goal and an opponent made final free throw. An offensive rebound continues the same possession. Of 987,140 complete starts, 960,616 in 6,874 games had at least 12 seconds left in the period. All time settings use these same eligible starts. [Coverage by season](coverage_by_season.csv)

Timing begins at the recorded change of possession, including the opponent basket for a possession that follows one. The game clock measures elapsed playing time. The events do not give the instant of the inbound or show whether the defense was set. Events at the same clock reading have zero elapsed seconds and retain their recorded order.

The outcome is the first field goal attempt by that team before its possession ends. Shots after an intervening foul still count. A turnover without a shot stays in the denominator. A first shot at exactly six elapsed seconds counts at six. The points measure assigns the first attempt its recorded reward of zero, two or three points. Free throws and points from later attempts belong to the wider possession analysis.

## Comparisons and forecasts

Each rate divides by the number of eligible possessions with that particular start. The pooled rate weights each possession equally. A separate count of season results checks how often the difference has the same direction across years. The 95% intervals use 2,000 draws of whole games within each season and game type. Both starts travel together when a game is drawn.

The forecast target is a first shot within six game seconds. One forecast gives every eligible start the historical league rate. The other learns a rate for each of the five starts. Each rate combines its observed outcomes with 40 possessions at the league rate. Both forecasts use games through 2024 and the same eligible possessions for evaluation. Knowing how the team gained possession lowered Brier error in the 2025 and 2026 regular seasons and playoffs. The paired game intervals favoured the model in all four tests. These seasons had already been examined in earlier atlas work. [Forecast scores and intervals](forecast_scores.csv)

## Reproduction

Run the possession reconstruction, then the two commands below from the repository root.

```sh
python research/public_atlas/shot_timing.py
python research/public_atlas/verify_timing.py
```

The season table keeps one row for each observed first shot timing bucket. Values 0 through 12 give the first whole second by which the shot had occurred. A value of 13 means the first attempt came later, and a value of `-1` means the possession ended without a shot. The checker reopens the pinned event files and searches forward from each start for the first attempt by the correct team before the recorded end. It independently recounts every public time setting, reproduces the historical Brier scores and checks the game intervals. [Season counts](first_shots_by_season.csv) · [Verification record](verification.json)
