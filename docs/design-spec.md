# SCR-Screen — Design Specification (v0.1)

| Item | Value |
|---|---|
| Author | Shaibu Ibrahim, P.E. |
| Status | v0.1 release candidate |
| Last updated | 2026-10-03 |
| License | MIT |

---

## 1. Purpose

SCR-Screen is an open-source Python tool that screens **system strength** at the point of interconnection (POI) of inverter-based resources (IBRs) such as solar, wind, and battery energy storage. It calculates short-circuit-ratio-based metrics early in siting and interconnection, so engineers can flag potentially weak-grid locations, and compare candidate sites, **before** detailed studies are commissioned.

### 1.1 In scope (v0.1)

- Single-plant **SCR** and multi-plant **WSCR** (MW and MVA bases).
- Short-circuit MVA from a network model by two methods: **classical flat-start** and **IEC 60909**.
- **Bus scan:** SCR at every bus for a hypothetical plant size.
- **Largest plant before a weak flag** at each location.
- **Cost screening:** synchronous condenser mitigation, gen-tie line, and POI substation cost per candidate bus, from user-supplied costs.
- **Own networks:** pandapower JSON, Excel, and MATPOWER files; a readiness check; a converter.
- Weak-grid flags against **user-configurable** thresholds.
- Self-contained **HTML report** with network map, method comparison, and interactive what-if inputs; CSV and JSON results.
- Command line and Python API.

### 1.2 Out of scope (v0.1)

- **Not a substitute for interconnection studies.** SCR-based metrics are screening indicators only. Weak-grid behavior is system- and equipment-specific and may require positive-sequence and EMT studies.
- CSCR (composite SCR) and SCRIF (SCR with interaction factors), planned for v0.2.
- Automatic contingency (N-1) scanning, retirement scenarios, queue build-out (planned for v0.2).
- PSS/E `.raw` import (planned for v0.2).
- **Network upgrade costs** (thermal, voltage, stability). These need power flow and interconnection-queue studies.
- Any shipped cost data, and any use of non-public network data.

---

## 2. Definitions and Formulas

Formulas follow the NERC Reliability Guideline *Integrating Inverter-Based Resources into Low Short Circuit Strength Systems* (Dec 2017) and the NERC white paper *Short-Circuit Modeling and System Strength* (Feb 2018).

### 2.1 Short-Circuit Ratio (SCR)

$$SCR_{POI} = \frac{SCMVA_{POI}}{P_{rated}}$$

- **SCMVA_POI**: three-phase short-circuit MVA at the POI **without** IBR contribution.
- **P_rated**: plant rating, MW by default, MVA optional (Decisions D1/D3).
- Most appropriate for a single IBR; optimistic when other IBRs are electrically close (NERC).

### 2.2 Weighted Short-Circuit Ratio (WSCR)

$$WSCR = \frac{\sum_{i=1}^{N} SCMVA_i \cdot P_{RMW,i}}{\left(\sum_{i=1}^{N} P_{RMW,i}\right)^2}$$

- Developed by ERCOT (Zhang et al., IEEE PES GM 2014); presented in both NERC documents.
- Assumes the N plants are **fully interacting**. The MVA variant replaces MW ratings with MVA.

### 2.3 Composite Short-Circuit Ratio (CSCR) — deferred to v0.2 (Decision D5)

$$CSCR = \frac{CSCMVA}{\sum P_{rated}}$$

CSCMVA is the short-circuit MVA at a common (virtual) bus tying the IBRs together, without IBR contribution. To be validated against the GE CSCR estimation guideline before implementation.

### 2.4 Largest plant before a weak flag

$$P_{max} = \frac{SCMVA}{SCR_{weak}}$$

The largest plant rating (same basis) that keeps SCR at or above the weak threshold. Single-plant only; nearby plants share this strength.

### 2.5 Synchronous condenser sizing (cost screening)

A condenser at the POI adds short-circuit MVA in parallel with the grid:

$$\Delta SCMVA \approx \frac{S_{cond}}{X''_d + X_t} \quad\Rightarrow\quad S_{cond} = \max\left(0,\; P \cdot SCR_{target} - SCMVA\right)\cdot\left(X''_d + X_t\right)$$

- X″d and Xt are per unit on the condenser base (defaults 0.20 and 0.10, typical; user-adjustable).
- Assumes the condenser is at the POI and that grid and condenser impedances are mostly reactive.
- Cost = S_cond × user $/MVA; gen-tie = distance × user $/mile; POI = user value per bus.

---

## 3. Engineering Conventions

| # | Convention | v0.1 choice |
|---|---|---|
| C1 | IBR fault contribution | Always excluded from SCMVA (sgen and storage set out of service, or not modeled as sources). |
| C2 | Fault type | Balanced three-phase fault. |
| C3 | Short-circuit method | User-selectable. **Classical flat-start** (default): S = V² / \|Z_th\| from the network impedance matrix, 1.0 pu pre-fault, sub-transient reactances, no correction factors; loads, shunts, and line charging ignored; nominal transformer taps. **IEC 60909** via pandapower: voltage factor c = 1.1 (max case) plus generator and transformer impedance correction factors. Reports state the method used. |
| C4 | Units | pandapower's `skss_mw` column is apparent power; relabeled MVA in all outputs. |
| C5 | Thresholds | User-configurable (Section 4). |
| C6 | Isolated buses | Buses with no path to any source are skipped in scans and listed in the notes; requesting one directly is an error. |
| C7 | Unsupported elements | Elements the classical method does not model (three-winding transformers, impedance elements, wards, DC lines, closed bus-bus switches) stop the classical calculation with a clear error rather than being ignored. |
| C8 | Costs | All money values are user inputs. No cost data ships with the tool. |
| C9 | Number input | Values containing commas are rejected (ambiguous thousands vs decimal separators). |

---

## 4. Flag Thresholds (Configurable)

There is no industry-standard weak-grid threshold (NERC). Defaults, overridable on the command line and in the report:

| Band | Default rule | Basis |
|---|---|---|
| Very weak: detailed study (e.g., EMT) likely needed | SCR < 2 | HVDC planning practice; IEEE Std 1204-1997 (verify bands in the standard) |
| Weak: further study recommended | 2 ≤ SCR < 3 | Same; NERC (2018) notes SCR below about 3 typically indicates low-SCR areas |
| No low-strength flag | SCR ≥ 3 | Same |

These bands originate in HVDC planning and do not replace the inverter manufacturer's minimum SCR rating. ERCOT's WSCR threshold of 1.5 is region-specific and is not used as a default.

---

## 5. Inputs

### 5.1 Direct mode (plant CSV)

| Field | Required | Example |
|---|---|---|
| `plant_id` | Yes | `PV-A` |
| `scmva` | Yes | `500` |
| `rating_mw` | Yes | `100` |
| `rating_mva` | No | `105` |
| `group` | No (plants sharing a group form a WSCR group) | `G1` |
| `poi_name` | No | `Bus 101` |

### 5.2 Network mode (network files)

| Format | Extension |
|---|---|
| pandapower JSON | `.json` |
| pandapower Excel | `.xlsx` |
| MATPOWER | `.m`, `.mat` |

Required short-circuit data:
- **External grids:** `s_sc_max_mva`, `rx_max` (IEC min case also `s_sc_min_mva`, `rx_min`).
- **Synchronous generators:** `xdss_pu`, `sn_mva` (both methods); `vn_kv`, `rdss_ohm`, `cos_phi` (IEC 60909).

`scr-screen check` reports anything missing; `scr-screen convert` adds empty short-circuit columns for the user to fill in.

### 5.3 Cost screening

- **Command options:** `--condenser-cost-per-mva`, `--gen-tie-cost-per-mile`, `--target-scr` (default: weak threshold), `--condenser-xdss` (default 0.20), `--condenser-xt` (default 0.10).
- **Site file** (`--site-costs`): columns `bus`, `distance_mi`, `poi_cost_usd`. Only listed buses are costed (Decision D10).

### 5.4 Report what-if inputs (scan reports)

Plant size; weak and very-weak thresholds; and, with cost screening, target SCR, condenser X″d and Xt, condenser $/MVA, gen-tie $/mile, and per-bus distance and POI cost. All recalculate in the browser; invalid entries are flagged and ignored.

---

## 6. Outputs

1. **HTML report** (single self-contained file, works offline):
   - summary cards
   - what-if inputs (scan reports)
   - network map (bus coordinates or automatic layout; omitted above 400 buses)
   - SCR chart
   - method comparison (classical vs IEC 60909)
   - largest-plant chart
   - cost screening table
   - WSCR group comparison (direct mode)
   - results tables
   - method and assumptions, and the disclaimer
2. **Results CSV/JSON** (`--out`), including the largest plant before a weak flag.
3. **Cost CSV** (`--cost-out`).
4. **Console summary.**

---

## 7. Architecture

```
scr-screen/
├── src/scr_screen/
│   ├── metrics.py     # core math: scr(), wscr(), classify(); Plant record — no pandapower dependency
│   ├── settings.py    # flag thresholds (user-configurable)
│   ├── screening.py   # engine: SCR per plant, WSCR per group, largest plant, metadata
│   ├── network.py     # short-circuit MVA: IEC 60909 (via pandapower), dispatch, bus scan
│   ├── classical.py   # classical flat-start: Y-bus / Z-bus, 1.0 pu; connectivity to sources
│   ├── loaders.py     # network files: JSON, Excel, MATPOWER; save as JSON/Excel
│   ├── check.py       # network readiness check
│   ├── cost.py        # condenser sizing and cost screening; site cost file
│   ├── netmap.py      # network map SVG
│   ├── io.py          # plant CSV input; results CSV/JSON; input template
│   ├── report.py      # self-contained HTML report with what-if inputs
│   ├── cli.py         # command line: template | run | scan | check | convert | sites-template
│   └── __main__.py    # allows: python -m scr_screen
├── tests/             # pytest; hand-calculated cases, examples, notebook
├── examples/          # IEEE 39-bus network (assumed data), site cost example (illustrative), templates, notebook
├── docs/              # this spec and the verification record
└── .github/workflows/ # automated tests on every push (Python 3.10 and 3.13)
```

Design rules:

- `metrics.py` stays independent of pandapower, so the math can be tested and verified by hand in isolation.
- `screening.py` is shared by the Python API, the report, and the command line, so all produce identical numbers.
- Each short-circuit method is a separate module behind one switch (`network.scmva(method=...)`).
- Unsupported network elements stop the calculation with a clear error rather than being silently ignored.
- The report's browser code reproduces the Python formulas exactly; its results are checked against the Python results (T11).

---

## 8. Validation Test Cases

Every case must be **independently verified by the author (Shai)** before its test is accepted.

| ID | Case | Inputs | Expected | Verified by Shai |
|---|---|---|---|---|
| T1 | Single-plant SCR | SCMVA = 500 MVA, P = 100 MW | 5.000 | ☐ |
| T2 | WSCR, two plants | 1000 MVA / 200 MW and 600 MVA / 100 MW | 260,000 / 90,000 = **2.889** | ☐ |
| T2b | Contrast for T2 | Same plants, individual SCRs | 5.000 and 6.000 | ☐ |
| T3 | IEC 60909, 2-bus radial | 138 kV source 1000 MVA (R/X 0.1) + 50 km line (R 0.05, X 0.4 Ω/km); 100 MW at POI | 509.68 MVA, SCR 5.097 | ☑ |
| T3b | Classical, same network | \|Zk\| = 39.20 Ω | 485.86 MVA, SCR 4.859 | ☑ |
| T4 | Transformer, classical | Source 1000 MVA + 100 MVA 138/34.5 kV transformer, vk 10%, vkr 0.5% | 500.15 MVA | ☐ |
| T5 | Synchronous generator, classical | T3b network + 100 MVA generator, X″d = 0.2 pu, at the POI | 984.30 MVA | ☑ |
| T6 | Input errors | Zero/negative rating, missing SCMVA, missing generator or source data, 0 MW plant | Clear error message, no crash | ☐ |
| M1 | Meshed network cross-check | 4-bus looped 138 kV network vs pandapower's independent calculation | Match at every bus | ☐ |
| T7 | File formats | IEEE 39-bus saved as Excel and reloaded | Identical SCMVA at every bus | ☐ |
| T8 | Isolated buses | Network with a section cut off from all sources | Section skipped and listed; other results unchanged | ☐ |
| T9 | Condenser sizing | IEEE bus 12, 1500 MW, target 3, X″d + Xt = 0.30 | (4500 − 2832.43) × 0.30 = **500.27 MVA** | ☑ |
| T10 | Largest plant | T3b POI, weak threshold 3 | 485.86 / 3 = **161.95 MW** | ☑ |
| T11 | Report recalculation | IEEE 39-bus scan report, inputs changed in the browser | Matches Python results (e.g., 800 MW: lowest SCR 3.54, 0 flagged) | ☐ |

T11 is checked by running the report's code in a simulated browser during development; it is not part of the automated test suite.

---

## 9. Required Disclaimer (README and report)

> SCR-Screen provides screening-level indicators of system strength. Results do not replace interconnection studies, detailed positive-sequence or EMT analysis, or the requirements of the applicable transmission provider. Thresholds are user-configurable and have no universal validity. SCR-based metrics assume grid-following inverters and do not replace the inverter manufacturer's minimum SCR rating. Cost screening is screening-level only, excludes network upgrades, and uses only user-supplied costs.

---

## 10. Decisions

| ID | Decision | Choice |
|---|---|---|
| D1 + D3 | Rating basis | MW default; MVA optional when provided |
| D2 | Short-circuit method | Both: classical flat-start (default) and IEC 60909, user-selectable |
| D4 | Flag bands | Below 2 very weak; 2 to below 3 weak; 3–5 band removed |
| D5 | CSCR | Deferred to v0.2 |
| D6 | Report format | HTML only; print to PDF from the browser |
| D7 | Cost screening | Included in v0.1; user-supplied costs only; no default prices; network upgrades excluded |
| D8 | Condenser defaults | X″d = 0.20, Xt = 0.10 pu (typical), labeled and adjustable |
| D9 | Target SCR | Defaults to the weak threshold and follows it in the report until set explicitly |
| D10 | Site file scope | When given, only listed buses are costed |
| D11 | Map readability | Map omitted above 400 buses; labels and pulsing rings limited to the 8 weakest flagged buses |
| D12 | Number format | Numbers with commas rejected rather than guessed |

---

## 11. References

1. NERC, *Integrating Inverter-Based Resources into Low Short Circuit Strength Systems*, Reliability Guideline, Dec 2017.
2. NERC, *Short-Circuit Modeling and System Strength*, White Paper, Feb 2018.
3. Y. Zhang, S.-H. F. Huang, J. Schmall, J. Conto, J. Billo, E. Rehman, "Evaluating system strength for large-scale wind plant integration," IEEE PES General Meeting, 2014.
4. R. Fernandes, S. Achilles, J. MacDowell (GE Energy Consulting), *Report to NERC ERSTF for Composite Short Circuit Ratio (CSCR) Estimation Guideline*, Jan 2015.
5. CIGRE WG B4.62, *Connection of Wind Farms to Weak AC Networks*, Technical Brochure 671, Dec 2016.
6. ERCOT, *Panhandle System Strength Assessment PSCAD Study*, Feb 2016.
7. IEC 60909-0, *Short-circuit currents in three-phase a.c. systems — Calculation of currents*.
8. pandapower documentation: short-circuit module (`pandapower.shortcircuit`).
9. IEEE Std 1204-1997, *IEEE Guide for Planning DC Links Terminating at AC Locations Having Low Short-Circuit Capacities*.
10. IEEE Std 551-2006 (Violet Book), *IEEE Recommended Practice for Calculating AC Short-Circuit Currents in Industrial and Commercial Power Systems*.
