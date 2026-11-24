# A Bayesian court surface for 2027

Two versions of the mesh model were tested on past seasons: mesh field only, and distance trend plus mesh field. The surface below uses the one with the lower past error, distance trend plus mesh field.

The mesh model was fitted to the 115,908 eligible shots of the 2024 to 2026 regular seasons. Its predicted make chance is 71.9% one foot in front of the rim (95% credible range 71.0% to 72.9%), 37.3% in the corner at 23 ft (35.3% to 39.3%) and 33.0% straight on at 24 ft (30.7% to 35.3%).

## How it did on past seasons

Each regular season from 2019 to 2026 was predicted from the three before it. Across 246,307 shots the mesh surface lowered Brier error by 6.14% against the league make rate and changed it by -0.06% against the distance curve (95% game interval -0.10% to -0.02%). The field alone changed it by -0.06% and the trend plus field by -0.06%. Among court spots with at least 20 shots in the predicted season, the makes fell inside the model's 95% range for 92.2% of spots (2,740 of 2,972).

| Season | Shots | Field range (ft) | Field spread | League Brier | Distance Brier | Mesh Brier | Spots inside the 95% range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2019 | 27,208 | 32 | 0.15 | 0.24469 | 0.23178 | 0.23205 | 318 of 347 |
| 2020 | 17,138 | 32 | 0.7 | 0.24713 | 0.23254 | 0.23432 | 177 of 211 |
| 2021 | 25,071 | 32 | 0.3 | 0.24575 | 0.23223 | 0.23252 | 296 of 319 |
| 2022 | 28,777 | 32 | 0.3 | 0.24692 | 0.23073 | 0.23057 | 338 of 365 |
| 2023 | 32,205 | 8 | 0.15 | 0.24659 | 0.23168 | 0.23144 | 371 of 400 |
| 2024 | 32,427 | 32 | 0.7 | 0.24619 | 0.23056 | 0.23036 | 377 of 406 |
| 2025 | 38,441 | 32 | 0.7 | 0.24644 | 0.23120 | 0.23123 | 404 of 440 |
| 2026 | 45,040 | 32 | 0.3 | 0.24798 | 0.23054 | 0.23066 | 459 of 484 |

## Method

The make chance at a location is the logistic transform of a mean plus a Gaussian random field. The mean is an intercept, or an intercept with a smooth curve in distance from the rim (linear, squared and a short range term near the basket) under a weak normal prior. The field has a Matern covariance with smoothness one, represented on a triangle mesh with nodes every 3 ft through the stochastic partial differential equation link. The posterior is a Laplace approximation at the mode, given the chosen range and spread of the field. Those two settings are chosen from nine combinations by log loss on the last training season, then the model is refitted on all three seasons. The credible range for a spot comes from the posterior variance of the field there. The range for a count of makes adds the binomial chance in that many shots.

The surface uses location only. It does not know the shooter, the shot type or the defence, and it assumes 2027 will look like the three seasons before it.

[Surface](surface_2027.csv) · [Past seasons](surface_backtest_by_season.csv) · [Pooled comparison](surface_backtest.csv)
