# Recount from the raw files

All 125 pinned raw files were hashed. 0 differ from the source manifest.

The raw shot files hold 902,729 regular season and playoff field goal attempts, 389,216 makes and 858,999 field goal points in 6,982 games with shot records.

| phase | games_with_shots | attempts | makes | points |
| --- | --- | --- | --- | --- |
| regular | 6,461 | 834,428 | 359,786 | 793,930 |
| playoffs | 521 | 68,301 | 29,430 | 65,069 |

## By shot feed

| feed | games_with_shots | attempts | makes | points | mapped_half | other_half | unknown_location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WNBA Stats 1997 to 2001 | 1,021 | 120,948 | 50,837 | 110,135 | 91,714 | 86 | 29,148 |
| ESPN 2002 to 2010 | 2,204 | 274,074 | 116,132 | 254,072 | 213,273 | 334 | 60,467 |
| ESPN 2011 to 2026 | 3,757 | 507,707 | 222,247 | 494,792 | 506,650 | 1,041 | 16 |

## Location

811,637 attempts are on the mapped half, 1,461 on the other half and 89,631 have an unknown location. The unknown group is 89,595 recorded exactly at the basket through 2010, 20 where the two coordinate pairs disagree, 16 outside the court and 0 with missing coordinates.

25 attempts carry a team ID that is neither the home nor the away team in the schedule, so the two coordinate pairs cannot be matched. 5 of them sit exactly at the basket in the raw pair and are counted in the first group here. The published build tests the signed pair first and files all of them under disagreeing pairs. Both routes give the same unknown total.

| season | phase | attempts | team_not_in_game | unknown_location |
| --- | --- | --- | --- | --- |
| 2,003 | regular | 27,676 | 22 | 5,722 |
| 2,004 | regular | 25,301 | 3 | 5,777 |

## Attempt value

The source identifies 361,241 two point attempts (308,649 made) and 173,041 three point attempts (80,567 made). 368,447 misses have no recorded value. Points check: 2 × 308,649 + 3 × 80,567 = 858,999.

## Rows left out of the total

Free throws: 227,825 rows. Other rows that are not field goals: 94. Special games: 4,507 attempts in 25 games (3,462 of them from 2011 on).

| phase | games | attempts | makes | points |
| --- | --- | --- | --- | --- |
| special | 25 | 4,507 | 2,080 | 4,774 |

## Scored rows without a shot label

In regular season and playoff games, 45 ESPN rows carry a score value of 2 or 3 (95 points) under a turnover, foul, not available or no shot label. They are outside the totals above. They fall in 24 team games. 23 of those have a team box, and adding the rows reproduces the box count of made field goals in 21. A further 49 rows with those labels have a score value of 0.

| season | scored_rows_without_shot_label | points_on_those_rows | team_games_with_those_rows | team_games_with_a_box | box_makes_reproduced_when_added |
| --- | --- | --- | --- | --- | --- |
| 2,012 | 29 | 59 | 15 | 14 | 14 |
| 2,018 | 4 | 9 | 4 | 4 | 4 |
| 2,019 | 1 | 2 | 1 | 1 | 1 |
| 2,023 | 8 | 19 | 2 | 2 | 2 |
| 2,024 | 3 | 6 | 2 | 2 | 0 |

## ESPN team boxes on identical games

Games from 2003 on where both teams have a complete box.

| measure | team_boxes | shot_feed | difference |
| --- | --- | --- | --- |
| attempts | 743,703 | 740,071 | -3,632 |
| makes | 322,490 | 320,856 | -1,634 |
| points | 714,207 | 710,592 | -3,615 |

Box three point makes 69,227, shot feed three point makes on the same games 68,880.

## Comparison with published numbers

Live site files were not fetched in this run.

| item | recount | published | difference |
| --- | --- | --- | --- |
| findings.json mapped | 811,637 | 811,637 | 0 |
| findings.json other_half | 1,461 | 1,461 | 0 |
| findings.json unknown | 89,631 | 89,631 | 0 |
| findings.json attempts | 902,729 | 902,729 | 0 |
| verification.json attempts | 902,729 | 902,729 | 0 |
| findings.json makes | 389,216 | 389,216 | 0 |
| verification.json makes | 389,216 | 389,216 | 0 |
| findings.json points | 858,999 | 858,999 | 0 |
| verification.json points | 858,999 | 858,999 | 0 |
| stated total attempts | 902,729 | 902,729 | 0 |
| stated total makes | 389,216 | 389,216 | 0 |
| stated total points | 858,999 | 858,999 | 0 |
| stated attempts, WNBA Stats 1997 to 2001 | 120,948 | 120,948 | 0 |
| stated attempts, ESPN 2002 to 2010 | 274,074 | 274,074 | 0 |
| stated attempts, ESPN 2011 to 2026 | 507,707 | 507,707 | 0 |
| season_coverage.csv attempts, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv makes, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv points, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv mapped_half, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv other_half, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv unknown_location, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv games_with_shots, season rows that differ | 0 | 0 | 0 |
| season_zones.csv, area rows that differ | 0 | 0 | 0 |
| season_zones.csv attempts | 902,729 | 902,729 | 0 |
| local site season files, area rows that differ | 0 | 0 | 0 |
| local site all.json, area rows that differ | 0 | 0 | 0 |
| local site all.json attempts | 902,729 | 902,729 | 0 |
| local site all.json makes | 389,216 | 389,216 | 0 |
| local site all.json points | 858,999 | 858,999 | 0 |
| local site all.json attempts, regular | 834,428 | 834,428 | 0 |
| local site all.json attempts, playoffs | 68,301 | 68,301 | 0 |
