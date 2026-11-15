# Review of the supplied archive

The supplied archive supports a study of **where recorded 2025 WNBA field goal attempts occur and how likely those attempts are to score**. Every model input in this update comes from `Data (1).zip`. The original archive is unchanged.

The archive contains **45 files and one empty directory**. Its SHA-256 is `22a86860e179ce40ed34648c592bbd384297ddd5833000117973308a915a2120`. The [file manifest](results/archive_manifest.csv), [full inventory](results/archive_audit.json), and [supporting-table checks](results/data1/supporting_tables_audit.json) record each file's treatment. Paper text and raw tables remain local.

## What the event and box-score checks establish

The original WNBA event file has 121,342 event records and 42,193 field goal attempts across 312 games. The descriptive regular-season sample excludes the All-Star game, the standalone Commissioner's Cup final, and playoffs: **38,535 attempts, 16,926 makes, and 38,533 field goal points in 286 games**. Of these attempts, 38,441 fit in the displayed half court; 94 longer attempts remain in the season totals.

All **624 game/team combinations** match the supplied team boxes for attempts, makes, and field goal points. That check does not establish that every event is attributed to the correct shooter. The player check finds **18 disagreeing player/game attempt totals in eight games**. The same players' makes and field goal points agree. Both source versions are retained; no missed shot is silently reassigned.

All prediction models use the same sample after excluding those eight games. Their within-season player histories also exclude those games. The [exclusion list](results/data1/excluded_games.csv) and [player reconciliation](results/data1/player_box_reconciliation.csv) make that decision reviewable. Model results therefore describe the retained, reconciled sample, rather than every game in the archive. This post-game source-quality filter is not a feature available to a live prediction system.

| Modelling interval | Half-court attempts | Games | Purpose |
| --- | ---: | ---: | --- |
| May 16–August 9 | 25,751 | 191 | Fit parameters and preprocessing |
| August 10–26 | 5,995 | 45 | Select settings and fit any explicitly labelled calibration/ensemble layer |
| August 27–September 11 | 5,626 | 42 | Later-game benchmark |
| September 14–October 10 | 3,311 | 24 | Playoff transfer check |

These 2025 periods have been examined in earlier development. They are **reused benchmarks**, not an untouched final season. The archive does not supply a second WNBA play-by-play season for a genuinely new season test.

The original event file also has **88 shot-score-update conflicts**, affecting 27 regular-season games. The model avoids score margin and sequence-derived play features. Valid shot locations and correct game totals do not validate possessions, passes, dribbles, or the previous ten basketball actions.

## All seven Wehoop tables

| File within the archive | Records | Finding and use |
| --- | ---: | --- |
| `original/wehoop_wnba_pbp.csv` | 121,342 | Primary 2025 event source. Used for recorded locations and outcomes, with the documented quality filters. |
| `original/parsed/wehoop_wnba_pbp_parsed.csv` | 121,165 | Two malformed records and 3,054 well-formed records with college or shifted identifiers. The entire derived export is excluded. |
| `original/wehoop_wbb_pbp.csv` | 1,993,401 | College women's basketball, labelled season 2026, with game dates spanning 2025–2026. It is not a second WNBA season. |
| `original/parsed/wehoop_wbb_pbp_parsed_1.csv` | 1,993,401 | Parsed college data. Inventoried and checked for record structure; outside the WNBA modelling cohort. |
| `WNBA_player/wnba_player_box.csv` | 120,980 | Player/game boxes spanning 2003–2025. Supplies ID-based names, reconciliation, and fixed 2022–2024 preseason histories. Current-game or future boxes are not predictors. |
| `WNBA_player/wnba_player_demographics.csv` | 1,145 | Unique NBA `PERSON_ID` records. This is a different identifier namespace from ESPN athlete IDs; no name-based or numeric-coincidence join is assumed. |
| `WNBA_Team/wnba_team_box.csv` | 10,134 | Team/game boxes used for team-level reconciliation. The file covers 2003–2025 with no 2005 entries; the model's 2025 checks are complete. |

The primary event file lacks authoritative two/three-point attempt values for every missed shot. Actual scored points remain observed. A joint model of outcomes **0, 2, and 3** can therefore estimate field goal points without inventing missed-shot labels:

\[
P(\text{make})=P(2)+P(3),\qquad E[\text{FG points}]=2P(2)+3P(3).
\]

This predicts the observed scoring mix conditional on an attempt. It does not identify the counterfactual reward from stepping behind the line, and it excludes free throws, unrecorded shooting-foul opportunities, rebounds, and future possession value.

## The other tabular files

The 25-row all-time franchise record table passes both `wins + losses = games` and its win-percentage calculation. Its cumulative, undated snapshot is background context rather than a pre-shot feature.

The 13 Basketball Reference exports are valid 28-field CSV tables despite their `.txt` extensions. They contain duplicate `G` and `MP` column names. Their normalized rates cannot be added as raw shot counts, and player/team-stint rows need an explicit aggregation rule.

| Export season | Data rows | Export season | Data rows |
| --- | ---: | --- | ---: |
| 2013 | 156 | 2020 | 162 |
| 2014 | 158 | 2021 | 183 |
| 2015 | 177 | 2022 | 198 |
| 2016 | 174 | 2023 | 175 |
| 2017 | 178 | 2024 | 183 |
| 2018 | 173 | 2025 | 234 |
| 2019 | 169 | — | — |

The 2025 full-season statistics would reveal information from after early-season prediction dates. The pre-shot models instead use ID-matched 2022–2024 box counts and completed earlier eligible 2025 games.

| Supporting file | Records | Treatment |
| --- | ---: | --- |
| `wnba_player_salaries.csv` | 915 | In 158 rows, salary year does not equal statistics year. Contract and performance grains require separate treatment. |
| `wnba_player_salaries_long.csv` | 288 | Statistics are labelled 2024; 225 rows do not have a matching salary year. These are not 288 independent current-season performance records. |
| `wnba_team_salary_summary.csv` | 91 | Annual team salary context, with currency-formatted fields; excluded from shot predictors. |
| Literature-search CSV dated March 22, 2026 | 70 | Contains 20 exact duplicate rows and 49 distinct nonmissing DOIs. It is a reading catalogue, not 70 independent studies or validation datasets. |

The five-sheet dictionary contains `Player_Statistics`, `Team_Statistics`, `Data Category Definition`, `Sheet1`, and `Full_Filled`. It mixes sources and season/game/career definitions. Some `3PA` descriptions say “points attempted”; attempts and points must remain separate quantities. The supplied count identities, rather than that wording, determine the calculations. The dictionary does not establish the meaning of event coordinates or provide a shot-clock field.

## Review of all 19 document files

The documents were extracted and reviewed for their research question, data, method, and relevance to this study. A journal article, a thesis, a preprint, a poster, and a background note do not provide the same type of evidence. Two PDFs are versions of the same profiling paper and are counted once as a study.

| Supplied document | What it contributes here |
| --- | --- |
| *Injury in WBALL background with references* | A separate injury-surveillance research direction. The archive does not contain the proposed injury-surveillance observations, and injury or protected characteristics are not shooting features. |
| Corona, *The Application of Artificial Intelligence Metrics in the NBA* | Broad organizational background. Its examples do not establish the predictive accuracy of this WNBA model. |
| Ferrario, *Basketball Analytics: The Use of Data Science to Describe and Predict the Performance of an NBA Team* | A thesis comparing game-outcome models and ensembles. Its target is a game result, so its accuracy cannot be compared with per-shot Brier score or AUC. |
| Burnett, *The Impact of Data Analytics in Basketball* | Historical NBA shot-selection trends and the limits of available tracking. Descriptive trends do not establish why an individual player chose a shot. |
| Hobbs et al., *Playing unpredictably: measuring the entropy of ball trajectories* | Uses actual ball movement. Entropy of our recorded shot locations would be a different quantity, not a replication of trajectory entropy. |
| Sarlis and Tjortjis, *Sports analytics—Evaluation of basketball players and team performance* | A review of performance measures, normalization, team composition, and uncertainty. Counting production and estimating shooting skill remain different tasks. |
| Wang et al., *The Effect of Basketball Analytics Investment on NBA Team Performance* | An organizational staffing study with a different outcome and design. It does not imply that a larger GPU bill guarantees a better shot model. |
| Zuccolotto, Manisera and Sandri, *Big data analytics for modeling scoring probability* | Motivates contextual prediction and validation across settings. Its shot-clock and pressure variables must not be replaced by period clock or unreliable score margin. |
| Mishra, *AI and analytics in sports: Leveraging BERTopic to map the past and chart the future* | A structured literature-mapping method. Topic models organize papers; they do not validate basketball outcome probabilities. |
| Agha et al., *The Effect of National Origin and Skin Color on Playing Time in the WNBA* | A distinct playing-time and bias question. Its sensitive attributes are not imported into the shot model. |
| Campaz, *Latent Structure of Situational Efficiency Variables in Elite Women's Basketball* | A thesis using team-level EuroLeague indicators and factor analysis. Associations between game totals do not determine a shot-level feature set or establish causation. |
| Cotta-Ortega et al., *Analysis of game situations in the 3-point shot in women's basketball* | A small observational case study emphasizing defensive pressure, passes, and context. Those richer annotations are absent from the supplied event table. |
| Courel-Ibáñez et al., *Profiling high performers in elite women's basketball*—published version | Suggests role-aware comparison and normalization. Roles would need to be learned from information available before prediction, with a definition agreed by the research group. |
| *Profiling high performers*—manuscript version | The same study as the preceding published PDF, with different pagination. It is not a second independent replication. |
| Ibáñez et al., *Redefining player roles in professional women's basketball* | A distinct functional-role study using Spanish-league box scores. Its roles are not automatically WNBA positions, and its data overlap in setting with the profiling study. |
| Javadpour et al., *Optimizing the best play in basketball using deep learning* | Uses richer college-team play, defender, passing, and shot-clock information. Predicting a recorded attempt is not the same as selecting the best available play. |
| Jepsen, *Determinants of Career Exits and Career Breaks in Women's Professional Basketball* | A labor-market and career-duration question, not a shot-conversion model. Career outcomes and demographic attributes are not features here. |
| Juliano and Thakkar, *R Analytics Tool to Study the Performance of the D1 Women's Basketball Team at Sacred Heart University* | A one-page dashboard poster using a different activity/wearable data log. It informs presentation and definitions, not a replication on our event file. |
| Bonato and Hinds, *Network analysis and link prediction in competitive women's basketball* | Motivates temporal network validation. Passing connections and defensive matchups need validated actor roles and interaction records; future-event labels cannot become pre-shot predictors. |

## What the archive can support next

The present data can support recorded shot-location summaries, conditional make probabilities, partial pooling across shooters, and an observed-outcome field goal points model. It can also support sensitivity checks for spatial approximations, priors, model settings, and recorded-coordinate precision.

Validated possessions, nonshot opportunities, actual shot-clock values, defensive pressure, and authoritative missed-attempt values are separate data requirements. The [questions for the research group](DATA_REQUESTS.md) prioritize them. No message has been sent to the group.
