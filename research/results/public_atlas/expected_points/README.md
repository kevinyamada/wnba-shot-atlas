# League expected points per shot

Across 353,293 shots from 2016 to 2026, a forecast from distance and the side of the three point line lowers the squared error of field goal points by 3.22% against the league average. Adding the recorded shot type lowers it by a further 0.13% (95% game interval 0.10% to 0.17%).

Each season is forecast from the three regular seasons before it. The expectation uses distance, the side of the line and the recorded shot type. It never uses the team, the shooter or anything from the season being scored, so it can be used to compare teams and players.

A miss is worth zero and a make is worth its recorded two or three points. The side of the line comes from the recorded location, so a shot near the line can be expected to score between two and three points when made.

| Games | Forecast | Compared with | Attempts | RMSE | Drop in squared error | 95% interval |
| --- | --- | --- | ---: | ---: | ---: | --- |
| regular | distance and line side | league average | 325,806 | 1.1318 | 3.23% | 3.12% to 3.34% |
| regular | distance, line side and shot type | distance and line side | 325,806 | 1.1310 | 0.13% | 0.09% to 0.17% |
| playoffs | distance and line side | league average | 27,487 | 1.1338 | 3.06% | 2.69% to 3.41% |
| playoffs | distance, line side and shot type | distance and line side | 27,487 | 1.1326 | 0.20% | 0.09% to 0.33% |
| both | distance and line side | league average | 353,293 | 1.1319 | 3.22% | 3.12% to 3.32% |
| both | distance, line side and shot type | distance and line side | 353,293 | 1.1312 | 0.13% | 0.10% to 0.17% |

Expected and actual points differ a little from season to season, because each forecast learned from earlier seasons. Team and player comparisons remove that season level before they are made.

[Scores](scores.csv) · [Expected and actual by area](calibration_by_area.csv) · [Expected and actual by season](calibration_by_season.csv)
