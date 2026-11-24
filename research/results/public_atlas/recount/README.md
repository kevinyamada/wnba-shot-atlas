# Recount from the raw files

All 125 pinned raw files were hashed. 0 differ from the source manifest.

The raw shot files hold 902,770 regular season and playoff field goal attempts, 389,257 makes and 859,086 field goal points in 6,982 games with shot records.

| phase | games_with_shots | attempts | makes | points |
| --- | --- | --- | --- | --- |
| regular | 6,461 | 834,451 | 359,809 | 793,978 |
| playoffs | 521 | 68,319 | 29,448 | 65,108 |

## By shot feed

| feed | games_with_shots | attempts | makes | points | mapped_half | other_half | unknown_location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WNBA Stats 1997 to 2001 | 1,021 | 120,948 | 50,837 | 110,135 | 91,714 | 86 | 29,148 |
| ESPN 2002 to 2010 | 2,204 | 274,074 | 116,132 | 254,072 | 213,273 | 334 | 60,467 |
| ESPN 2011 to 2026 | 3,757 | 507,748 | 222,288 | 494,879 | 506,691 | 1,041 | 16 |

## Location

811,678 attempts are on the mapped half, 1,461 on the other half and 89,631 have an unknown location. The unknown group is 89,595 recorded exactly at the basket through 2010, 20 where the two coordinate pairs disagree, 16 outside the court and 0 with missing coordinates.

25 attempts carry a team ID that is neither the home nor the away team in the schedule, so the two coordinate pairs cannot be matched. 5 of them sit exactly at the basket in the raw pair and are counted in the first group here. The published build tests the signed pair first and files all of them under disagreeing pairs. Both routes give the same unknown total.

| season | phase | attempts | team_not_in_game | unknown_location |
| --- | --- | --- | --- | --- |
| 2,003 | regular | 27,676 | 22 | 5,722 |
| 2,004 | regular | 25,301 | 3 | 5,777 |

## Attempt value

The source identifies 361,277 two point attempts (308,685 made) and 173,046 three point attempts (80,572 made). 368,447 misses have no recorded value. Points check: 2 × 308,685 + 3 × 80,572 = 859,086.

## Rows left out of the total

Free throws: 227,825 rows. Other rows that are not field goals: 53. Special games: 4,507 attempts in 25 games (3,462 of them from 2011 on).

| phase | games | attempts | makes | points |
| --- | --- | --- | --- | --- |
| special | 25 | 4,507 | 2,080 | 4,774 |

## Scored rows without a shot label

In regular season and playoff games, 45 ESPN rows carry a score value of 2 or 3 (95 points) under a turnover, foul, not available or no shot label. 41 of them are counted as made baskets in the totals above, because the team box for that game still has that many makes to account for. The rest stay out because the box is missing or already matches the labelled makes. A further 49 rows with those labels have a score value of 0 and stay out.

| season | scored_rows_without_shot_label | points_on_those_rows | counted_as_makes_with_box_support |
| --- | --- | --- | --- |
| 2,012 | 29 | 59 | 28 |
| 2,018 | 4 | 9 | 4 |
| 2,019 | 1 | 2 | 1 |
| 2,023 | 8 | 19 | 8 |
| 2,024 | 3 | 6 | 0 |

## ESPN team boxes on identical games

Games from 2003 on where both teams have a complete box.

| measure | team_boxes | shot_feed | difference |
| --- | --- | --- | --- |
| attempts | 743,703 | 740,112 | -3,591 |
| makes | 322,490 | 320,897 | -1,593 |
| points | 714,207 | 710,679 | -3,528 |

Box three point makes 69,227, shot feed three point makes on the same games 68,885.

## Comparison with published numbers

Live site files were not fetched in this run.

| item | recount | published | difference |
| --- | --- | --- | --- |
| findings.json mapped | 811,678 | 811,678 | 0 |
| findings.json other_half | 1,461 | 1,461 | 0 |
| findings.json unknown | 89,631 | 89,631 | 0 |
| findings.json attempts | 902,770 | 902,770 | 0 |
| verification.json attempts | 902,770 | 902,770 | 0 |
| findings.json makes | 389,257 | 389,257 | 0 |
| verification.json makes | 389,257 | 389,257 | 0 |
| findings.json points | 859,086 | 859,086 | 0 |
| verification.json points | 859,086 | 859,086 | 0 |
| plays.json attempts, WNBA Stats 1997 to 2001 | 120,948 | 120,948 | 0 |
| plays.json attempts, ESPN 2002 to 2010 | 274,074 | 274,074 | 0 |
| plays.json attempts, ESPN 2011 to 2026 | 507,748 | 507,748 | 0 |
| season_coverage.csv attempts, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv makes, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv points, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv mapped_half, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv other_half, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv unknown_location, season rows that differ | 0 | 0 | 0 |
| season_coverage.csv games_with_shots, season rows that differ | 0 | 0 | 0 |
| season_zones.csv, area rows that differ | 0 | 0 | 0 |
| season_zones.csv attempts | 902,770 | 902,770 | 0 |
| local site season files, area rows that differ | 0 | 0 | 0 |
| local site all.json, area rows that differ | 0 | 0 | 0 |
| local site all.json attempts | 902,770 | 902,770 | 0 |
| local site all.json makes | 389,257 | 389,257 | 0 |
| local site all.json points | 859,086 | 859,086 | 0 |
| local site all.json attempts, regular | 834,451 | 834,451 | 0 |
| local site all.json attempts, playoffs | 68,319 | 68,319 | 0 |
