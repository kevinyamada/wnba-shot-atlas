# WNBA Shot Atlas data review

The pinned files support 507,707 recorded field goal attempts in regular season games and playoffs from 2011 through 2026. There were 222,247 makes and 494,792 points from those attempts. The court displays 506,650 attempts. Another 1,041 came from the other half of the court and 16 have an unusable location. The three counts sum to the attempt total.

## What changed

- The share of recorded shots from the geometric three point area rose from 23.8% in 2011 to 36.5% in 2026. It was 23.8% and 36.5% when limited to games matching both team boxes.
- The team boxes also show more attempts credited as threes. The share was 24.1% in 2011 and 37.2% in 2026, across the available regular season boxes. The box share uses recorded three point attempts. The map share uses court geometry and can differ.
- To compare the space affected by the 2013 rule change, use the same physical band in both years. Among locations at least 10 feet in front of the rim and between the old and new arc radii, there were 2,396 shots in 2012 and 403 in 2013. The source coverage and other changes across seasons matter for interpreting this difference.

## Season coverage

Games matching both boxes is a count of games whose attempts, makes, and points from the floor agree for both teams. A missing or different box is documented in team_game_audit.csv. The explorer shows the recorded attempts and gives those coverage counts for each season.

| Season | Recorded regular games | Both boxes match | Attempts | Made | Field goal points | Make rate | Points per attempt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2011 | 203/204 | 202 | 26,640 | 11,605 | 25,468 | 43.6% | 0.956 |
| 2012 | 202/204 | 182 | 26,863 | 11,515 | 25,548 | 42.9% | 0.951 |
| 2013 | 203/204 | 152 | 26,868 | 11,361 | 24,606 | 42.3% | 0.916 |
| 2014 | 203/204 | 201 | 26,898 | 11,772 | 25,424 | 43.8% | 0.945 |
| 2015 | 204/204 | 202 | 26,681 | 11,335 | 24,635 | 42.5% | 0.923 |
| 2016 | 201/204 | 197 | 27,121 | 11,961 | 26,089 | 44.1% | 0.962 |
| 2017 | 204/204 | 196 | 27,694 | 12,217 | 26,846 | 44.1% | 0.969 |
| 2018 | 201/203 | 188 | 27,659 | 12,315 | 27,326 | 44.5% | 0.988 |
| 2019 | 202/204 | 198 | 27,695 | 11,749 | 26,231 | 42.4% | 0.947 |
| 2020 | 131/132 | 126 | 17,866 | 7,972 | 17,863 | 44.6% | 1.000 |
| 2021 | 192/192 | 184 | 26,265 | 11,413 | 25,616 | 43.5% | 0.975 |
| 2022 | 216/216 | 212 | 29,371 | 12,985 | 29,312 | 44.2% | 0.998 |
| 2023 | 240/240 | 236 | 32,805 | 14,459 | 32,597 | 44.1% | 0.994 |
| 2024 | 240/240 | 238 | 32,761 | 14,349 | 32,405 | 43.8% | 0.989 |
| 2025 | 286/286 | 286 | 38,535 | 16,926 | 38,533 | 43.9% | 1.000 |
| 2026 | 330/330 | 329 | 45,297 | 20,480 | 46,692 | 45.2% | 1.031 |

## Agreement with Data (1)

All 42,193 of the 42,193 field goal attempts match the public file for 2025 across 312 games. This comparison includes the game, period, clock, team, shooter, play type, makes, points, and both coordinates. The two files have the same upstream source, so agreement checks that the data were joined and interpreted consistently. Box score differences in recording individual shooters remain visible in the player audit.

The source coordinates are recorded at coarse precision. The exact rim coordinate can hold many shots at the same point. Near the three point line the recorded shot value and the geometric zone are separate fields. A shot inside a court area can have an uncertain attempt value, especially on a miss. Aggregates by geometric area preserve those attempts, and their observed points only count actual makes.
