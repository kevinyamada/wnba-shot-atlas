# Methods lab

Eleven methods answer one question: the chance a shot goes in from each court spot. Each learns from three regular seasons and is scored on the next. Across 115,908 shots from 2024 to 2026, the lowest error belongs to gaussian process at 0.23064. The distance curve scores 0.23085.

| Method | Family | Brier error | Change from the distance curve | 95% game interval |
| --- | --- | ---: | ---: | --- |
| Gaussian process | Bayesian field | 0.23064 | +0.09% | +0.04% to +0.14% |
| Stacked ensemble | Ensemble | 0.23064 | +0.09% | +0.05% to +0.13% |
| Simple average | Ensemble | 0.23067 | +0.07% | +0.03% to +0.12% |
| SPDE mesh with trend | Bayesian field | 0.23077 | +0.03% | -0.02% to +0.09% |
| SPDE mesh field | Bayesian field | 0.23077 | +0.03% | -0.02% to +0.09% |
| Distance curve | Baseline | 0.23085 | -0.00% | -0.00% to -0.00% |
| Universal kriging | Geostatistics | 0.23098 | -0.06% | -0.14% to +0.02% |
| Ordinary kriging | Geostatistics | 0.23099 | -0.06% | -0.14% to +0.02% |
| Areal CAR model | Areal data | 0.23108 | -0.10% | -0.17% to -0.02% |
| Inverse distance weighting | Interpolation | 0.23136 | -0.22% | -0.31% to -0.14% |
| League rate | Baseline | 0.24697 | -6.98% | -7.31% to -6.65% |

## Where shots come from

A log Gaussian Cox process treats shot locations as a point pattern whose intensity varies smoothly over the court. It is fitted to counts in 2 ft cells with a Poisson likelihood and a neighbour prior on the log intensity. Predicting where the next season's shots fall, its average log score per shot is 5.0628, against 5.0632 for reusing the cell shares of the three seasons and 5.0612 for reusing the last season alone. Lower is better. The best of the three is last season, so smoothing the pattern adds little once a full season of shots is available.

| Season | Shots | Last season shares | Three season shares | Cox process |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 32,427 | 5.1110 | 5.1129 | 5.1129 |
| 2025 | 38,441 | 5.0774 | 5.0798 | 5.0792 |
| 2026 | 45,040 | 5.0114 | 5.0132 | 5.0128 |

A positive change means lower error than the distance curve. The stacked ensemble uses weights fitted on the season before each test, so it never sees the season it is scored on.

## Spatial structure

The variogram of cell make rates on the logit scale rises with distance, with a fitted sill of 0.16 and a range of 33.4 ft. After a trend in distance is removed the sill falls to 0.049, so little spatial structure is left.

| Cell values | Moran's I | Permutation p value |
| --- | ---: | ---: |
| Observed make rate | 0.531 | 0.001 |
| After the distance curve | 0.067 | 0.037 |
| After the mesh model with trend | -0.078 | 0.974 |

Shots are far from evenly spread. A quadrat test on 45,040 shots from 2026 gives a variance to mean ratio of 3496 where complete spatial randomness would give about 1, and Ripley's K at 2 ft is 109 against 13 for random points.

## Notes

Kriging and inverse distance weighting work on 2 ft cells. The areal model uses the same cells with a conditional autoregressive prior and a binomial likelihood. The Gaussian process and the mesh models use exact shot locations. Bayesian models use a Laplace approximation at the posterior mode. Kriging, the Gaussian process and inverse distance weighting use the settings chosen in the earlier benchmark. The areal and mesh models choose theirs on the last training season. Moran's I uses cells with at least 20 shots and neighbours one cell apart, with 999 permutations. Ripley's K uses 4,000 sampled shots moved by up to half a foot, a border correction and 39 random patterns.

[Scores](scores.csv) · [Scores by season](scores_by_season.csv) · [Stacking weights](stacking_weights.csv) · [Settings](settings.csv) · [Variograms](variogram.csv) · [Moran's I](morans_i.csv) · [K function](k_function.csv) · [Surfaces for 2027](surfaces_2027.csv) · [Shot density scores](intensity_scores.csv) · [Shot density for 2027](intensity_2027.csv)
