# Research pipeline

Read [the current methods and results](summary.md), [all file archive review](ARCHIVE_REVIEW.md), and [data questions](DATA_REQUESTS.md). The [live page](https://kevinyamada.github.io/wnba-shot-atlas/) is built entirely from the Data (1) analysis in `results/data1/`.

The [event based EPV prototype](POSSESSION_VALUE.md) adds audited control episodes, ordinary free throws and offensive rebounds, with CPU model fitting and independent verification. It uses only the supplied archive. Its strict retained subset is not an official possession feed, and the archive cannot support full spatial xT without nonshot action data. VS Code tasks provide desktop CPU reconstruction and fitting.

The [meeting brief](MEETING_BRIEF.md) and [diagnostics](MEETING_DIAGNOSTICS.md) explain exclusion coverage and where prediction gains occur. `meeting_clock_baseline.py` adds one fixed training only clock reference; `meeting_diagnostics.py` builds the tables and three figures; `verify_meeting_diagnostics.py` independently verifies them. These exploratory checks preserve the original fitted models and published site data.

The [ordinary tail recovery extension](RECOVERY.md) is now implemented: special/review sequences remain excluded, then a live miss, defensive rebound and corroborating action permit a later tail to resume. It adds 5,394 entry states; a stricter second restart policy adds 4,339. The original score/order exclusions and artifacts stay fixed. `verify_recovery.py` independently checks the source decisions, every expanded target and feature count, saved CPU inference, paired comparisons and live publication. The [meeting page](https://kevinyamada.github.io/wnba-shot-atlas/meeting/) provides the demo and a print friendly view.

The archive is the only basketball source. `data/` holds private working files and is ignored. `results/archive_audit.json` and `archive_manifest.csv` account for all 45 files; `results/data1/` contains current aggregate results. Individual event predictions, raw experiment tasks and posterior arrays are excluded from Git. Earlier public release outputs were removed from the current branch and remain available in Git history.

Compatibility commands `prepare_data.py`, `run_comparisons.py`, `export_site_data.py` and `evaluate_predictions.py` route to the archive only implementation. `gp_model.py` points to the Modal workflow. There is no public download fallback.

`requirements.txt` records the actual Python 3.13 CPU analysis versions. The separate Python 3.12 GPU image in `modal_study.py` pins its own tested environment, mirrored by `requirements_gp.txt`. `verify_methods.py` and `check_numerics.py` use generated synthetic arrays only to check mathematics; they add no basketball observations.
