# Changelog

All notable changes to SCR-Screen are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-17

### Added
- `scan --groups CSV` (columns `bus`, `group`): screen nearby buses together with WSCR in a network scan. Each grouped bus gets a plant of `--plant-mw`; results, CSV/JSON output and the report include each group.
- Interactive scan reports recalculate group WSCR, flags, the "Lowest group WSCR" card and the flagged count live as the plant size and thresholds change.
- Bundled example `ieee39_groups_example.csv` (G1: buses 11 and 13; G2: buses 16 and 17), copied by `scr-screen example`.
- "File not found" errors now point to the `scr-screen-example` folder when the file is there (a common slip after `scr-screen example`).

### Changed
- Reports show the "Plants screened together (WSCR)" section right after the SCR chart.
- Scan reports: the results column "POI" (which showed "pandapower index 29") is now "Model index" and shows the number only, with a note explaining it counts from 0. In scan CSV/JSON output, `poi_name` holds the same number.
- The "Flagged" card counts groups as well as plants in interactive reports, matching the static count.
- Interactive demo report regenerated with the two example groups.

### Fixed
- SCR-Screen Lite page (`docs/lite/`): on phones the calculator was about 24 px wider than the screen, so the page scrolled sideways. The calculator now fits the screen width.
- Threshold labels ("2", "3") on the SCR and method-comparison charts no longer overlap the text above the chart.

## [0.1.0] - 2026-10-04

First public release.

### Screening
- Short-circuit ratio (SCR) for single plants and weighted SCR (WSCR) for groups of plants assumed fully interacting (ERCOT/NERC formulation).
- Rating basis in MW (default) or MVA.
- Flags with user-configurable thresholds; defaults below 2 very weak, 2 to below 3 weak (HVDC planning practice, IEEE Std 1204-1997).
- Largest plant each location can host before a weak flag (SCMVA ÷ weak threshold).

### Short-circuit calculation (network mode)
- Classical flat-start method (1.0 pu pre-fault, no correction factors), built on the network impedance matrix.
- IEC 60909 method via pandapower (max and min cases).
- Inverter-based resource contribution always excluded, as NERC's SCR definition requires.
- Buses with no path to any source are skipped and listed, instead of stopping the scan.
- Bus scan: SCR at every bus for a hypothetical plant size.

### Your own network
- Reads pandapower JSON (`.json`), pandapower Excel (`.xlsx`), and MATPOWER (`.m`, `.mat`).
- `scr-screen check` lists missing short-circuit data and unsupported elements before scanning.
- `scr-screen convert` turns any supported file into Excel or JSON, adding empty short-circuit columns to fill in.

### Cost screening
- Screening-level interconnection cost per candidate bus: synchronous condenser to reach a target SCR, gen-tie line, and POI substation. All costs are user inputs; network upgrades are excluded.
- `scr-screen sites-template` creates the per-bus site cost file.
- Target check: buses below the target SCR are listed in an alert, each with the largest plant that meets the target and the condenser alternative; "SCR after condenser" shown for every bus.

### SCR-Screen Lite
- Browser calculator for direct mode (SCR, WSCR, flags, largest plant, target check, condenser and cost), responsive and theme-safe for embedding in other websites. Published under `docs/lite/`.

### Reports and interfaces
- Self-contained HTML report (works offline; print to PDF from any browser): summary cards, network map from bus coordinates or an automatic layout, SCR chart, method comparison (classical vs IEC 60909), largest-plant chart, cost ranking, results tables, method notes, and disclaimer.
- Interactive what-if inputs in scan reports: plant size slider, flag thresholds, target SCR, condenser parameters and costs, and per-bus gen-tie distance and POI cost, all recalculated instantly in the browser.
- Animations that respect the reader's reduced-motion setting and are disabled when printing.
- Command line: `scr-screen example | template | run | scan | check | convert | sites-template`, with `--open` to show the report when ready.
- `scr-screen example` copies bundled example files (IEEE 39-bus network with assumed data, illustrative site costs, plant template) so a scan can be tried right after installing.
- CSV and JSON results; Python API.

### Documentation and verification
- README, design specification, walkthrough notebook, IEEE 39-bus example with documented assumed short-circuit data.
- Automated tests on Python 3.10 and 3.13 for every change, with hand-calculated expected values.
- Verification record (`docs/verification.md`), including an independent hand check of IEEE 39-bus bus 12.
