# SCR-Screen — Design Specification (v0.1 draft)

| Item | Value |
|---|---|
| Author | Shaibu Ibrahim, P.E. |
| Status | DRAFT — open decisions in Section 10 must be settled before coding |
| Target release | v0.1 |
| License | MIT |

---

## 1. Purpose

SCR-Screen is an open-source Python tool that screens **system strength** at the point of interconnection (POI) of inverter-based resources (IBRs) such as solar, wind, and battery energy storage. It calculates short-circuit-ratio-based metrics early in project siting and interconnection, so engineers can flag potentially weak-grid locations **before** detailed studies are commissioned.

### 1.1 In scope (v0.1)

- Single-plant **SCR** at a POI.
- Multi-plant **WSCR** (weighted SCR), in MW and MVA variants.
- Two input modes:
  - **Direct mode:** the user supplies short-circuit MVA values.
  - **Network mode:** SCR-Screen computes short-circuit MVA from a pandapower network model.
- Weak-grid flags against **user-configurable** thresholds.
- Output as a table (CSV/JSON) plus a one-page HTML screening report.

### 1.2 Out of scope (v0.1)

- **Not a substitute for interconnection studies.** SCR-based metrics are screening indicators only. Weak-grid behavior is system- and equipment-specific and may require positive-sequence and EMT studies.
- CSCR (composite SCR) and SCRIF (SCR with interaction factors), planned for v0.2.
- Automatic contingency (N-1) scanning (planned for v0.2). In v0.1, users can study a contingency manually by editing the network.
- Reading proprietary study-software formats.
- Any use of non-public data.

---

## 2. Definitions and Formulas

All formulas follow the NERC Reliability Guideline *Integrating Inverter-Based Resources into Low Short Circuit Strength Systems* (Dec 2017) and the NERC white paper *Short-Circuit Modeling and System Strength* (Feb 2018).

### 2.1 Short-Circuit Ratio (SCR)

$$SCR_{POI} = \frac{SCMVA_{POI}}{P_{rated}}$$

- **SCMVA_POI**: three-phase short-circuit MVA at the POI **without** the contribution of the IBR being studied (per NERC).
- **P_rated**: nominal rating of the IBR. MW or MVA is a user choice; see Decision D3.
- **Applicability:** most appropriate for a single IBR. NERC notes that SCR can be overly optimistic when other IBRs are electrically close.

### 2.2 Weighted Short-Circuit Ratio (WSCR)

Developed by ERCOT (Zhang et al., IEEE PES GM 2014) and presented in both NERC documents:

$$WSCR = \frac{\sum_{i=1}^{N} SCMVA_i \cdot P_{RMW,i}}{\left(\sum_{i=1}^{N} P_{RMW,i}\right)^2}$$

- **SCMVA_i**: short-circuit MVA at bus *i* without contribution from non-synchronous generation.
- **P_RMW,i**: MW rating (or output) of IBR *i*.
- **N**: number of plants assumed to be **fully interacting**.
- **WSCR-MVA:** identical, with MVA ratings replacing MW. NERC notes the two variants may need different thresholds.

### 2.3 Composite Short-Circuit Ratio (CSCR) — deferred to v0.2 (Decision D5)

$$CSCR = \frac{CSCMVA}{\sum P_{rated}}$$

- **CSCMVA**: short-circuit MVA at a **common (virtual) bus** that ties together all IBRs of interest, without IBR current contribution.
- **Implementation note:** in network mode, the tool creates a temporary common bus connected to each plant's POI through negligible impedance, then runs the short-circuit calculation there. **This method must be validated against the GE CSCR estimation guideline before release** (see Decision D5).

### 2.4 Shared assumption for WSCR and CSCR

Both metrics assume strong electrical coupling between plants, as if all were connected to one virtual POI (per NERC). The report must state this assumption.

---

## 3. Engineering Conventions

| # | Convention | v0.1 choice |
|---|---|---|
| C1 | IBR fault contribution | Excluded from SCMVA: IBRs are left out of, or set out of service in, the short-circuit calculation. |
| C2 | Fault type | Balanced three-phase fault. |
| C3 | Short-circuit method (network mode) | User-selectable. **Option A: IEC 60909** via pandapower `calc_sc`, which applies voltage factor c = 1.1 (max case) plus generator and transformer impedance correction factors. **Option B: classical flat-start**, S = V² / \|Z_th\| from the network impedance matrix, with 1.0 pu pre-fault voltage, sub-transient reactances, and no IEC correction factors (aligned with common U.S. planning practice). The report states which method was used. |
| C4 | Units | pandapower reports short-circuit power in a column named `skss_mw`, but the quantity is apparent power (MVA). The tool relabels it as MVA in all outputs. |
| C5 | Thresholds | User-configurable. Defaults are informational only (Section 4). |

---

## 4. Flag Thresholds (Configurable)

**There is no industry-standard weak-grid threshold.** NERC states that no specific short-circuit threshold defines a "weak grid," and that what is weak for one manufacturer's equipment may not be for another's.

Proposed defaults, which the user can override:

| Band | Default rule | Basis |
|---|---|---|
| Very weak: detailed study (e.g., EMT) likely needed | SCR < 2 | HVDC planning practice; IEEE Std 1204-1997 (verify bands in the standard) |
| Weak: further study recommended | 2 ≤ SCR < 3 | Same; NERC (2018) notes SCR below about 3 typically indicates low-SCR areas |
| No low-strength flag | SCR ≥ 3 | Same |

The report must state that flags are screening indicators, not pass/fail criteria. ERCOT's WSCR threshold of 1.5 was specific to its Panhandle region and topology, so it must **not** be applied as a general default. The tool may reference it only as an example.

---

## 5. Inputs

### 5.1 Direct mode

A CSV or Python list with one row per plant:

| Field | Type | Example |
|---|---|---|
| `plant_id` | text | `PV-A` |
| `poi_name` | text | `Bus 101` |
| `scmva` | float (MVA) | `500` |
| `rating_mw` | float | `100` |
| `rating_mva` | float (optional) | `105` |
| `group` | text (optional; plants in the same group feed WSCR/CSCR) | `G1` |

### 5.2 Network mode

- A pandapower network, as a JSON file or a built-in test case (e.g., IEEE 39-bus from `pandapower.networks`).
- A plant list: POI bus index, rating, and group.
- Short-circuit data (source impedances, generator sub-transient reactances) must exist in the network. Public test cases may lack it; the tool must error clearly rather than guess. Any assumed values used in examples must be documented.

---

## 6. Outputs

1. **Results table (CSV/JSON):** per plant, the SCMVA, rating, SCR and flag; per group, the WSCR-MW, WSCR-MVA and CSCR.
2. **HTML report (one page):**
   - inputs summary and method used (direct or network, and the c-factor)
   - results table with flags
   - assumptions and limitations
   - tool version and run timestamp
3. **Console summary** when run from the command line.

---

## 7. Architecture

```
scr-screen/
├── src/scr_screen/
│   ├── metrics.py     # core math: scr(), wscr(), classify(); Plant record — no pandapower dependency
│   ├── settings.py    # flag thresholds (user-configurable)
│   ├── screening.py   # engine: SCR per plant, WSCR per group, with metadata
│   ├── network.py     # short-circuit MVA from a network: IEC 60909 (via pandapower) and bus scan
│   ├── classical.py   # classical flat-start method: Y-bus / Z-bus, 1.0 pu, no c-factor
│   ├── io.py          # CSV input; CSV/JSON results; input template
│   ├── report.py      # self-contained HTML report
│   ├── cli.py         # command-line tool: scr-screen template | run | scan
│   └── __main__.py    # allows: python -m scr_screen
├── tests/             # pytest; hand-calculated cases, examples, and the walkthrough notebook
├── examples/          # IEEE 39-bus example and network (assumed data), input template, walkthrough notebook
├── docs/              # this spec and the verification record
└── .github/workflows/ # automated tests on every push (Python 3.10 and 3.13)
```

Design rules:

- `metrics.py` stays independent of pandapower, so the math can be tested and verified by hand in isolation.
- `screening.py` is shared by the Python API, the HTML report, and the command line, so all three always produce identical numbers.
- Each short-circuit method is a separate module behind one switch (`network.scmva(method=...)`), so methods can be added or changed without touching the metrics.
- Unsupported network elements stop the calculation with a clear error rather than being silently ignored.

---

## 8. Validation Test Cases

Every case must be **independently verified by the author (Shai)** before its test is accepted.

| ID | Case | Inputs | Expected | Verified by Shai |
|---|---|---|---|---|
| T1 | Single-plant SCR | SCMVA = 500 MVA, P = 100 MW | SCR = 5.000 | ☐ |
| T2 | WSCR, two plants | Plant 1: 1000 MVA, 200 MW. Plant 2: 600 MVA, 100 MW | (1000·200 + 600·100) / 300² = **2.889** | ☐ |
| T2b | Contrast for T2 | Same plants, individual SCRs | 5.000 and 6.000. Shows that single-plant SCR is optimistic when plants interact. | ☐ |
| T3 | Network mode, 2-bus radial | 138 kV source 1000 MVA (R/X 0.1); 50 km line, R = 0.05, X = 0.4 Ω/km; plant 100 MW at bus 2 | pandapower gives 509.68 MVA at bus 2 (IEC 60909 max case, c = 1.1), so SCR = 5.097. **Verify by hand: S″k = c·Un²/\|Zk\|.** | ☐ |
| T3b | Same network as T3, classical flat-start (Option B) | Source impedance 138²/1000 = 19.044 Ω (R/X 0.1) plus the line gives \|Zk\| = 39.20 Ω, so S = 138²/39.20 = 485.86 MVA and SCR = 4.859 | ☐ |
| T4 | Transformer, classical (Option B) | 138 kV source 1000 MVA (R/X 0.1) + 100 MVA transformer 138/34.5 kV, vk 10%, vkr 0.5%; fault at 34.5 kV bus | 500.15 MVA | ☐ |
| T5 | Synchronous generator, classical (Option B) | T3b network + 100 MVA generator, X''d = 0.2 pu, at the POI | 984.30 MVA | ☐ |
| T6 | Input errors | Zero or negative rating, missing SCMVA, missing generator or source data | Clear error message, no crash | ☐ |
| M1 | Meshed network cross-check | 4-bus looped 138 kV network; classical result compared with pandapower's independent calculation | Match at every bus | ☐ |

The T3 value was produced by running pandapower 3.5.5 during drafting. It must be confirmed by hand before the test is accepted.

---

## 9. Required Disclaimer (README and report)

> SCR-Screen provides screening-level indicators of system strength. Results do not replace interconnection studies, detailed positive-sequence or EMT analysis, or the requirements of the applicable transmission provider. Thresholds are user-configurable and have no universal validity.

---

## 10. Open Decisions for the Author

| ID | Decision | Options | Your choice |
|---|---|---|---|
| D1 | Default rating basis | MW / MVA / report both | |
| D2 | Voltage factor c in network mode | Keep IEC 60909 c = 1.1 / normalize to 1.0 / report both | |
| D3 | Denominator for single-plant SCR | Rated MW / rated MVA / user choice per run | |
| D4 | Middle "moderate" band | Keep (with a source) / remove | |
| D5 | CSCR method | Virtual common bus (per GE guideline) / defer CSCR to v0.2 | |
| D6 | Report format | HTML only / HTML + PDF | |

---

## 11. References

1. NERC, *Integrating Inverter-Based Resources into Low Short Circuit Strength Systems*, Reliability Guideline, Dec 2017. Free.
2. NERC, *Short-Circuit Modeling and System Strength*, White Paper, Feb 2018. Free.
3. Y. Zhang, S.-H. F. Huang, J. Schmall, J. Conto, J. Billo, E. Rehman, "Evaluating system strength for large-scale wind plant integration," IEEE PES General Meeting, 2014. IEEE Xplore, paid. Origin of WSCR.
4. R. Fernandes, S. Achilles, J. MacDowell (GE Energy Consulting), *Report to NERC ERSTF for Composite Short Circuit Ratio (CSCR) Estimation Guideline*, Jan 2015. Cited in reference 1.
5. CIGRE WG B4.62, *Connection of Wind Farms to Weak AC Networks*, Technical Brochure 671, Dec 2016. Paid; CIGRE members may have access.
6. ERCOT, *Panhandle System Strength Assessment PSCAD Study*, Feb 2016. Cited in reference 1.
7. IEC 60909-0, *Short-circuit currents in three-phase a.c. systems — Calculation of currents*. Paid. Basis of pandapower's method.
8. pandapower documentation: the short-circuit module (`pandapower.shortcircuit`). Free.
9. IEEE Std 1204-1997, *IEEE Guide for Planning DC Links Terminating at AC Locations Having Low Short-Circuit Capacities*. Paid; source of the SCR 2/3 bands.
10. IEEE Std 551-2006 (Violet Book), *IEEE Recommended Practice for Calculating AC Short-Circuit Currents in Industrial and Commercial Power Systems*. Paid; ANSI/IEEE short-circuit practice.
