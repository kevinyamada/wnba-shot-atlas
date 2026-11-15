# Questions for the research group

The current models use only the supplied `Data (1).zip`. These requests would help resolve source problems and define a later study; they are not additional inputs to the present analysis.

1. **Shooter attribution.** Can we get the authoritative event/shooter identifiers or corrections for games `401736112`, `401736137`, `401736145`, `401736155`, `401736217`, `401736227`, `401736274`, and `401736355`? Eighteen player/game attempt totals disagree with the player boxes, while makes, field goal points, and team totals agree. The [difference table](results/data1/player_box_reconciliation.csv) preserves both versions.
2. **Event ordering.** Which identifier is the authoritative order, and are corrections available for the 88 shot-score-update conflicts? Reliable ordering is necessary before reconstructing possessions or recent actions.
3. **Attempt value.** Is an official two/three-point label available for every missed attempt? Scored points are zero for misses, and rounded coordinates are insufficient for resolving shots near the line.
4. **Coordinates.** What do coordinates represent—manual shot location, player position, or ball release? What are the units, origin, basket direction, rounding, and known recording errors?
5. **Shot clock and context.** Can we obtain the actual shot clock, defensive distance/pressure, transition status, and shot categories recorded consistently for makes and misses? Period time remaining is not the shot clock. An assist label populated only on makes cannot be a make predictor.
6. **Possessions and actions.** Are there validated possession IDs, actor roles, passes, dribbles, turnovers, fouls, rebounds, and opportunities where a team could shoot but did not? Ten play-by-play rows are not necessarily ten basketball actions. These are prerequisites for shot-choice or expected-threat models.
7. **Player roles.** Should we use listed positions, or roles learned from prior performance? Can ESPN and NBA player IDs be linked with an authoritative crosswalk? Season-end role classifications must not leak into earlier predictions.
8. **A new evaluation season.** Can the group provide another WNBA season in an updated archive with the same schema and source definitions? The existing WNBA event file is 2025; the college file labelled 2026 is a different competition. A new WNBA season would allow a genuinely new test after model choices are frozen.

A short message to copy if useful:

> I have a first shooting-location and prediction study using the supplied archive. The team totals reconcile, but eight games have player-attempt attribution differences, and some score updates disagree with the event order. Could we get authoritative event/shooter IDs and ordering, two/three-point labels for misses, and documentation for the coordinates? For the later possession/decision model, it would also help to have possession IDs, actual shot clock, nonshot actions/opportunities, and defensive context. Another consistently recorded WNBA season would let us test the chosen model on new data. I can share the discrepancy tables.

This is a prepared draft; it has not been posted or sent.
