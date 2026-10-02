# SCR-Screen

[![tests](https://github.com/ishaibu/scr-screen/actions/workflows/tests.yml/badge.svg)](https://github.com/ishaibu/scr-screen/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

**Open-source short-circuit ratio (SCR) screening for solar, wind, and battery storage interconnection.**

SCR-Screen helps interconnection, planning, and siting engineers find weak-grid locations **early**, before detailed studies are commissioned. It calculates short-circuit strength from a network model, screens single plants (SCR) and groups of nearby plants (WSCR), and produces a clear, self-contained HTML report.

> **Screening only.** SCR-Screen provides screening-level indicators of system strength. Results do not replace interconnection studies, detailed positive-sequence or EMT analysis, or the requirements of the applicable transmission provider.

---

## Why use it

The SCR formula is simple. Getting a trustworthy answer is not:

- **Short-circuit MVA must come from the network, calculated consistently.** SCR-Screen computes it from a model, excludes inverter-based resource (IBR) contributions as NERC requires, and states the method used.
- **Nearby plants share grid strength.** Two plants that each pass alone can be weak together. SCR-Screen screens groups with WSCR and shows the difference side by side.
- **Siting needs every location, not one.** The bus scan ranks every bus in a model for a plant of a given size.
- **Method choice changes answers.** SCR-Screen supports both the classical flat-start method (common U.S. planning practice) and IEC 60909, and records which one produced each result.
- **Transparent and reproducible.** Open formulas, documented assumptions, automated tests, and a public [verification record](docs/verification.md).

## Features (v0.1)

| Feature | Details |
|---|---|
| SCR | Single plant at its point of interconnection (POI) |
| WSCR | Groups of plants assumed fully interacting (ERCOT/NERC formulation) |
| Rating basis | MW (default) or MVA |
| Short-circuit methods | Classical flat-start (1.0 pu) and IEC 60909 (via pandapower) |
| Bus scan | SCR at every bus of a network for a hypothetical plant size |
| Flags | Very weak / weak / no flag, with user-configurable thresholds |
| Network map | Grid drawn from bus coordinates (or an automatic layout), colored and animated by SCR flag |
| Plant-size slider | In scan reports, drag to any plant size; every SCR, flag, chart and the map update instantly in the browser |
| Max plant size | Largest plant each location can host before a weak flag (SCMVA ÷ weak threshold) |
| Method comparison | Classical vs IEC 60909 for every bus, highlighting where the flag changes |
| Outputs | Self-contained HTML report (works offline), CSV, JSON |
| Interfaces | Command line (`scr-screen`) and Python API |

## Installation

Requires Python 3.10 or newer.

```bash
git clone https://github.com/ishaibu/scr-screen.git
cd scr-screen
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -e .
```

A PyPI release (`pip install scr-screen`) is planned for v0.1.0.

## Quick start (command line)

**Direct mode:** you already have short-circuit MVA values (from any study tool).

```bash
scr-screen template plants.csv          # creates an input file with example rows
scr-screen run plants.csv --report report.html --out results.csv
```

**Network mode:** calculate short-circuit MVA from a [pandapower](https://www.pandapower.org/) network saved as JSON, and scan every bus.

```bash
scr-screen scan examples/ieee39_assumed.json --plant-mw 1500 --report scan.html --open
scr-screen scan examples/ieee39_assumed.json --plant-mw 1500 --method iec60909
```

`--open` opens the report in your browser as soon as it is ready. In a scan report, use the **plant-size slider** to try other sizes without re-running. The map, charts, and table recalculate instantly in the browser.

Run `scr-screen --help` or `scr-screen run --help` for all options (`--basis MVA`, `--weak`, `--very-weak`, `--title`, `--open`, `--no-compare`).

## Input format (direct mode)

One row per plant. Column order and capitalization do not matter; files saved from Excel as **CSV UTF-8** work.

| Column | Required | Description |
|---|---|---|
| `plant_id` | Yes | Unique label |
| `scmva` | Yes | Three-phase short-circuit MVA at the POI, **without** IBR contribution |
| `rating_mw` | Yes | Plant rating in MW |
| `rating_mva` | No | Plant rating in MVA (needed only for `--basis MVA`) |
| `group` | No | Plants sharing a group are also screened together with WSCR |
| `poi_name` | No | Display name of the POI |

Numbers must use a dot for decimals and no thousands separators (e.g. `1000`, `485.86`). Values with commas are rejected rather than guessed.

## Python API

```python
from scr_screen.metrics import scr, wscr
from scr_screen.io import read_plants_csv
from scr_screen.screening import screen
from scr_screen.report import write_html_report

scr(500, 100)                          # 5.0
wscr([1000, 600], [200, 100])          # 2.889

plants, poi = read_plants_csv("plants.csv")
result = screen(plants, poi_names=poi)
write_html_report(result, "report.html")
```

Network mode:

```python
import pandapower as pp
from scr_screen.network import scan_buses

net = pp.from_json("network.json")
for row in scan_buses(net, plant_mw=300, method="classical"):
    print(row.bus, row.name, round(row.scr, 2), row.flag)
```

See [`examples/walkthrough.ipynb`](examples/walkthrough.ipynb) for a step-by-step tour.

## Methods

**SCR** = SCMVA ÷ plant rating
**WSCR** = Σ(SCMVAᵢ × Pᵢ) ÷ (ΣPᵢ)²

| Short-circuit method | Pre-fault voltage | Correction factors | Typical use |
|---|---|---|---|
| Classical flat-start (default) | 1.0 pu | None | Common U.S. planning practice |
| IEC 60909 (max case) | c = 1.1 | Generator and transformer impedance correction | IEC practice |

In both methods, inverter-based resources do not contribute to SCMVA.

**Default flag bands** (user-configurable): below 2 **very weak**; 2 to below 3 **weak**; 3 or above **no flag**. These follow HVDC planning practice (IEEE Std 1204-1997). There is no universal weak-grid threshold.

Full details: [design specification](docs/design-spec.md).

## Limitations

- SCR-based metrics assume **grid-following** inverters and do not replace the inverter manufacturer's minimum SCR.
- WSCR assumes the plants in a group are fully interacting.
- The classical method (v0.1) ignores loads, shunts, and line charging, uses nominal transformer taps, and does not yet model three-winding transformers or closed bus-bus switches. Unsupported elements stop the calculation with a clear error rather than being ignored.
- Real transmission models are often restricted (e.g. CEII in the U.S.). SCR-Screen ships only public test data; users run it on their own models.

## Verification

Every formula is covered by automated tests with hand-calculated expected values, run on each change. Independent engineering checks are recorded in [`docs/verification.md`](docs/verification.md).

## Roadmap

- **v0.2:** N-1 contingency worst case, generator retirement scenarios, interconnection-queue build-out, composite SCR (CSCR)
- **v0.3:** mitigation sizing (e.g. synchronous condenser MVA needed), SCR with interaction factors (SCRIF)

## Feedback and contributions

Found a bug, have a question, or use SCR-Screen in your work? Please [open an issue](https://github.com/ishaibu/scr-screen/issues). Feedback from utility, ISO/RTO, developer, and consulting engineers is especially welcome.

## References

1. NERC, *Integrating Inverter-Based Resources into Low Short Circuit Strength Systems*, Reliability Guideline, December 2017.
2. NERC, *Short-Circuit Modeling and System Strength*, White Paper, February 2018.
3. Y. Zhang et al., "Evaluating system strength for large-scale wind plant integration," IEEE PES General Meeting, 2014.
4. IEEE Std 1204-1997, *IEEE Guide for Planning DC Links Terminating at AC Locations Having Low Short-Circuit Capacities*.
5. IEC 60909-0, *Short-circuit currents in three-phase a.c. systems*.

## License and author

MIT License. Created and maintained by **Shaibu Ibrahim, P.E.**
