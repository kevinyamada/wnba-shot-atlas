# Predictions for 2027

Written on 24 November 2026, before any 2027 game. They will be scored once against the 2027 season under the rules in the prospective test plan.

## League

| Measure | 2026 | Predicted 2027 | 95% range | Rule |
| --- | ---: | ---: | --- | --- |
| Share of shots from the three point area | 36.53 | 36.53 | 33.28 to 39.78 | Same as last season |
| Field goal points per shot | 1.03 | 1.02 | 0.98 to 1.06 | Five season trend |

## Teams

Net is points per 100 shots against the league from field goals, adding shot quality and shot making on offence and subtracting what is allowed on defence.

| Team | 2026 estimate | Predicted 2027 | 95% range |
| --- | ---: | ---: | --- |
| Indiana Fever | +7.6 | +5.0 | -8.4 to +18.3 |
| Las Vegas Aces | +7.3 | +4.8 | -8.6 to +18.1 |
| Minnesota Lynx | +6.7 | +4.4 | -9.0 to +17.8 |
| New York Liberty | +4.2 | +2.7 | -10.7 to +16.1 |
| Golden State Valkyries | +3.8 | +2.5 | -10.9 to +15.9 |
| Dallas Wings | +3.6 | +2.4 | -11.0 to +15.7 |
| Washington Mystics | +1.7 | +1.1 | -12.2 to +14.5 |
| Los Angeles Sparks | -1.3 | -0.9 | -14.3 to +12.5 |
| Portland Fire | -1.5 | -1.0 | -14.4 to +12.4 |
| Chicago Sky | -1.9 | -1.2 | -14.6 to +12.1 |
| Seattle Storm | -3.3 | -2.1 | -15.5 to +11.2 |
| Atlanta Dream | -4.6 | -3.0 | -16.4 to +10.4 |
| Phoenix Mercury | -5.2 | -3.4 | -16.8 to +10.0 |
| Toronto Tempo | -7.6 | -5.0 | -18.4 to +8.4 |
| Connecticut Sun | -9.8 | -6.4 | -19.8 to +7.0 |

## Shooters

Makes per 100 shots above the league expectation, for players with at least 100 eligible attempts in 2026. The range is for a season with the same number of attempts.

| Player | 2026 estimate | Predicted 2027 | 95% range |
| --- | ---: | ---: | --- |
| NaLyssa Smith | +8.6 | +7.6 | +0.1 to +15.1 |
| Paige Bueckers | +8.4 | +7.4 | +1.2 to +13.5 |
| Natasha Mack | +7.4 | +6.5 | -1.6 to +14.5 |
| A'ja Wilson | +6.5 | +5.7 | -0.3 to +11.7 |
| Megan DiLeo | +6.2 | +5.4 | -1.5 to +12.4 |
| Julie Allemand | +5.6 | +4.9 | -4.4 to +14.2 |
| Jackie Young | +5.5 | +4.8 | -1.4 to +10.9 |
| Kelsey Plum | +5.4 | +4.7 | -3.1 to +12.5 |
| Nneka Ogwumike | +4.7 | +4.2 | -2.2 to +10.5 |
| Chennedy Carter | +4.6 | +4.0 | -6.7 to +14.7 |

## How well the rule worked on past seasons

Each season from 2019 to 2026 was predicted from the season before, using only earlier seasons to set the pooling and the carry over. Error is the root mean squared error against what was then observed.

| Measure | Predictions | League average | Same as last season | Carry over rule |
| --- | ---: | ---: | ---: | ---: |
| Shot making allowed | 97 | 3.60 | 3.51 | 3.47 |
| Shot quality allowed | 97 | 1.59 | 1.36 | 1.33 |
| Net | 97 | 7.60 | 7.16 | 6.82 |
| Shot making | 97 | 5.69 | 5.19 | 4.96 |
| Shot quality taken | 97 | 2.14 | 1.96 | 1.84 |
| Shooter makes above expected | 933 | 4.72 | 4.07 | 4.03 |

## Method and limits

A team or player prediction is the pooled 2026 estimate times a carry over factor. The factor is the slope, through zero, of the next season on the pooled estimate across all earlier pairs of seasons. Team ranges are 1.96 times the past error of the rule. Shooter ranges add the chance in a season of the same length. League values use whichever of two simple rules had the lower past error: the last value, or a straight line through the last five seasons.

The rule knows nothing about trades, injuries, coaching changes, the draft or new teams. A team that changes its roster can move well outside its range. Players and teams with no 2026 record have no prediction.

[Teams](teams.csv) · [Shooters](shooters.csv) · [League](league.csv) · [Past error](backtest.csv) · [Each past team prediction](team_backtest_rows.csv)
