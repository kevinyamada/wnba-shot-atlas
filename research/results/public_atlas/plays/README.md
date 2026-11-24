# WNBA play situations and expected points

From 1997 through 2026, the WNBA Stats schedule lists 7,021 regular season and playoff games. Both final scores and the recorded scoring snapshots passed the checks in 6,877. Complete, traceable turns contributed misses in 6,874.

| How the team got the ball | Decision points | Shot on next event | Points to end of turn |
| :--- | ---: | ---: | ---: |
| Steal | 101,035 | 68.1% | 1.138 |
| Offensive rebound | 148,060 | 65.0% | 1.021 |
| Defensive rebound | 345,444 | 64.7% | 0.992 |
| Opponent basket | 342,699 | 68.2% | 0.958 |
| Opponent turnover | 92,798 | 69.2% | 0.942 |
| Opponent free throw | 105,164 | 67.3% | 0.941 |

Of 461,950 verified missed field goals, 142,251 (30.8%) were followed by an offensive rebound. Across all retained offensive rebounds, teams then scored 1.02 more points on average.

## What the forecasts measure

A decision is recorded when a team gains control after a defensive rebound, turnover, opponent basket or final made free throw, or regains control after an offensive rebound. The shot target is whether the next substantive recorded event is a field goal attempt. Its complement includes fouls, turnovers, free throws and period endings. Scoring threat is the probability of at least one more point before the turn ends. The points target is all subsequent ordinary points through the end of that team’s turn. Groups can overlap when an offensive rebound keeps the same turn alive. The data describe the situations in which teams got the ball. They cannot identify the effect of calling a specific play.

Each sequence begins at a confirmed change of control. The model uses at most the last ten recorded actions already visible at the decision, in order. It fits through 2024. Both phases of 2025 and 2026 are scored on identical decision points for the league average, the last action model and the longer history model. Shot probability, scoring threat and expected points share the prior structure and use different outcomes. For a suffix seen n times, the posterior mean is the observed total plus 40 times its parent estimate, divided by n + 40. The parent drops the oldest action. Unseen suffixes take their parent’s estimate. For both binary outcomes this is a Beta prior. For points it is the mean of a distribution over turn rewards with a Dirichlet prior. The prior strength is fixed. Game resampling compares paired differences in Brier error and squared points error. These are historical tests in previously examined seasons.

| 2026 games | History | Decision points | Shot Brier | Scoring threat Brier | Points RMSE |
| :--- | :--- | ---: | ---: | ---: | ---: |
| playoffs | League average | 3,698 | 0.218067 | 0.248138 | 1.1717 |
| playoffs | Last action | 3,698 | 0.217690 | 0.248174 | 1.1712 |
| playoffs | Up to ten actions | 3,698 | 0.217686 | 0.248127 | 1.1712 |
| regular | League average | 56,522 | 0.216555 | 0.250081 | 1.1657 |
| regular | Last action | 56,522 | 0.216352 | 0.249494 | 1.1649 |
| regular | Up to ten actions | 56,522 | 0.216361 | 0.249500 | 1.1648 |

## Location and movement

The shot map gives observed attempts, make rate and field goal points per attempt. The location forecast summarizes the joint model’s predicted probabilities of zero, two and three points across the actual attempts in each court area. Training uses 2022 to 2024 and model selection uses 2025. This is shot value given an attempt. The event model also includes situations that end without a shot.

The expected goals idea from hockey carries over as two distinct questions. How likely is a shot to happen next? Once taken, how valuable is it? In basketball the possible field goal rewards are zero, two and three. The sequence model borrows information across related recorded histories when observations are scarce. All fitted observations and scores in this project come from the WNBA.

The archive gives locations at shot attempts. It cannot show every successful pass, dribble, cut or defender position. The action display counts only events within a single turn. Shorter histories are shown at their actual length. In the ten or more group only the final ten events are shown. The gap in shot density immediately inside the three point line is consistent with an incentive to shoot a three. Release coordinates alone do not show whether the shooter deliberately stepped back.

## Source accounting and exclusions

The shot explorer uses one provider per season. WNBA Stats supplies 120,948 attempts in 1997 through 2001. ESPN supplies 274,074 attempts in 2002 through 2010. ESPN supplies 507,748 attempts in 2011 through 2026. The recent release contains 511,210 field goal attempts before setting aside 3,462 from special games. The public explorer therefore has 902,770 regular season and playoff attempts. The separate league event files supply histories and a score check. They add zero attempts to that total.

Event order comes from the published order index. The schedule must agree with both teams’ points and the running scoreboard on scoring rows where it is available. A period needs an end marker and an ordered, valid clock. Before 2006 the regulation clock uses two twenty minute halves. Later seasons use four ten minute quarters, with five minute overtime periods. Unresolved transfers, jumps, reviews that overturn a call, special free throws and unsupported live events discard open turns. Play can resume at the next confirmed change of control. Missed shots require an identifiable rebound to connect to another live attempt. Midseries dead ball rebounds do not create a second chance. The public miss dropdown preserves the earlier ESPN study samples under their own names. Its all seasons options use the WNBA Stats reconstruction.

## Files and references

[Season coverage](coverage.csv) · [Each game and final score](event_game_checks.csv) · [Shot source counts](shot_sources.csv) · [Play situations](situations_by_season.csv) · [Misses](misses_by_season.csv) · [Rebounds](boards_by_season.csv) · [Location value](location_value.csv) · [Forecasts and intervals](sequence_scores.csv) · [Source manifest](../../../public_atlas/play_manifest.json)

[WNBA Stats event documentation](https://github.com/sportsdataverse/wehoop-wnba-stats-data/blob/main/docs/datasets/pbp.md) · [Hockey shot quality and empirical Bayes](https://spectrum.library.concordia.ca/id/eprint/988845/) · [Basketball possession value with tracking](https://www.lukebornn.com/papers/cervone_ssac_2014.pdf)
