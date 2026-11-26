# Predictions for 2027

Written on 24 November 2026, before any 2027 game. They will be scored once against the 2027 season under the rules in the prospective test plan.

Teams and shooters are predicted with a Bayesian season model. On past seasons it had lower error than the simple carry over rule for 6 of 6 measures.

## League

| Measure | 2026 | Predicted 2027 | 95% range | Rule |
| --- | ---: | ---: | --- | --- |
| Share of shots from the three point area | 36.53 | 36.53 | 33.28 to 39.78 | Same as last season |
| Field goal points per shot | 1.03 | 1.02 | 0.98 to 1.06 | Five season trend |

## Teams

Net is points per 100 shots against the league from field goals, adding shot quality and shot making on offence and subtracting what is allowed on defence.

| Team | 2026 estimate | Predicted 2027 | 95% range |
| --- | ---: | ---: | --- |
| Minnesota Lynx | +6.7 | +5.4 | -7.3 to +18.0 |
| Las Vegas Aces | +7.3 | +4.8 | -7.7 to +17.3 |
| Indiana Fever | +7.6 | +4.7 | -8.0 to +17.4 |
| New York Liberty | +4.2 | +3.4 | -8.8 to +15.7 |
| Golden State Valkyries | +3.8 | +2.5 | -9.7 to +14.7 |
| Dallas Wings | +3.6 | +0.9 | -11.2 to +13.0 |
| Washington Mystics | +1.7 | +0.6 | -11.7 to +12.9 |
| Portland Fire | -1.5 | -1.0 | -13.6 to +11.6 |
| Los Angeles Sparks | -1.3 | -1.0 | -13.6 to +11.6 |
| Seattle Storm | -3.3 | -1.8 | -14.2 to +10.6 |
| Atlanta Dream | -4.6 | -2.1 | -14.5 to +10.4 |
| Chicago Sky | -1.9 | -2.1 | -14.5 to +10.2 |
| Phoenix Mercury | -5.2 | -2.8 | -14.9 to +9.2 |
| Toronto Tempo | -7.6 | -5.0 | -17.5 to +7.5 |
| Connecticut Sun | -9.8 | -7.1 | -19.4 to +5.3 |

## Shooters

Makes per 100 shots above the league expectation, for players with at least 100 eligible attempts in 2026. The range is for a season with the same number of attempts.

| Player | 2026 estimate | Predicted 2027 | 95% range |
| --- | ---: | ---: | --- |
| Paige Bueckers | +8.4 | +7.7 | +2.5 to +12.9 |
| Natasha Mack | +7.4 | +7.1 | -0.8 to +14.9 |
| A'ja Wilson | +6.5 | +6.4 | +1.6 to +11.2 |
| Brittney Griner | +2.0 | +6.0 | -2.2 to +14.2 |
| Nneka Ogwumike | +4.7 | +5.7 | +0.3 to +11.1 |
| Jackie Young | +5.5 | +5.5 | +0.4 to +10.6 |
| Megan DiLeo | +6.2 | +5.2 | -1.2 to +11.6 |
| NaLyssa Smith | +8.6 | +5.0 | -2.0 to +11.9 |
| Napheesa Collier | +1.7 | +4.7 | -2.9 to +12.2 |
| Chelsea Gray | +3.9 | +4.6 | -1.0 to +10.3 |

## How the rules did on past seasons

Each season from 2019 to 2026 was predicted using only earlier seasons. Error is the root mean squared error against what was then observed. The last column is coverage using prior-season noise. Shooter forecasts require 100 attempts in the preceding season and are weighted by target-season attempts.

| Measure | Predictions | League average | Same as last season | Carry over rule | Bayesian season model | Inside 95% range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Shot quality taken | 97 | 2.14 | 1.96 | 1.84 | 1.82 | 95% |
| Shot making | 97 | 5.69 | 5.19 | 4.96 | 4.82 | 93% |
| Shot quality allowed | 97 | 1.59 | 1.36 | 1.33 | 1.25 | 96% |
| Shot making allowed | 97 | 3.60 | 3.51 | 3.47 | 3.41 | 94% |
| Net | 97 | 7.60 | 7.16 | 6.82 | 6.71 | 95% |
| Shooter makes above expected | 710 | 4.53 | 3.77 | 3.73 | 3.54 | 96% |

## The Bayesian season model

Each team or shooter has a true level in each season, measured against the league. Levels across the league are normal with a common spread. From one season to the next a level keeps a fraction of itself, the persistence, and the rest is replaced by new variation, so the spread stays the same. An observed season equals the true level plus noise of known size: game to game noise for teams and the chance in each shot for shooters.

Starting from the league wide prior, the belief about a level is updated on each observed season in turn and then carried forward to 2027. This uses every past season, with older seasons counting less. The spread and the persistence are set by maximum likelihood on all past seasons. The 95% range is for the value that will be observed in 2027, so it adds the noise of a season of the same length.

| Measure | Persistence from one season to the next | Spread of true levels |
| --- | ---: | ---: |
| Shot quality taken | 0.57 | 2.10 |
| Shot making | 0.75 | 5.28 |
| Shot quality allowed | 0.86 | 1.59 |
| Shot making allowed | 0.70 | 2.68 |
| Net | 0.66 | 6.71 |
| Shooter makes above expected | 0.94 | 3.94 |

The carry over rule multiplies the pooled 2026 estimate by the slope of the next season on the pooled estimate across earlier pairs of seasons. League values use whichever of two simple rules had the lower past error.

No rule here knows about trades, injuries, coaching changes, the draft or new teams. A team that changes its roster can move well outside its range. Players and teams with no 2026 record have no prediction.

[Teams](teams.csv) · [Shooters](shooters.csv) · [League](league.csv) · [Past error](backtest.csv) · [Model settings](season_model.csv) · [Each past team prediction](team_backtest_rows.csv) · [Bayesian court surface](SURFACE.md)
