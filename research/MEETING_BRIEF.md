# What we can do before the meeting

We can make the existing project clearer and more useful without collecting another dataset. The current shooting analysis and basic possession-value prototype are complete. The next work is to understand their limits and improve how we handle the data already supplied.

## Three findings worth discussing

1. **Many exclusions are precautions, not confirmed bad data.** Of 595 excluded periods, 485 were excluded only because our code conservatively avoids special-foul/free-throw or overturned-review situations. These may be legitimate events. Carefully supporting those situations could recover more of Data (1), but we must validate the sequences before including them. This does not mean all 485 periods can be recovered.
2. **Knowing the time left explains much of the apparent model benefit.** In later regular games, the model's clearest improvement appears in the 120 entry states with 2–24 seconds left in the period. Outside that window, neither the selected model nor Markov model clearly beats the simple average. A separate training-only clock baseline performs about as well as the more complicated models. The comparison is exploratory; these games have already been examined.
3. **The useful next step is better event handling and a stronger simple reference.** Extra GPU searches would not resolve the missing pass records or source disagreements. Keep the current models frozen, test difficult recorded-event cases carefully, and use the simple clock reference when assessing future improvements.

“Period clock” means time left in the quarter or overtime. It is not the shot clock. The project estimates remaining points at recorded events; it does not yet value individual passes, movements, or player decisions.

## Work for the next three days

- **First day — completed:** diagnose excluded periods, check which situations benefit from modelling, fit one small clock-only reference, and prepare three charts. Everything ran on the desktop CPU using Data (1); the original models and website data were kept unchanged.
- **Second day — proposed:** inspect representative technical-free-throw and review sequences against the original records. Write small tests for the cases we can interpret reliably. Change the reconstruction only where the evidence supports it; keep unresolved cases excluded.
- **Third day — proposed:** rerun checks after any supported changes and rehearse a short walkthrough: what works, what remains uncertain, and the specific decisions needed from the group.

## A short meeting update

“I've completed the first analysis using only the supplied archive. I then checked why the prediction gains are small. Much of the benefit seems to come from knowing how little time remains, and a simple clock rule performs about as well as the larger models. I also found that many excluded periods are excluded because our code handles special situations cautiously, not because the records are definitely wrong. My next priority is to handle those situations safely and use more of the existing archive. For full pass and movement valuation, we would still need records of those actions and their locations.”

Ask the group which event-order and correction fields are authoritative, and whether passes/movement with start and end locations exist in another supplied file or dataset. For example, game **401736112** records **14** Rhyne Howard attempts in the event list and **15** in the player box. We preserve both versions rather than guessing which is right.

## What to show

- [Coverage chart](results/data1/meeting/coverage_by_team.png): which teams' periods survive the strict checks. This measures data coverage, not team ability.
- [Time-left comparison](results/data1/meeting/entry_error_by_clock.png): why the small overall prediction gain needs explanation.
- [Errors at different recorded states](results/data1/meeting/error_by_state.png): whether a complicated model adds value beyond simple references.

[Detailed calculations and limits](MEETING_DIAGNOSTICS.md) · [Source-disagreement examples](results/data1/followup/attempt_discrepancy_examples.csv) · [Final checks](results/data1/meeting/final_verification.json)
