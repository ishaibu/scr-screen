# Changelog

All notable changes to SCR-Screen are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

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

### Reports and interfaces
- Self-contained HTML report (works offline; print to PDF from any browser): summary cards, network map from bus coordinates or an automatic layout, SCR chart, method comparison (classical vs IEC 60909), largest-plant chart, cost ranking, results tables, method notes, and disclaimer.
- Interactive what-if inputs in scan reports: plant size slider, flag thresholds, target SCR, condenser parameters and costs, and per-bus gen-tie distance and POI cost, all recalculated instantly in the browser.
- Animations that respect the reader's reduced-motion setting and are disabled when printing.
- Command line: `scr-screen template | run | scan | check | convert | sites-template`, with `--open` to show the report when ready.
- CSV and JSON results; Python API.

### Documentation and verification
- README, design specification, walkthrough notebook, IEEE 39-bus example with documented assumed short-circuit data.
- Automated tests on Python 3.10 and 3.13 for every change, with hand-calculated expected values.
- Verification record (`docs/verification.md`), including an independent hand check of IEEE 39-bus bus 12.
