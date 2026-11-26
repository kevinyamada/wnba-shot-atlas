# Why is distance so hard to beat?

On 44,478 shots from the 2026 regular season, a forecast that gives every shot the league make rate has a Brier error of 0.2480. Using distance alone brings it to 0.2308. Adding court position, the recorded shot type, the period, clock and score, the previous event and the shooter's record so far brings it to 0.2264, a further drop of 1.9%.

If the fitted make probabilities were exact, the expected squared error would be 0.2263, against the 0.2264 it actually has. The contribution of unobserved shot difficulty is unknown. Distance already spreads them with a standard deviation of 12.5 percentage points and everything else widens that to 14.6.

| Added information | Brier error | Drop from distance | 95% interval | Drop from previous step | 95% interval |
| --- | ---: | ---: | --- | ---: | --- |
| League make rate only | 0.24803 | | | | |
| Distance | 0.23077 | | | 6.96% | 6.41% to 7.50% |
| Court position | 0.23069 | 0.04% | -0.01% to 0.09% | 0.04% | -0.01% to 0.09% |
| Recorded shot type | 0.22801 | 1.20% | 0.91% to 1.45% | 1.16% | 0.88% to 1.42% |
| Period, clock and score | 0.22782 | 1.28% | 1.00% to 1.55% | 0.09% | 0.00% to 0.17% |
| Previous event | 0.22698 | 1.64% | 1.34% to 1.93% | 0.37% | 0.25% to 0.49% |
| Shooter record so far | 0.22640 | 1.90% | 1.59% to 2.18% | 0.26% | 0.13% to 0.37% |

## What a larger gain would take

For a well calibrated forecast, Brier error equals the error of the league rate minus the variance of the predicted chances. The table gives the spread of predicted chances needed to beat distance by each amount.

| Drop from distance | Brier error needed | Spread of predicted chances needed |
| ---: | ---: | ---: |
| 2% | 0.2262 | 14.8 points |
| 5% | 0.2192 | 17.0 points |
| 10% | 0.2077 | 20.1 points |
| 20% | 0.1846 | 25.2 points |

## What this can and cannot say

The recorded shot type and the previous event are the closest things in these files to how a shot came about. They help a little. The files have no defender positions, no passes and no movement, so the gain from tracking data cannot be measured here. The spread table shows the size of the task: tracking would have to separate shots far more sharply than everything recorded today.

Each step is a boosted tree model with depth 3 and a learning rate of 0.05. The number of rounds is chosen by log loss on the 2025 regular season and the 2026 scores are computed once. The previous event and the score come from the ESPN play by play and use only rows recorded before the shot. 100.0% of test shots matched a play by play row. Unmatched shots keep missing values for those features. Intervals resample whole games.

[Scores for every split](ladder.csv) · [Spread needed](what_it_would_take.csv)
