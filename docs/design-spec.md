# SCR-Screen — Design Specification

| Item | Value |
|---|---|
| Author | Shaibu Ibrahim, P.E. |
| Status | Current through v0.5.0 |
| Last updated | 2026-11-14 |
| License | MIT |

---

## 1. Purpose

SCR-Screen is an open-source Python tool that screens **system strength** at the point of interconnection (POI) of inverter-based resources (IBRs) such as solar, wind, and battery energy storage. It calculates short-circuit-ratio-based metrics early in siting and interconnection, so engineers can flag potentially weak-grid locations, and compare candidate sites, **before** detailed studies are commissioned.

### 1.1 In scope

- Single-plant **SCR** and multi-plant **WSCR** (MW and MVA bases).
- Short-circuit MVA from a network model by two methods: **classical flat-start** and **IEC 60909**.
- **Bus scan:** SCR at every bus for a hypothetical plant size.
- **Network-aware metrics (v0.3):** interaction factors, SCRIF, CSCR and ESCR; suggested groups; N-1 worst-case SCR.
- **EMT study triage (v0.4):** a system strength data sheet per POI (Thévenin impedance, intact, N-1 and minimum generation) and a priority for an EMT study, from the situations listed in NERC's 2024 EMT guideline.
- **Largest plant before a weak flag** at each location.
- **Cost screening:** synchronous condenser mitigation, gen-tie line, and POI substation cost per candidate bus, from user-supplied costs.
- **Own networks:** pandapower JSON, Excel, and MATPOWER files; a readiness check; a converter.
- Weak-grid flags against **user-configurable** thresholds.
- Self-contained **HTML report** with network map, method comparison, and interactive what-if inputs; CSV and JSON results.
- Command line and Python API.

### 1.2 Out of scope (as of v0.5)

- **Not a substitute for interconnection studies.** SCR-based metrics are screening indicators only. Weak-grid behavior is system- and equipment-specific and may require positive-sequence and EMT studies.
- EMT simulation. Interconnection studies must use equipment-specific EMT models (NERC, 2023); SCR-Screen's EMT triage (v0.4) lists the situations that call for them; it does not decide whether a study is required.
- Retirement scenarios and queue build-out; PSS/E `.raw` import (planned).
- Frequency-domain metrics (impedance scans, Q/V sensitivity).
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

### 2.3 Composite Short-Circuit Ratio (CSCR) — implemented in v0.3 (Decision D5)

$$CSCR = \frac{CSCMVA}{\sum P_{rated}}$$

CSCMVA is the short-circuit MVA at a common bus tying the IBRs together, without IBR contribution. NERC (2017) ties the plants' medium-voltage buses; plant collector systems are not in transmission models, so SCR-Screen ties the **points of interconnection** with zero impedance. With Z_GG the group's block of the bus impedance matrix:

$$Z_{eq} = \frac{1}{\mathbf{1}^T Z_{GG}^{-1}\mathbf{1}}, \qquad CSCMVA = \frac{S_{base}}{|Z_{eq}|}$$

Verified against an independent calculation that ties the buses with near-zero-impedance lines and recomputes short-circuit MVA. The GE estimation guideline (reference 4) was not reviewed for this implementation.

### 2.3a Interaction factors and SCRIF (v0.3)

$$IF_{ij} = \frac{\Delta V_i}{\Delta V_j} = \left|\frac{Z_{ij}}{Z_{jj}}\right|, \qquad SCRIF_i = \frac{SCMVA_i}{P_i + \sum_{j \ne i} IF_{ij} P_j}$$

IF_ij is the voltage change at bus i per unit voltage change at bus j for a current injection at j (NERC 2017; NREL/TP-5D00-94961). SCRIF lies between SCR (IF = 0) and, for close buses, WSCR. Suggested groups (`scr-screen interactions`) use complete linkage: every pair of members has max(IF_ij, IF_ji) ≥ threshold (default 0.5, a judgment value).

### 2.3b Effective SCR (ESCR) (v0.3)

$$ESCR_i = \frac{SCMVA_i - Q_{c,i}}{P_i}$$

Q_c,i is the in-service capacitive shunt compensation at bus i (pandapower `shunt` with q_mvar < 0, times step), in Mvar at 1.0 pu.

### 2.3c N-1 worst case (v0.3)

Each in-service line circuit (one circuit of a parallel entry) and transformer unit is removed in turn. Removing admittance y between buses a and b, with m = e_a − e_b, updates the impedance-matrix diagonal by Sherman–Morrison:

$$Z'_{kk} = Z_{kk} + \frac{y\,(Zm)_k^2}{1 - y\,m^T Z m}$$

A generator unit (admittance y to ground at bus k) is removed the same way with m = e_k (v0.3.1). Outages for which the denominator vanishes leave buses with no source; they are skipped and listed. Verified against rebuilding and re-inverting the network for every outage of the IEEE 39-bus case (agreement within 10⁻⁹).

### 2.3d Thévenin data and EMT triage (v0.4)

For a POI at bus i and each condition (intact; worst single outage, from the N-1 screen, which keeps the complex diagonal term; minimum generation, from a second Z-bus with the `--gen-out` generators out):

    Z_th = Z_ii (pu, 100 MVA base);  Z_ohm = Z_th × kV² / 100;  X/R = X / R (shown as ∞ when R = 0)
    SCMVA = 100 / |Z_th|;  I_sc = SCMVA / (√3 × kV) kA;  SCR = SCMVA / P;  ESCR = (SCMVA − Q_c) / P

all at 1.0 pu pre-fault voltage with inverter-based resources excluded (classical method only). The minimum-generation case is computed with the network otherwise intact.

**Proximity.** An existing IBR (in-service `sgen` or `storage`) or a device is *nearby* when its pair interaction with the POI, max(IF_ij, IF_ji) with IF_ij = |Z_ij / Z_jj|, is at least the threshold (default 0.5, the same judgment value as `interactions`). For a two-terminal device the larger of its terminals is used.

**Devices.** Series compensation: in-service lines with negative series reactance (`x_ohm_per_km < 0`). FACTS: `svc`, `ssc`, `tcsc`. HVdc: `vsc`, `dcline`. For the strength calculation, `ssc`, `vsc` and `dcline` are set out of service (converter-interfaced, so excluded like other IBRs; a dc line has no AC path). A `tcsc` carries its line, so removing it would change the network; an in-service TCSC stops the triage with a message instead.

**Priority** (SCR-Screen's ordering; NERC lists the situations without ranking them):
1. any strength metric (SCR and ESCR in every condition; group WSCR, CSCR and SCRIF, intact) below the very-weak threshold; series compensation, FACTS or HVdc nearby (found or answered yes); a system event that positive-sequence models cannot reproduce (answered yes; NERC says a new EMT study is needed); or the lowest SCR below the OEM minimum SCR;
2. any metric below the weak threshold; other IBRs nearby; or any other situation answered yes;
3. otherwise ("no screening trigger found", with NERC's note that high system strength alone should not rule out EMT studies).

Answers of "unknown" (or no answer) never change the priority; they are listed as not checked. The `--poi-info` questions cover the rest of NERC's Chapter 1 list: Stability Criteria (`rms_stability_concerns`), EMT Studies Following System Events (`unexplained_system_event`), and the "System Topology or Conditions with Stability Risks" items (`pre_existing_oscillation`, `series_compensation`, `facts_nearby`, `hvdc_nearby`, `high_ibr_penetration`, `ras`, `distance_relays_declining_fault_current`, `decreasing_strength_trend`, `rocof_inertia_trend`); "other IBRs" and low system strength are found in the model.

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

| # | Convention | Choice |
|---|---|---|
| C1 | IBR fault contribution | Always excluded from SCMVA (sgen and storage set out of service, or not modeled as sources). |
| C2 | Fault type | Balanced three-phase fault. |
| C3 | Short-circuit method | User-selectable. **Classical flat-start** (default): S = V² / \|Z_th\| from the network impedance matrix, 1.0 pu pre-fault, sub-transient reactances, no correction factors; loads, shunts, and line charging ignored; nominal transformer ratio (tap positions and off-nominal turns ratios are not modeled; the number of such transformers is reported). Transformer and generator impedances are converted from the equipment's rating and rated voltage to the 100 MVA base and the bus nominal voltage: z = z_rated × (100 ÷ S_rated) × (V_rated ÷ V_bus)², the transformer referred to its low-voltage side (v0.5; Decision D27). **IEC 60909** via pandapower: voltage factor c = 1.1 (max case) plus generator and transformer impedance correction factors. Reports state the method used. |
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
- **Groups file** (`scan --groups`): columns `bus`, `group`. Each listed bus gets a plant of `--plant-mw`; buses sharing a group are screened together with WSCR. A bus can belong to one group only.
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
   - WSCR group comparison (direct mode, and network scans with `--groups`; placed after the SCR chart)
   - EMT study triage (scan with `--emt-triage`)
   - results tables
   - method and assumptions, and the disclaimer
2. **Results CSV/JSON** (`--out`), including the largest plant before a weak flag.
3. **Cost CSV** (`--cost-out`).
4. **Console summary.**
5. **Dashboard** (`scan --dashboard`, v0.5): the scan report's content as a single self-contained file with a sidebar of views (Overview, Network map, Rankings, Charts, Groups, N-1 outages, EMT study triage, Cost screening, Method comparison, Method & assumptions), inputs that stay in place, the weakest locations, and the details of a selected bus (including Thévenin R, X, \|Z\| in ohms, X/R and fault current, intact and worst N-1). Search, flagged-only filter and sorting in the rankings; map colored by SCR, N-1 SCR or EMT priority; print (all views) and CSV download of the values shown.
6. **EMT triage report** (`triage --report`): printable HTML with a summary and one data sheet per POI; `triage --out` writes CSV (one row per POI and condition) or JSON.

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
│   ├── strength.py    # interaction factors, SCRIF, CSCR, ESCR, N-1 (Sherman–Morrison)
│   ├── triage.py      # EMT triage: Thévenin data, devices, nearby IBRs, POI information, priorities
│   ├── triage_report.py # EMT triage HTML data sheets, CSV and JSON
│   ├── dashboard.py   # dashboard layout: the scan report rearranged into views (no calculation of its own)
│   ├── cli.py         # command line: example | template | run | scan | check | convert | sites-template | interactions | triage
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
- The dashboard contains no calculation: it is built from the report's HTML and runs the report's script unchanged, so the two cannot disagree (T12).

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
| T12 | Dashboard equals report | IEEE 39-bus scan with groups, N-1, EMT triage and cost; inputs changed in the browser in both files | Every card, table row, group panel, cost row and map node identical at each setting | ☐ |
| T13 | Voltage-base conversion (V6) | 220 kV / 33 kV buses; source 1000 MVA, X″d 0.20, rated 230 kV; transformer 100 MVA, 230/34.5 kV, vk 12 %, vkr 0.4 % | 4,574.67 MVA at bus 1; 653.57 MVA at bus 2 | ☐ |

T11 and T12 are checked by running the report's code in a simulated browser during development; they are not part of the automated test suite (T12's structure, that nothing in the report is missing from the dashboard and the script is unchanged, is tested automatically).

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
| D5 | CSCR | Implemented in v0.3 at the POIs (plant medium-voltage buses are not in transmission models) |
| D6 | Report format | HTML only; print to PDF from the browser |
| D7 | Cost screening | Included in v0.1; user-supplied costs only; no default prices; network upgrades excluded |
| D8 | Condenser defaults | X″d = 0.20, Xt = 0.10 pu (typical), labeled and adjustable |
| D9 | Target SCR | Defaults to the weak threshold and follows it in the report until set explicitly |
| D10 | Site file scope | When given, only listed buses are costed |
| D11 | Map readability | Map omitted above 400 buses; labels and pulsing rings limited to the 8 weakest flagged buses |
| D12 | Number format | Numbers with commas rejected rather than guessed |
| D13 | Network-aware metrics | SCRIF, CSCR and N-1 from the classical Z-bus only; refused or omitted (with a note) when IEC 60909 is the primary method |
| D14 | Group flag | Group flag and Flagged count stay on WSCR (most conservative); SCRIF and CSCR shown alongside |
| D15 | Heat map | Blurred flag-colored circle per bus under the map; labeled as a visual aid, not a computed field |
| D16 | IEEE 39-bus drawing | One-line positions following the commonly published diagram, stored in the example network's bus coordinates with a "drawing" marker |
| D17 | MVA basis in scans (v0.3.1) | `--basis MVA` with `--plant-mva`; every ratio, the slider and cost screening use MVA. CSCR then divides by nominal MVA, as NERC defines it |
| D18 | Devices with no active power (v0.3.1) | Entered as 0 MW plus an MVA rating; counted on the MVA basis, left out with a note on the MW basis (NERC Table 2.1: WSCR-MVA and SCRIF consider non-active inverter capacity) |
| D19 | Group member sizes (v0.3.1) | Optional `mw`, `mva` columns in the groups file (both or neither). SCRIF for a fixed-size member is shown in the group panel only, since the results table row describes the scan's plant |
| D20 | N-1 outages (v0.3.1) | Generator units added to lines and transformer units (Sherman–Morrison on one diagonal term); external grids are network equivalents and are not removed |
| D21 | Plant MVA rating (v0.3.1) | Nameplate (inverter) MVA, as NERC's MVA metrics use; or inverters × inverter MVA; or an estimate MW ÷ power factor at the POI, labeled as an estimate (less conservative than nameplate). Only one source per plant; MW remains the default basis |
| D22 | EMT triage source (v0.4) | NERC Reliability Guideline, *Recommended Practices for Performing EMT System Studies for IBRs* (Dec 2024), Chapter 1: if any one listed situation applies, EMT studies should be considered. The tool checks what a model can show and asks the user about the rest |
| D23 | Priority levels (v0.4) | Three levels, defined in §2.3d. They are the tool's ordering of work, stated as such in every output; level 3 always repeats NERC's note that high system strength alone does not rule out EMT studies |
| D24 | Nearby test (v0.4) | Pair interaction factor ≥ 0.5 (user-configurable), the same judgment value as `interactions`; not an industry standard |
| D25 | Conditions (v0.4) | Intact, worst N-1 (lines, transformers, generators) and, when generators are named, minimum generation; group metrics intact only |
| D26 | Unchanged outputs (v0.4) | New behavior only with `triage` or `scan --emt-triage`; every other output is identical to v0.3.1 (checked file by file) |
| D27 | Voltage base (v0.5) | Transformer and generator impedances are converted to the bus nominal voltage, the transformer on its low-voltage side (the convention pandapower uses). Before v0.5 the rated voltage was taken as equal to the bus voltage, which overstated or understated SCMVA when they differed |
| D28 | Nominal ratio (v0.5) | Taps and off-nominal turns ratios stay unmodeled (flat-start convention); the report and `check` state how many transformers this affects and that the effect can reach several percent at adjacent buses |
| D29 | Negative reactance (v0.5) | A line with negative series reactance is still listed as possible series compensation, but answering `series_compensation = no` in the POI information file removes that trigger (reduced models contain negative-reactance equivalent branches) |
| D30 | Dashboard (v0.5) | A separate output (`scan --dashboard`); `--report` is unchanged. Layout only: built from the report and running its script. With the classical method it turns on `--n1` and `--emt-triage` so every view is present |
| D31 | Report data precision (v0.5) | Values embedded in the report for live recalculation carry full double precision (17 significant digits), so the browser and Python round identically |

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
11. P. Sharma et al., *Existing Methods for Grid Strength Assessment and Role of Hydropower in Future Grids*, NREL/TP-5D00-94961, Nov 2025.
12. NERC, *Electromagnetic Transient Modeling for BPS-Connected Inverter-Based Resources*, Reliability Guideline, Mar 2023.
13. NERC, *Reliability Guideline: Recommended Practices for Performing EMT System Studies for Inverter-Based Resources*, Dec 2024.
