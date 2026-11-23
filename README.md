# WNBA Shot Atlas

[WNBA Shot Atlas](https://kevinyamada.github.io/wnba-shot-atlas/) covers 1997 to 2026 from public wehoop releases. See the [data pipeline and methods](research/public_atlas/README.md) and the [public results](research/results/public_atlas/study.md). The [original 2025 study](https://kevinyamada.github.io/wnba-shot-atlas/study/) remains available.

[Kevin Yamada · Portfolio](https://kevinyamada.github.io/)

An interactive study of recorded WNBA shot locations, conditional make probabilities, observed field goal points and a source limited event based possession value prototype. **All basketball inputs come from the supplied Data (1).zip.**

**[Explore the live app](https://kevinyamada.github.io/wnba-shot-atlas/) · [Methods and results](research/summary.md) · [Archive and literature review](research/ARCHIVE_REVIEW.md)**

The descriptive sample contains 38,535 regular season attempts in 286 games, with 38,441 attempts in the half court view. Explore teams, 1/2/4 foot squares, actual field goal scoring leaders, observed make rates, Bayesian predictions and posterior uncertainty. The app also compares distance, logistic, IDW, kriging, SPDE, four chain Bayesian GP, GPU boosting and ensemble models.

The website leads with the court explorer, shot density around the arc, prediction differences with uncertainty, spatial transfer errors, and observed scoring after misses and rebounds. Complete model tables, source limits and mathematical details sit in expandable notes. The three project links are collected in the footer. No basketball observations were added for these presentation changes.

## Source and limitations

The original 45 file archive has SHA256 `22a86860e179ce40ed34648c592bbd384297ddd5833000117973308a915a2120`. It supplies 2025 WNBA events, historical player/team boxes and supporting tables and papers. No external basketball release or additional season enters the active pipeline.

All 624 game/team shot totals and final scores reconcile. Eighteen player/game attempt totals disagree across eight games; those games remain in descriptive maps and are excluded uniformly from the player context shot models. The source also contains 88 shot score update conflicts, so score margin is excluded from the primary shot comparison. [Review the exclusions](research/results/data1/excluded_games.csv).

The model cohorts contain 25,751 training attempts, 5,995 validation attempts, 5,626 later regular season attempts and 3,311 playoff attempts. All are previously examined 2025 benchmarks. They do not establish performance in an untouched season. Missing missed shot values are handled by a joint 0/2/3 outcome model, rather than invented attempt labels. This does not yet estimate expected threat or causal shot selection effects.

The [desktop follow up](research/LOCAL_FOLLOWUP.md) gives concrete source disagreement examples and additional CPU refit and source exclusion sensitivity results. It uses the same Data (1) archive.

The [event based possession value extension](research/POSSESSION_VALUE.md) reconstructs ordinary scoring episodes, including free throws and offensive rebound continuation. Strict source checks retain 662 of 1,257 periods and 25,306 entry states. CPU stage mean, Markov, spline and context models use validation only selection. The selected model's later game improvement is uncertain. This is a screened, retrospectively qualified EPV prototype; full spatial xT still needs nonshot action data absent from the archive. No additional Modal compute is used. The [EPV verification record](research/results/data1/possession/final_possession_verification.json) is generated after publication.

The [meeting walkthrough](https://kevinyamada.github.io/wnba-shot-atlas/meeting/) and [speaking brief](research/MEETING_BRIEF.md) present the completed work. The [recovery extension](research/RECOVERY.md) adds 5,394 ordinary episode entry states after the final hazardous event and a corroborated live rebound, raising the total to 30,700. A second restart check adds 4,339. Fixed setting CPU refits improve the later context benchmark but do not establish an advantage over a simple clock rule. Original results remain frozen. [Earlier diagnostics](research/MEETING_DIAGNOSTICS.md) explain exclusions and clock effects.

## View locally

```bash
python -m http.server 8001
```

Open http://localhost:8001/. Viewing needs no raw source, model fitting, API key or server backend. HTTP is required for loading `assets/data.json`.

## Reproduce the analysis

The [methods note](research/summary.md#reproduce-and-verify) gives complete commands and numerical environments. Start with the exact supplied archive. Preparation verifies its checksum and performs no network data download. Raw tables, paper text, event predictions, posterior arrays and full billing exports stay outside Git.

The GPU study uses Modal H100 80GB devices, up to four concurrently, and records source hashes, diagnostics, seed stability, validation only choices and cost. [Compute usage](research/results/data1/compute_usage.json) distinguishes measured GPU allocation from gross Modal resource usage before credits. The original target was at least US$20 useful GPU work, with a US$40 total ceiling. A later user update reported only US$1 credit remaining: all paid study apps were stopped, and remaining work runs on the desktop CPU. The compute record distinguishes completed result time from total resource usage, including interrupted jobs.

The [final verification record](research/results/data1/final_verification.json) is generated **after** analysis and publication. It reopens the original ZIP, checks all 45 hashes, independently rebuilds row labels and historical predictors, recomputes metrics, verifies every website aggregate, and checks the live data and browser interactions.

## Repository guide

| Path | Purpose |
| --- | --- |
| `index.html`, `style.css`, `app.js` | Interactive article and accessible court explorer |
| `assets/data.json` | Data1 aggregates, selected GP surface and model tables |
| `research/prepare_data1.py` | Archive only source preparation and reconciliation |
| `research/data1_cpu.py` | Reference models, spatial folds, mesh refinement and descriptive analysis |
| `research/gpu_models.py`, `research/modal_study.py` | Bounded H100 model study |
| `research/summarize_data1.py` | Validation only selection, keyed evaluation and game bootstraps |
| `research/verify_data1.py`, `research/check_site.py` | Final independent source/results and real browser checks |
| `research/possession_reconstruction.py`, `research/possession_models.py` | Desktop CPU event based EPV prototype |
| `research/verify_possession_value.py` | Independent rewards, timing, Markov and EPV publication checks |
| `research/possession_recovery.py`, `research/recovery_models.py` | Corroborated ordinary tail recovery and fixed setting CPU refits |
| `research/verify_recovery.py`, `meeting/index.html` | Independent recovery checks and printable meeting walkthrough |
| `research/results/data1/` | Current public aggregate outputs and audit records |
| `research/DATA_REQUESTS.md` | Prepared research group questions; not sent |

## Publication

This repository deploys its root from `main` to **https://kevinyamada.github.io/wnba-shot-atlas/** through GitHub Pages. It began as an extraction of the older portfolio project. This archive only update replaces the older public download outputs in the current branch; Git history preserves the earlier work.

Kevin Yamada · University of Toronto. Independent research, unaffiliated with the WNBA or ESPN. The supplied event tables identify SportsDataverse/wehoop and ESPN as upstream providers.
