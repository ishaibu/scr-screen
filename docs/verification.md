# SCR-Screen — Verification Record

This file records independent checks of SCR-Screen results. Each entry states
what was checked, how, the result, and what the check does and does not prove.

Checks are performed by the author as an engineering review of the tool. They
are not a sealed engineering document or an endorsement of results for any
real project.

---

## Summary

| ID | Date | What was checked | Method | Result |
|---|---|---|---|---|
| V1 | 2026-09-29 | IEEE 39-bus, bus 12, classical SCMVA | Hand calculation (two-port reduction) | Match |
| V2 | 2026-10-17 | IEEE 39-bus, group G1 (buses 11 + 13), WSCR | Hand calculation from reported SCMVA | Match |
| V3 | 2026-11-01 | IEEE 39-bus, group G1, interaction factors, SCRIF, CSCR | Hand calculation from impedance matrix | Match |
| V4 | 2026-11-06 | IEEE 39-bus, MVA basis (WSCR-MVA, CSCR-MVA, SCRIF), STATCOM in a group, generator outage at bus 38 | Hand calculation | Match |

---

## V1 — IEEE 39-bus, bus 12 (classical flat-start)

**Date:** 2026-09-29
**Checked by:** Shaibu Ibrahim, P.E.
**Tool version:** 0.1.0.dev0 (commit: `e3605bc5c4369671f6df515dedf6738946e9ac46`)
**Case:** `examples/ieee39_example.py`, with its documented assumed
short-circuit data (X''d = 0.20 pu, R/X = 0.05, rating = max MW ÷ 0.85).

### Why this bus
IEEE bus 12 is the weakest bus in the scan (SCR 1.89 for a 1,500 MW plant).
It has no generator and no lines, only two transformers: to bus 11 and to
bus 13. This allows a hand calculation of the final step.

### Method
The rest of the network (bus 12 removed) was represented by its two-port
impedance matrix at buses 11 and 13, from SCR-Screen. Bus 12 was then added
by hand through its two transformers:

    Z_th = Zm + (A × B) / (A + B)
    A = Z11 + za − Zm
    B = Z13 + zb − Zm

### Data (per unit, 100 MVA base)

| Symbol | Meaning | Value | Source |
|---|---|---|---|
| za | Transformer, bus 12 to 11 | 0.001600 + j0.043500 | Hand-derived from transformer data; matches original IEEE data |
| zb | Transformer, bus 12 to 13 | 0.001600 + j0.043500 | Same |
| Z11 | Rest of network, Thévenin at bus 11 | 0.000831 + j0.014984 | SCR-Screen |
| Z13 | Rest of network, Thévenin at bus 13 | 0.000919 + j0.015584 | SCR-Screen |
| Zm | Rest of network, mutual 11–13 | 0.000560 + j0.011763 | SCR-Screen |

### Results

| Quantity | Hand calculation | SCR-Screen |
|---|---|---|
| Z_th (pu) | 0.001517 + j0.035273 | 0.001517 + j0.035273 |
| \|Z_th\| (pu) | 0.035305 | 0.035305 |
| SCMVA | 2,832 MVA | 2,832.43 MVA |
| SCR, 1,500 MW plant | 1.89 (very weak) | 1.89 (very weak) |

**Outcome:** Match.

### What this proves
- Transformer impedances are converted to the system base correctly.
- Two paths that share part of the network (mutual impedance) are combined correctly.
- Thévenin impedance is converted to short-circuit MVA and SCR correctly.

### What this does not prove
- The values of Z11, Z13 and Zm, which came from SCR-Screen. The underlying
  network matrix is checked separately by test M1 (meshed network compared
  with pandapower's independent calculation).
- A comparison with an independent commercial or open-source tool is
  planned before the public release.

---

## V2 — IEEE 39-bus, group G1 WSCR (buses 11 and 13)

**Date:** 2026-10-17
**Checked by:** Shaibu Ibrahim, P.E.
**Tool version:** 0.2.0
**Case:** `scr-screen scan ieee39_assumed.json --plant-mw 1500 --groups ieee39_groups_example.csv`,
with the documented assumed short-circuit data used in V1.

### Why this group
Buses 11 and 13 each pass the single-plant screen at 1,500 MW (SCR 4.48 and
4.31), but the group is flagged weak. That is exactly the case WSCR exists to
catch, so it is the most useful one to confirm by hand.

### Method
WSCR for plants assumed fully interacting (ERCOT/NERC formulation):

    WSCR = Σ(SCMVAᵢ × Pᵢ) ÷ (ΣPᵢ)²

The short-circuit MVA values were taken from the SCR-Screen report (Results
table, SCMVA column). Their accuracy is not part of this check (see below).

### Data

| Bus | SCMVA (from report) | Plant P (MW) | SCMVA × P |
|---|---|---|---|
| 11 | 6,712.87 | 1,500 | 10,069,310 |
| 13 | 6,470.21 | 1,500 | 9,705,308 |
| **Total** | | **3,000** | **19,774,618** |

### Results

| Quantity | Hand calculation | SCR-Screen |
|---|---|---|
| (ΣP)² | 9,000,000 | — |
| WSCR at 1,500 MW | 19,774,618 ÷ 9,000,000 = **2.197** | 2.197 |
| Flag (weak below 3, very weak below 2) | Weak | Weak |
| WSCR at 1,000 MW (slider) | 13,183.08 × 1,000 ÷ 2,000² = **3.296** | 3.30 (report shows 2 decimals) |

**Outcome:** Match.

### What this proves
- The WSCR formula is applied correctly to a network scan group.
- The live browser recalculation (slider) gives the same WSCR as the hand
  calculation at a second plant size.

### What this does not prove
- The SCMVA values themselves. For the classical method these rest on the
  network matrix checked in V1 and test M1.
- That buses 11 and 13 are fully interacting. WSCR assumes they are; for
  buses electrically far apart the result is conservative. Methods that use
  the network's mutual impedances (CSCR and SCRIF) were added in v0.3.0; see V3.

---

## V3 — IEEE 39-bus, group G1 interaction factors, SCRIF and CSCR (buses 11 and 13)

**Date:** 2026-11-01
**Checked by:** Shaibu Ibrahim, P.E.
**Tool version:** 0.3.0
**Case:** `scr-screen scan ieee39_assumed.json --plant-mw 1500 --groups ieee39_groups_example.csv --n1`,
with the documented assumed short-circuit data used in V1 and V2.

### Why this group
V2 confirmed the WSCR of group G1 (2.197, weak). WSCR assumes the two plants
fully interact. v0.3.0 adds two metrics that use the network's mutual
impedance instead: SCRIF and CSCR. Checking them on the same group shows how
much of the WSCR result comes from the full-interaction assumption.

### Method
From the classical bus impedance matrix (100 MVA base), take the two
driving-point impedances Z₁₁, Z₁₃ and the transfer impedance Z₁₁,₁₃
(printed by a short Python snippet, shown below).

    Interaction factor   IF(i←j) = |Zᵢⱼ| ÷ |Zⱼⱼ|
    Short-circuit MVA    Sᵢ = 100 ÷ |Zᵢᵢ|
    SCRIF                SCRIFᵢ = Sᵢ ÷ (Pᵢ + IF(i←j) × Pⱼ)
    CSCR (two buses tied together)
                         Yeq = (Z₁₁ + Z₁₃ − 2Z₁₁,₁₃) ÷ (Z₁₁Z₁₃ − Z₁₁,₁₃²)
                         CSCMVA = 100 × |Yeq|,   CSCR = CSCMVA ÷ (P₁₁ + P₁₃)

The CSCR formula is the two-bus case of Z_eq = 1 ÷ (1ᵀ Z_GG⁻¹ 1).

Snippet used to print the impedances (run in the repository folder):

    python -c "import pandapower as pp; from scr_screen.classical import build_zbus; net=pp.from_json('examples/ieee39_assumed.json'); zb=build_zbus(net); n={str(net.bus.at[b,'name']):int(b) for b in net.bus.index}; i,j=zb.pos[n['11']],zb.pos[n['13']]; print(zb.z[i,i], zb.z[j,j], zb.z[i,j])"

### Data (per unit, 100 MVA base, rounded to 7 decimals)

| Quantity | Value | Magnitude |
|---|---|---|
| Z₁₁ (bus 11) | 0.0008171 + j0.0148743 | 0.0148968 |
| Z₁₃ (bus 13) | 0.0008965 + j0.0154294 | 0.0154555 |
| Z₁₁,₁₃ (transfer) | 0.0005780 + j0.0118937 | 0.0119077 |

### Results

| Quantity | Hand calculation | SCR-Screen |
|---|---|---|
| S₁₁ = 100 ÷ 0.0148968 | 6,712.9 MVA | 6,712.87 |
| S₁₃ = 100 ÷ 0.0154555 | 6,470.2 MVA | 6,470.21 |
| IF(11←13) = 0.0119077 ÷ 0.0154555 | 0.7705 | 0.7705 |
| IF(13←11) = 0.0119077 ÷ 0.0148968 | 0.7994 | 0.7994 |
| SCRIF bus 11 = 6,712.9 ÷ (1,500 + 0.7705 × 1,500) | **2.528** | 2.528 |
| SCRIF bus 13 = 6,470.2 ÷ (1,500 + 0.7994 × 1,500) | **2.397** | 2.397 |
| Z₁₁ + Z₁₃ − 2Z₁₁,₁₃ | 0.0005576 + j0.0065163 (mag 0.0065401) | — |
| Z₁₁Z₁₃ − Z₁₁,₁₃² | −0.0000876 + j0.0000122 (mag 0.000088487) | — |
| CSCMVA = 100 × 0.0065401 ÷ 0.000088487 | ≈ 7,391 MVA | 7,391.03 |
| CSCR at 1,500 MW each = 7,391 ÷ 3,000 | **2.464** | 2.464 |
| SCRIF at 1,000 MW (slider): bus 11 / bus 13 | 3.792 / 3.596 | 3.792 / 3.596 |
| CSCR at 1,000 MW (slider) = 7,391 ÷ 2,000 | 3.696 | 3.696 |

Hand values from the 7-decimal impedances agree with the tool to about five
significant figures; the small differences come from rounding the inputs.

Order check: SCR (4.48 / 4.31) > SCRIF (2.53 / 2.40) and CSCR (2.46) > WSCR (2.20),
as expected for two buses with interaction factors near 0.8.

**Outcome:** Match / Mismatch   <!-- choose after checking -->

### What this proves
- The interaction factor, SCRIF and CSCR formulas are applied correctly to the
  network's impedance matrix for a two-plant group.
- The report's live recalculation gives the same SCRIF and CSCR at a second
  plant size.

### What this does not prove
- The impedance matrix itself (rests on V1 and test M1).
- CSCR at the plants' medium-voltage buses. SCR-Screen ties the points of
  interconnection, because plant collector systems are not in transmission
  models; NERC's definition ties the medium-voltage buses.
- N-1 results. These are checked by an automated test that rebuilds the
  network for every outage (agreement within 10⁻⁹), not by this hand check.

---

## V4 — IEEE 39-bus, MVA basis (WSCR-MVA, CSCR-MVA, SCRIF), a STATCOM in a group, and a generator outage

**Date:** 2026-11-06 
**Checked by:** Shaibu Ibrahim, P.E.
**Tool version:** 0.3.1
**Cases:**
- A, C: `scr-screen scan ieee39_assumed.json --plant-mw 1500 --plant-mva 1650 --basis MVA --groups ieee39_groups_mva_example.csv`
- B: `scr-screen scan ieee39_assumed.json --plant-mw 1500 --plant-mva 1650 --basis MVA --groups ieee39_groups_example.csv`
- D: `scr-screen scan ieee39_assumed.json --plant-mw 1500 --n1`

All with the documented assumed short-circuit data used in V1 to V3. The 200 MVA
STATCOM at bus 12 is illustrative.

### Why these cases
v0.3.1 adds the MVA basis to network scans (NERC's WSCR-MVA, and CSCR divided by
nominal MVA as NERC defines it), devices with no active power such as STATCOMs,
and generator outages in N-1. Each is checked once by hand.

### Method
- **A. WSCR-MVA:** WSCR = Σ(SCMVAᵢ × Pᵢ) ÷ (ΣPᵢ)², with P in MVA, for buses 11 and 13
  (1,650 MVA each) and the STATCOM at bus 12 (200 MVA, 0 MW). On the MW basis the
  STATCOM is left out.
- **B. CSCR-MVA:** CSCMVA (7,391.03 MVA, verified in V3) ÷ (1,650 + 1,650).
- **C. SCRIF on the MVA basis:** SCRIFᵢ = SCMVAᵢ ÷ (Pᵢ + IF × Pⱼ), interaction factors from V3.
- **D. Generator outage at the plant's own bus:** the rest of the network stays in
  parallel, so the Thévenin admittance loses the generator's admittance:
  Y′ = 1 ÷ Z₃₈,₃₈ − y_gen, and SCMVA′ = 100 × |Y′|.

Snippet used to print Z₃₈,₃₈ and generator 7's data (run in the repository folder):

    python -c "import pandapower as pp; from scr_screen.classical import build_zbus; net=pp.from_json('examples/ieee39_assumed.json'); zb=build_zbus(net); n={str(net.bus.at[b,'name']):int(b) for b in net.bus.index}; k=n['38']; print(zb.z[zb.pos[k],zb.pos[k]]); print(net.gen[net.gen.bus==k][['sn_mva','xdss_pu','rdss_ohm']])"

### Results

| Check | Hand calculation | SCR-Screen |
|---|---|---|
| A. WSCR-MVA, G1 with STATCOM | 22,318,568 ÷ 3,500² = **1.822** | 1.822 |
| A. Same group, MW basis (STATCOM left out) | **2.197** | 2.197 |
| B. CSCR-MVA, G1 | 7,391.03 ÷ 3,300 = **2.240** | 2.240 |
| C. SCRIF bus 11 / bus 13, MVA basis | 6,712.87 ÷ 2,921.325 = **2.298** / 6,470.21 ÷ 2,969.010 = **2.179** | 2.298 / 2.179 |
| D. Z₃₈,₃₈ | 0.0008897 + j0.0154951 pu (intact SCMVA 6,443.0) | 6,443.03 |
| D. y_gen (generator 7: 1,017.65 MVA, X″d 0.20, R 1.16961 Ω at 345 kV) | 2.5378 − j50.7556 pu | — |
| D. Y′ = 1/Z₃₈,₃₈ − y_gen | (3.6934 − j64.3245) − (2.5378 − j50.7556) = 1.1556 − j13.5689; magnitude 13.618 | — |
| D. SCMVA with generator 7 out | **1,361.8 MVA** | 1,361.80 |
| D. N-1 SCR at 1,500 MW | **0.908** (worst outage for bus 38: generator 7) | 0.908, generator 7 (Bus 38) |

Hand values from rounded inputs agree with the tool to about four significant figures.
Step-by-step working is in the V4 hand-calculation worksheet.

**Outcome:** Match / 

### What this proves
- The MVA basis is applied to WSCR, CSCR and SCRIF in network scans, and CSCR then
  matches NERC's definition (nominal MVA in the denominator).
- A device with no active power counts on the MVA basis and is left out on the MW basis.
- A generator outage is evaluated correctly for a plant at that generator's bus.

### What this does not prove
- The impedance matrix itself (V1 and test M1), or CSCMVA (V3).
- Generator outages at other buses, and SCRIF for a three-member group. These are
  checked by automated tests that rebuild the network for every outage and compute
  SCRIF from the impedance matrix directly.
- Whether a STATCOM's own SCRIF is a meaningful acceptance criterion for that device.
  NERC's table credits SCRIF and WSCR-MVA with considering non-active inverter
  capacity; the tool reports the value and leaves its use to the engineer.
