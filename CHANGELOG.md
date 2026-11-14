# Changelog

All notable changes to SCR-Screen are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.5.0] - 2026-11-14

A dashboard for network scans, and accuracy fixes found in a review of the calculations.

### Added
- **`scan --dashboard FILE.html`**: the scan as a one-screen dashboard. A sidebar of views (Overview, Network map, Rankings, Charts, Groups, N-1 outages, EMT study triage, Cost screening, Method comparison, Method & assumptions) with counts of what needs attention; plant size and thresholds stay in place; the Overview shows the network map beside the weakest locations and the details of the selected bus: SCR intact and under the worst single outage, short-circuit MVA, fault current, largest size before a weak flag, Thévenin impedance (R + jX in ohms, X/R) intact and N-1, the worst outage and the reason for its EMT priority. Rankings can be searched, filtered to flagged buses and sorted; the map can be colored by SCR, N-1 SCR or EMT study priority; Print / PDF prints every view; Download CSV saves the results as shown. One self-contained HTML file. The dashboard is built from the report and runs the report's own script, so both show the same numbers. With the classical method, `--dashboard` turns on `--n1` and `--emt-triage`.
- Verification V6: voltage-base conversion of a transformer and a generator, by hand.
- `scr-screen check` and the report notes state how many transformers have a rated voltage different from the bus voltage (converted) and how many have a tap position or turns ratio away from nominal (not modeled).

### Fixed
- **Voltage base (classical method).** A transformer's short-circuit impedance and a generator's X″d are now converted from the equipment's rated voltage to the bus nominal voltage: z × (V rated ÷ V bus)², the transformer on its low-voltage side. Before, the rated voltage was assumed equal to the bus voltage. Results change **only** for networks where a transformer's rated low-voltage winding voltage or a generator's rated voltage differs from its bus's nominal voltage; there the short-circuit MVA was overstated when the equipment is rated above the bus voltage (and understated when below). The bundled IEEE 39-bus example and networks imported from MATPOWER files are not affected.
- **EMT triage: negative reactance.** A line with negative series reactance near a POI is reported as possible series compensation. Reduced network models contain negative-reactance equivalent branches that are not capacitors, so answering `series_compensation = no` for the POI in the `--poi-info` file now removes that trigger, and the trigger text says so.
- **Report: live values.** Numbers embedded for live recalculation now carry full precision. Before, a live value could differ from the Python result in the last displayed digit (seen once: N-1 SCR 5.937 vs 5.938), and the cost table showed "459" where the static table showed "459.0".

### Changed
- The classical method's stated assumption is now precise: transformers are modeled at their **nominal ratio**; tap positions and off-nominal turns ratios are not modeled. The effect is usually small but can reach several percent at buses next to such transformers. Scan reports for the IEEE 39-bus example gain one note line (11 transformers); its numbers are unchanged.
- The public demo page is now the dashboard; the one-page report of the same scan is at `demo/report/`.
- Otherwise, every existing command and option gives the same numbers as v0.4.0.

## [0.4.0] - 2026-11-07

EMT study triage, based on the situations listed in NERC's Reliability Guideline *Recommended Practices for Performing EMT System Studies for Inverter-Based Resources* (December 2024, Chapter 1).

### Added
- **`scr-screen triage`**: a system strength data sheet for each listed point of interconnection (`--buses`): SCR and ESCR with the network intact, under the worst single outage (N-1) and, with `--gen-out`, in a minimum-generation case; WSCR, CSCR and SCRIF for grouped POIs (`--groups`); the Thévenin impedance (R, X, |Z| in pu on 100 MVA and in ohms, X/R) and the fault current in kA for each condition. Printable HTML report (one page per POI), CSV (one row per POI and condition) and JSON.
- **EMT study priority** for each POI: 1 (EMT study recommended, high priority), 2 (EMT study should be considered) or 3 (no screening trigger found), with the reason for each trigger. Priority 1: a strength metric below the very-weak threshold in any condition; series compensation, FACTS or HVdc nearby; a system event that positive-sequence models cannot reproduce; or SCR below the OEM minimum. Priority 2: a metric below the weak threshold; other IBRs nearby; or any other situation answered yes. The priorities are SCR-Screen's ordering of the work; NERC lists the situations without ranking them.
- **Nearby existing IBRs**: in-service `sgen` and `storage` elements whose interaction factor with the POI, max(IF_ij, IF_ji), is at least `--ibr-threshold` (default 0.5).
- **Series compensation, FACTS and HVdc** found in the model (lines with negative series reactance; `svc`, `ssc`, `tcsc`; `vsc`, `dcline`) and their proximity to each POI. HVdc converters, dc lines and STATCOMs are left out of the short-circuit calculation (converter-interfaced, like other IBRs) with a note; an in-service TCSC stops the triage with a message.
- **`--poi-info` file**: yes / no / unknown answers for the situations in NERC's Chapter 1 that a model cannot show (poor positive-sequence stability results; a system event that positive-sequence models cannot reproduce; pre-existing oscillation or oscillatory modes; series-compensated lines; FACTS devices; HVdc lines; high IBR penetration level; specialized protection schemes such as RAS; distance-relay-protected lines with declining fault current levels; a trend of decreasing system strength; a trend of increasing RoCoF or decreasing inertia) and an optional OEM minimum SCR. Unanswered situations are listed as not checked.
- **`scan --emt-triage`** (implies `--n1`): an EMT priority column and an "EMT study triage" section in the scan report, updated live with the plant-size slider and thresholds; `emt_priority` and `emt_triggers` columns in the results CSV and an `emt_triage` entry in the results JSON. `--ibr-threshold` and `--poi-info` work here too.
- Example files `ieee39_triage_example.json` (the IEEE 39-bus case with three assumed, illustrative existing IBRs) and `ieee39_poi_info_example.csv` (illustrative answers and an assumed OEM minimum SCR).
- Verification V5: Thévenin data sheet for bus 12, intact and worst N-1, by hand from the impedance matrix.

### Changed
- Nothing for existing commands and options: without the new options, every output is the same as v0.3.1 (checked file by file on the example cases). The scan report's built-in script gains the triage functions.

## [0.3.1] - 2026-11-07

Rating basis and contingency coverage, completing the metrics in NERC's 2017 comparison table (SCR, CSCR, WSCR-MW, WSCR-MVA, SCRIF).

### Added
- **MVA basis in network scans:** `scan --basis MVA --plant-mva X`. Every ratio, the slider and cost screening use MVA, giving NERC's WSCR-MVA and CSCR divided by nominal MVA ratings, as NERC defines it. (Direct mode has had `run --basis MVA` since v0.1.0.)
- **Plant MVA rating, three ways:** the nameplate (inverter) MVA (`--plant-mva`, `rating_mva`); the inverter count × each inverter's MVA (`--inverters 55 --inverter-mva 4.2` = 231 MVA; `inverters`, `inverter_mva` columns); or, early in a project, an **estimate** from the power factor required at the POI (`--power-factor 0.95`: MVA = MW ÷ 0.95; `power_factor` column, or `run --power-factor`). Estimates are labeled in the console and report. MW stays the default basis.
- **Devices with no active power** (e.g. STATCOMs): `rating_mw` 0 with a `rating_mva`. They count on the MVA basis and are left out, with a note, on the MW basis.
- **Group member sizes:** optional `mw` and `mva` columns in the groups file give a member its own size (an existing plant, or a STATCOM); other members use the scan's plant size. WSCR, SCRIF and CSCR use these sizes, live in the report.
- **Generator outages in N-1:** `--n1` now also removes each synchronous generator unit (external grids, which are network equivalents, are not removed).
- **Minimum-generation case:** `scan --gen-out 30,32` takes the generators at those buses out of service for the whole scan.
- **SCR-Screen Lite:** MW/MVA switch and a Nameplate (MVA) column that also accepts the inverter count × MVA (e.g. `55×4.2`); an optional power factor at the POI estimates blank MVA cells (shown as "≈ … (est.)"); STATCOMs with 0 MW count on the MVA basis.
- **Animated network map in the README**, linking to the interactive demo (`docs/images/network-map.gif`, captured from the demo page).
- Example file `ieee39_groups_mva_example.csv` (illustrative 200 MVA STATCOM at bus 12).
- README thresholds table: IESO (Ontario) and AESO (Alberta).

### Changed
- `--n1` results now include generator outages, so the worst N-1 SCR can be lower at generator buses (in the IEEE 39-bus example, only the nine generator buses change). Line and transformer outages give the same results as v0.3.0.
- The map caption no longer names another tool.
- Results JSON adds `excluded` (0 MW devices left out on the MW basis) and, for groups, `member_ratings` and `member_scrif`. Existing fields are unchanged.

## [0.3.0] - 2026-11-01

Network-aware screening.

### Added
- **SCR with interaction factors (SCRIF)** for grouped buses in network scans: SCRIF_i = SCMVA_i ÷ (P_i + Σ IF_ij·P_j), with interaction factors IF_ij = |Z_ij ÷ Z_jj| from the network impedance matrix (NERC Reliability Guideline, 2017; NREL/TP-5D00-94961, 2025). It sits between each plant's SCR and the group's WSCR.
- **Composite SCR (CSCR)** for each group: short-circuit MVA with the group's points of interconnection tied together, ÷ total MW.
- **Effective SCR (ESCR)**: short-circuit MVA minus capacitive shunt compensation at the bus, ÷ plant MW; shown when the network has capacitor banks.
- **`scr-screen interactions`**: interaction-factor table for a list of buses, and suggested groups (every pair interacts at least `--threshold`, default 0.5), written as a groups file for `scan --groups`.
- **`scan --n1`**: each line circuit and transformer unit is removed in turn; each bus's lowest SCR and the outage that causes it are reported (console, CSV/JSON, report section, results table, summary card). Outages that would leave buses with no source are skipped and listed.
- **Heat-map shading** on the network map, so weak areas stand out like a contour plot (toggle in the report; `--no-heatmap` to omit), and an **N-1 view** of the map.
- All new values update live with the plant-size slider and thresholds.
- Results CSV gains columns `scrif`, `escr`, `n1_ratio`, `n1_outage`, `cscr` (appended at the end; existing columns unchanged).

### Changed
- The bundled IEEE 39-bus example now carries one-line drawing positions that follow the commonly published diagram of this system; the map says the positions are a drawing, not geographic. Short-circuit results are unchanged.
- README: thresholds used in practice (NREL, SPP, ERCOT) with sources; updated roadmap; new references.
- Error messages and the design specification no longer refer to "v0.1".

### Notes
- SCRIF, CSCR and N-1 use the classical method's network impedance matrix; with `--method iec60909`, `--n1` is refused and SCRIF/CSCR are omitted with a note.
- Group flags and the Flagged count still use WSCR, the most conservative group metric.

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
