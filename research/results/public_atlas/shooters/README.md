# Shooters against expectation

Across 353,290 shots from 2016 to 2026, the estimated spread of true shooting skill between players is 3.9 makes per 100 shots (one standard deviation), after accounting for distance and recorded shot type. A shooter with 300 attempts in a season keeps about 74% of the observed margin after pooling.

Using last season's pooled estimate lowered Brier error on the next season's shots by 0.23% (95% game interval 0.19% to 0.28%). Using last season's raw margin instead changed it by -0.18% (-0.26% to -0.10%). Even perfect knowledge of each shooter's skill at this spread would lower shot error by only about 0.42%, which is one reason distance is hard to beat.

## Leaders from 2016 to 2026

Players with at least 200 eligible attempts. Values are makes per 100 shots above the league expectation.

| Player | Attempts | Makes | Expected makes | Observed margin | Pooled estimate | 95% interval |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Elena Delle Donne | 2,530 | 1,229 | 1,014.2 | +8.5 | +8.0 | +6.2 to +9.8 |
| Paige Bueckers | 1,232 | 609 | 499.8 | +8.9 | +7.8 | +5.3 to +10.4 |
| Brittney Griner | 3,820 | 2,101 | 1,793.1 | +8.1 | +7.7 | +6.2 to +9.2 |
| Emma Meesseman | 1,813 | 933 | 791.1 | +7.8 | +7.2 | +5.0 to +9.3 |
| Natasha Mack | 511 | 299 | 250.6 | +9.5 | +7.1 | +3.5 to +10.8 |
| Allie Quigley | 2,454 | 1,135 | 956.5 | +7.3 | +6.8 | +5.0 to +8.7 |
| LaToya Sanders | 464 | 245 | 203.0 | +9.0 | +6.7 | +2.9 to +10.5 |
| Nneka Ogwumike | 4,790 | 2,557 | 2,246.1 | +6.5 | +6.3 | +4.9 to +7.6 |
| Sylvia Fowles | 2,248 | 1,391 | 1,248.3 | +6.3 | +5.9 | +4.0 to +7.8 |
| Sue Bird | 1,536 | 674 | 573.7 | +6.5 | +5.9 | +3.6 to +8.2 |

## Method

The expected chance of each shot comes from the shot type study: a curve of make rate by distance for each recorded shot family, fitted on the three regular seasons before the shot. Each season, those chances are scaled so that the rest of the league, leaving the player out, makes exactly what is expected. Shooter identity never enters the expectation.

A player season has an observed margin, makes minus expected makes per shot, and a noise variance from the chance in each shot. True margins are treated as draws from a normal distribution centred on zero. Its variance is estimated by maximum likelihood from all player seasons. The pooled estimate multiplies the observed margin by the share of its variance that is skill. The interval is the 95% range of the resulting normal posterior.

The sample is the shot type study sample: mapped shots in games where both team boxes match the shot records. The estimate measures results on the shots a player took. It does not separate shooting skill from shot selection, defensive attention or teammates. Players who shoot rarely are pulled toward the league average, which may flatter weaker shooters with few attempts.

## Forecast check

Each season from 2017 on is forecast with estimates from the season before, and the spread of skill is estimated from earlier seasons only. Players without a previous season get the league expectation.

| Shots | Forecast | Attempts | League Brier | Brier | Drop | 95% interval |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| all shots | pooled estimate | 325,009 | 0.23140 | 0.23086 | 0.23% | 0.19% to 0.28% |
| all shots | raw margin | 325,009 | 0.23140 | 0.23181 | -0.18% | -0.26% to -0.10% |
| returning shooters | pooled estimate | 268,116 | 0.23174 | 0.23109 | 0.28% | 0.23% to 0.33% |
| returning shooters | raw margin | 268,116 | 0.23174 | 0.23224 | -0.21% | -0.31% to -0.12% |

[Player seasons](player_seasons.csv) · [Players across 2016 to 2026](players_2016_to_2026.csv) · [Forecast check](forecast_check.csv)
