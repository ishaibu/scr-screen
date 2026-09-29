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