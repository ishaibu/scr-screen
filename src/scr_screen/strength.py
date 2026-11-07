"""Network-aware system strength metrics from the classical bus impedance matrix.

All quantities use the classical flat-start Z-bus (100 MVA base), so they are
consistent with the classical short-circuit MVA:

Interaction factor (NERC Reliability Guideline, Dec 2017; NREL/TP-5D00-94961)
    IF_ij = dV_i / dV_j  for a current injection at bus j  =  |Z_ij / Z_jj|
    How much bus i's voltage moves when bus j's voltage moves (0 = no
    interaction, 1 = same bus).

SCR with interaction factors (SCRIF)
    SCRIF_i = SCMVA_i / (P_i + sum_{j != i} IF_ij * P_j)
    Sits between SCR (no interaction) and WSCR (full interaction).

Composite SCR (CSCR), evaluated at the points of interconnection
    The group's buses are tied together with zero impedance and the
    short-circuit MVA is taken at the combined bus:
        Z_eq = 1 / (1' * inv(Z_GG) * 1),  CSCMVA = S_base / |Z_eq|,
        CSCR = CSCMVA / sum(P)
    NERC's definition ties the plants' medium-voltage buses; plant collector
    systems are not in a transmission model, so SCR-Screen ties the POIs.

Effective SCR (ESCR)
    ESCR_i = (SCMVA_i - Q_c,i) / P_i, where Q_c,i is the capacitive shunt
    compensation (Mvar at 1.0 pu) connected at the bus.

N-1 worst case
    Each in-service line circuit, transformer unit and synchronous generator unit
    is removed in turn (Sherman-Morrison update of the Z-bus diagonal) and the
    lowest SCMVA at each bus is kept with the outage that causes it. Outages that
    would leave buses with no source (islanding) are skipped and counted.
    Removing a branch of admittance y between buses a and b uses m = e_a - e_b;
    removing a generator (admittance y to ground at bus k) uses m = e_k:
        Y' = Y - y m m',   Z'_ii = Z_ii + y (Z m)_i^2 / (1 - y m' Z m)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .classical import S_BASE_MVA, ZBus
from .metrics import InputError

ISLAND_TOL = 1e-9


def interaction_factor(zb: ZBus, i: int, j: int) -> float:
    """IF_ij = |Z_ij / Z_jj|: voltage change at bus i per unit voltage change at bus j."""
    if i == j:
        return 1.0
    pi, pj = _pos(zb, i), _pos(zb, j)
    return float(abs(zb.z[pi, pj] / zb.z[pj, pj]))


def interaction_matrix(zb: ZBus, buses: list[int]) -> dict[tuple[int, int], float]:
    return {(i, j): interaction_factor(zb, i, j) for i in buses for j in buses}


def scrif(scmva: dict[int, float], mw: dict[int, float], ifs: dict[tuple[int, int], float]) -> dict[int, float]:
    """SCRIF for each bus of a group. mw: plant MW at each bus of the group."""
    out = {}
    for i in mw:
        denom = mw[i] + sum(ifs[(i, j)] * mw[j] for j in mw if j != i)
        out[i] = scmva[i] / denom
    return out


def interaction_sums(ifs: dict[tuple[int, int], float], buses: list[int]) -> dict[int, float]:
    """sum_{j != i} IF_ij over a group; with equal plant sizes P, SCRIF_i = SCMVA_i / (P * (1 + sum))."""
    return {i: sum(ifs[(i, j)] for j in buses if j != i) for i in buses}


def composite_scmva(zb: ZBus, buses: list[int]) -> float:
    """Short-circuit MVA at the group's buses tied together (zero impedance)."""
    idx = [_pos(zb, b) for b in buses]
    z_gg = zb.z[np.ix_(idx, idx)]
    ones = np.ones(len(idx))
    y_eq = ones @ np.linalg.solve(z_gg, ones)
    if abs(y_eq) == 0:
        raise InputError("Composite short-circuit MVA could not be computed for this group.")
    return float(S_BASE_MVA * abs(y_eq))


def capacitor_mvar(net) -> dict[int, float]:
    """Capacitive shunt compensation at each bus, Mvar at 1.0 pu (pandapower: q_mvar < 0 is capacitive)."""
    out: dict[int, float] = {}
    if "shunt" not in net or len(net.shunt) == 0:
        return out
    for _, sh in net.shunt.iterrows():
        if not sh.get("in_service", True):
            continue
        step = sh.get("step", 1)
        step = 1 if step is None or not np.isfinite(step) else step
        q = float(sh["q_mvar"]) * float(step)
        if q < 0:
            out[int(sh["bus"])] = out.get(int(sh["bus"]), 0.0) - q
    return out


@dataclass(frozen=True)
class N1Result:
    scmva: dict[int, float]        # worst-case (lowest) SCMVA per bus
    outage: dict[int, str]         # outage label causing it ("none" if no outage lowers it)
    studied: int                   # outages evaluated
    skipped: list[str]             # outages skipped because they island buses
    zth: dict[int, complex] = field(default_factory=dict)  # complex Z_ii (pu) in that worst case


def n1_worst(zb: ZBus, buses: list[int], label=None, generators: bool = True) -> N1Result:
    """Worst single-outage SCMVA for each bus in `buses` (Sherman-Morrison on the Z diagonal).

    Outages: every line circuit and transformer unit, and (if `generators`) every
    synchronous generator unit.
    """
    label = label or (lambda b: str(b))
    z = zb.z
    cols = [_pos(zb, b) for b in buses]
    base_diag = np.array([z[c, c] for c in cols])
    worst = {b: S_BASE_MVA / abs(d) for b, d in zip(buses, base_diag)}
    cause = {b: "none" for b in buses}
    zth = {b: complex(d) for b, d in zip(buses, base_diag)}
    studied, skipped = 0, []
    outages = []
    for name, a, b, y1 in zb.branches:
        if a in zb.pos and b in zb.pos:
            outages.append((f"{name} ({label(a)}–{label(b)})", zb.pos[a], zb.pos[b], y1))
    if generators:
        for name, k, y1 in zb.sources:
            if k in zb.pos:
                outages.append((f"{name} ({label(k)})", zb.pos[k], None, y1))
    for text, pa, pb, y1 in outages:
        if pb is None:
            zm = z[:, pa].copy()                 # Z m, with m = e_k (unit to ground)
            mzm = zm[pa]
        else:
            zm = z[:, pa] - z[:, pb]             # Z m, with m = e_a - e_b
            mzm = zm[pa] - zm[pb]                # m' Z m
        c = -y1                                  # removing the element: Y' = Y + c m m'
        denom = 1.0 + c * mzm
        if abs(denom) < ISLAND_TOL * max(1.0, abs(c * mzm)):
            skipped.append(text)
            continue
        studied += 1
        zm_sel = zm[cols]
        new_diag = base_diag - c * zm_sel * zm_sel / denom
        for k, bus in enumerate(buses):
            d = abs(new_diag[k])
            if not np.isfinite(d) or d <= 0:
                continue
            s = S_BASE_MVA / d
            if s < worst[bus] - 1e-9:
                worst[bus], cause[bus], zth[bus] = s, text, complex(new_diag[k])
    return N1Result(worst, cause, studied, skipped, zth)


def suggest_groups(ifs: dict[tuple[int, int], float], buses: list[int], threshold: float) -> list[list[int]]:
    """Suggest groups so that EVERY pair of buses in a group interacts at least `threshold`.

    Pair interaction = max(IF_ij, IF_ji) (strong in at least one direction). Clusters are
    merged greedily, strongest link first, only while every cross pair meets the threshold
    (complete linkage), so a chain of moderately close buses does not become one huge group.
    Buses that interact with no other listed bus are left out (screened alone).
    """
    def pair(i, j):
        return max(ifs[(i, j)], ifs[(j, i)])

    clusters = [[b] for b in buses]
    while True:
        best, best_val = None, threshold
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                link = min(pair(i, j) for i in clusters[a] for j in clusters[b])
                if link >= best_val and (best is None or link > best_val):
                    best, best_val = (a, b), link
        if best is None:
            break
        a, b = best
        clusters[a] = clusters[a] + clusters[b]
        del clusters[b]
    return [sorted(c, key=buses.index) for c in clusters if len(c) > 1]


def _pos(zb: ZBus, b: int) -> int:
    if b not in zb.pos:
        raise InputError(f"Bus {b} is isolated or out of service.")
    return zb.pos[b]
