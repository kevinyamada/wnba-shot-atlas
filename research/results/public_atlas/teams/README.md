# What a team controls

Across 136 team seasons from 2016 to 2026, shot quality taken is the most repeatable of the four measures (correlation 0.84 between alternating games of the same season) and shot making allowed is the least (0.29).

Shot quality is the league expected points of the shots a team takes or allows. Shot making is the points scored above that expectation. All four are in points per 100 shots against the rest of the league in that regular season.

| Measure | Same season, alternating games | 95% interval | Following season | 95% interval | Spread between teams | Share of an observed gap kept after pooling |
| --- | ---: | --- | ---: | --- | ---: | ---: |
| Shot quality taken | 0.84 | 0.78 to 0.89 | 0.45 | 0.30 to 0.60 | 2.1 | 90% |
| Shot making | 0.72 | 0.63 to 0.80 | 0.55 | 0.43 to 0.67 | 5.2 | 84% |
| Shot quality allowed | 0.67 | 0.56 to 0.76 | 0.52 | 0.35 to 0.67 | 1.5 | 82% |
| Shot making allowed | 0.29 | 0.10 to 0.46 | 0.37 | 0.22 to 0.51 | 2.7 | 55% |

A higher correlation means the measure reflects something a team does. A correlation near zero means most of what is seen in one stretch of games is chance. These are descriptions of past seasons. They do not show that changing a scheme would move a measure.

## Method

The league expectation comes from `expected_points.py` and uses no team or player. Before a team is compared, the expectation is scaled so that the rest of the league scores exactly what is expected that season. Noise for each team season comes from drawing its games again 1,000 times. Each measure is then pulled toward the league average in proportion to that noise, and the 95% interval is the range of the resulting normal posterior. The same season check splits each team season into alternating games by date. The following season check pairs a franchise with its next season. Intervals for the correlations resample team seasons.

Possession starts use the play by play reconstruction of complete possessions in regular season games. Each start is compared with the rest of the league, and the margin of error is 1.96 standard errors of the mean.

[Team seasons](team_seasons.csv) · [Repeatability](repeatability.csv) · [Possession starts](possession_starts.csv)
