"""Classical flat-start short-circuit MVA (Option B).

Method (common U.S. planning practice for SCR screening):
    1. Every bus starts at 1.0 pu voltage ("flat start").
    2. Sources are modeled as impedances to ground:
         - external grids: Z = 1 / S_sc (pu), split by R/X, with NO IEC c-factor;
         - synchronous generators: sub-transient reactance X''d (plus R).
       Inverter-based resources (sgen, storage) are not sources, so their
       contribution is excluded automatically.
    3. Lines and transformers are series impedances. Loads, shunts and line
       charging are ignored; transformers are at nominal ratio (taps and
       off-nominal turns ratios are not modeled).
       Per-unit conversion: a transformer's short-circuit impedance is given on
       its own rating and rated voltage. It is referred to the low-voltage side
       and converted to the bus voltage base (the convention pandapower uses):
           z_pu = z_k × (S_base / S_n) × (V_n,LV winding / V_n,LV bus)²
       and a generator's X''d likewise: x_pu = X''d × (S_base / S_n) × (V_n,gen / V_n,bus)².
       When the rated voltages equal the bus nominal voltages the factors are 1.
    4. Build the bus admittance matrix Y, then for each bus i:
         Z_th,i = [Y^-1]_ii   and   SCMVA_i = S_base / |Z_th,i|   (V = 1.0 pu)

Supported elements: bus, ext_grid, gen, line, trafo (two-winding), and
line/transformer switches. Other in-service elements raise a clear error
rather than being silently ignored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .metrics import InputError

S_BASE_MVA = 100.0

# Element tables that would change the result but are not modeled.
UNSUPPORTED_TABLES = ("trafo3w", "impedance", "xward", "ward", "dcline", "tcsc", "ssc", "vsc")


@dataclass
class ZBus:
    """The network's bus impedance matrix on a 100 MVA base (classical model).

    z[pos[b], pos[k]] is the driving-point (b == k) or transfer impedance in pu.
    branches lists every in-service series element as (label, bus_a, bus_b, admittance_pu)
    of ONE circuit (an entry with parallel=2 contributes two circuits in Y), used for
    N-1 outage screening. sources lists every in-service synchronous generator as
    (label, bus, admittance_pu to ground), so generator outages can be screened too
    (external grids are network equivalents, not units, and are not listed).
    """

    z: np.ndarray
    pos: dict[int, int]
    isolated: list[int]
    notes: list[str]
    branches: list[tuple[str, int, int, complex]] = field(default_factory=list)
    sources: list[tuple[str, int, complex]] = field(default_factory=list)


def scmva_classical(net, bus_list: list[int], skip_isolated: bool = False
                    ) -> tuple[dict[int, float], list[str]]:
    """Return {bus: SCMVA} using the classical flat-start method, plus notes.

    Buses with no electrical path to any source cannot have a short-circuit
    level. With skip_isolated=True (used by full-network scans) they are left
    out and listed in the notes; otherwise requesting one raises InputError.
    """
    zb = build_zbus(net)
    z_bus, pos, isolated, notes = zb.z, zb.pos, zb.isolated, list(zb.notes)
    values = {}
    for b in bus_list:
        if b in isolated:
            if skip_isolated:
                continue
            raise InputError(f"Bus {b} has no path to any source (isolated part of the network).")
        if b not in pos:
            raise InputError(f"Bus {b} is out of service.")
        z_th = abs(z_bus[pos[b], pos[b]])
        if not math.isfinite(z_th) or z_th <= 0:
            raise InputError(f"Bus {b} has no valid path to a source.")
        values[b] = S_BASE_MVA / z_th
    return values, notes


def build_zbus(net) -> ZBus:
    """Build Y for the classical flat-start model and invert it to the Z-bus."""
    _check_supported(net)

    live = [int(b) for b in net.bus.index[net.bus["in_service"]]]
    reachable = connected_to_source(net, set(live))
    isolated = [b for b in live if b not in reachable]
    buses = [b for b in live if b in reachable]
    pos = {b: k for k, b in enumerate(buses)}
    n = len(buses)
    y = np.zeros((n, n), dtype=complex)
    notes = [
        "Classical flat-start: 1.0 pu pre-fault voltage, no IEC c-factor or "
        "correction factors; loads, shunts and line charging ignored; "
        "transformers at nominal ratio.",
    ]

    open_lines, open_trafos = _open_switches(net)
    n_base = n_base_gen = n_ratio = 0
    branches: list[tuple[str, int, int, complex]] = []
    sources: list[tuple[str, int, complex]] = []

    # --- Series branches: lines -------------------------------------------
    for idx, ln in net.line.iterrows():
        if not ln["in_service"] or idx in open_lines:
            continue
        f, t = int(ln["from_bus"]), int(ln["to_bus"])
        if f not in pos or t not in pos:
            continue
        vn = float(net.bus.at[f, "vn_kv"])
        par = float(ln.get("parallel", 1) or 1)
        z_ohm = complex(ln["r_ohm_per_km"], ln["x_ohm_per_km"]) * ln["length_km"] / par
        z_pu = z_ohm * S_BASE_MVA / vn**2
        adm = _add_branch(y, pos[f], pos[t], z_pu, f"line {idx}")
        branches.append((f"line {idx}", f, t, adm / par))  # one circuit

    # --- Series branches: two-winding transformers ------------------------
    for idx, tr in net.trafo.iterrows():
        if not tr["in_service"] or idx in open_trafos:
            continue
        hv, lv = int(tr["hv_bus"]), int(tr["lv_bus"])
        if hv not in pos or lv not in pos:
            continue
        zk = tr["vk_percent"] / 100.0
        rk = tr["vkr_percent"] / 100.0
        if zk <= 0 or rk < 0 or rk > zk:
            raise InputError(f"Transformer {idx} has invalid vk_percent/vkr_percent.")
        xk = math.sqrt(zk**2 - rk**2)
        par = float(tr.get("parallel", 1) or 1)
        k_v = _voltage_factor(tr.get("vn_lv_kv"), net.bus.at[lv, "vn_kv"])
        n_base += abs(k_v - 1.0) > BASE_TOL
        n_ratio += _off_nominal(tr, net.bus.at[hv, "vn_kv"], net.bus.at[lv, "vn_kv"])
        z_pu = complex(rk, xk) * (S_BASE_MVA / tr["sn_mva"]) * k_v / par
        adm = _add_branch(y, pos[hv], pos[lv], z_pu, f"transformer {idx}")
        branches.append((f"transformer {idx}", hv, lv, adm / par))  # one unit

    # --- Sources: external grids ------------------------------------------
    n_sources = 0
    for idx, eg in net.ext_grid.iterrows():
        if not eg["in_service"]:
            continue
        b = int(eg["bus"])
        s_sc = eg.get("s_sc_max_mva", np.nan)
        rx = eg.get("rx_max", np.nan)
        if not _is_pos(s_sc) or not _is_nonneg(rx):
            raise InputError(
                f"External grid {idx} needs s_sc_max_mva and rx_max for the "
                "classical method."
            )
        z_mag = S_BASE_MVA / s_sc
        x = z_mag / math.sqrt(1 + rx**2)
        _add_shunt(y, pos[b], complex(rx * x, x), f"external grid {idx}")
        n_sources += 1

    # --- Sources: synchronous generators -----------------------------------
    for idx, g in net.gen.iterrows():
        if not g["in_service"]:
            continue
        b = int(g["bus"])
        xdss, sn = g.get("xdss_pu", np.nan), g.get("sn_mva", np.nan)
        if not _is_pos(xdss) or not _is_pos(sn):
            raise InputError(
                f"Generator {idx} needs xdss_pu and sn_mva (sub-transient data) "
                "for the classical method."
            )
        vn = float(net.bus.at[b, "vn_kv"])
        rdss_ohm = g.get("rdss_ohm", 0.0)
        r_pu = 0.0 if not _is_nonneg(rdss_ohm) else rdss_ohm * S_BASE_MVA / vn**2
        k_v = _voltage_factor(g.get("vn_kv"), vn)
        n_base_gen += abs(k_v - 1.0) > BASE_TOL
        x_pu = xdss * S_BASE_MVA / sn * k_v
        sources.append((f"generator {idx}", b, _add_shunt(y, pos[b], complex(r_pu, x_pu), f"generator {idx}")))
        n_sources += 1

    if n_sources == 0:
        raise InputError("The network has no in-service external grid or generator.")

    try:
        z_bus = np.linalg.inv(y)
    except np.linalg.LinAlgError:
        raise InputError(
            "The network matrix could not be inverted. Part of the network is "
            "probably isolated from every source."
        ) from None

    if n_base or n_base_gen:
        what = " and ".join(t for t in (f"{n_base} transformer(s)" if n_base else "",
                                        f"{n_base_gen} generator(s)" if n_base_gen else "") if t)
        notes.append(f"Voltage base: {what} have a rated voltage different from the bus nominal voltage; "
                     "their impedances were converted to the bus voltage base (z × (V rated ÷ V bus)²).")
    if n_ratio:
        notes.append(f"Nominal ratio: {n_ratio} transformer(s) have a tap position away from neutral or a "
                     "rated turns ratio different from the bus voltage ratio; the classical method uses the "
                     "nominal ratio, so these are not modeled. This is the usual flat-start assumption; it can change the short-circuit MVA by several percent at buses next to those transformers.")
    if isolated:
        notes.append(f"{len(isolated)} bus(es) have no path to any source and were "
                     "excluded: " + ", ".join(str(b) for b in isolated[:20])
                     + (" ..." if len(isolated) > 20 else "") + ".")
    return ZBus(z=z_bus, pos=pos, isolated=isolated, notes=notes, branches=branches, sources=sources)


# ---------------------------------------------------------------------------

def connected_to_source(net, live: set[int]) -> set[int]:
    """Buses connected (through in-service lines/transformers) to a grid source or generator."""
    open_lines, open_trafos = _open_switches(net, allow_bus_bus=True)
    adj: dict[int, set[int]] = {b: set() for b in live}

    def link(a, b):
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)

    for idx, ln in net.line.iterrows():
        if ln["in_service"] and idx not in open_lines:
            link(int(ln["from_bus"]), int(ln["to_bus"]))
    for idx, tr in net.trafo.iterrows():
        if tr["in_service"] and idx not in open_trafos:
            link(int(tr["hv_bus"]), int(tr["lv_bus"]))
    if "trafo3w" in net and len(net.trafo3w):
        for _, t3 in net.trafo3w.iterrows():
            if t3["in_service"]:
                link(int(t3["hv_bus"]), int(t3["mv_bus"]))
                link(int(t3["hv_bus"]), int(t3["lv_bus"]))
    if "impedance" in net and len(net.impedance):
        for _, im in net.impedance.iterrows():
            if im["in_service"]:
                link(int(im["from_bus"]), int(im["to_bus"]))
    if "switch" in net and len(net.switch):
        for _, sw in net.switch.iterrows():
            if sw["et"] == "b" and sw["closed"]:
                link(int(sw["bus"]), int(sw["element"]))

    stack = []
    for table in ("ext_grid", "gen"):
        if table in net and len(net[table]):
            stack += [int(b) for b in net[table].loc[net[table]["in_service"], "bus"] if int(b) in adj]
    seen = set(stack)
    while stack:
        b = stack.pop()
        for n in adj[b]:
            if n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


def _add_branch(y, i, j, z_pu, label):
    if abs(z_pu) == 0:
        raise InputError(f"{label} has zero impedance; merge the buses instead.")
    adm = 1.0 / z_pu
    y[i, i] += adm
    y[j, j] += adm
    y[i, j] -= adm
    y[j, i] -= adm
    return adm


def _add_shunt(y, i, z_pu, label):
    if abs(z_pu) == 0:
        raise InputError(f"{label} has zero impedance.")
    y[i, i] += 1.0 / z_pu
    return 1.0 / z_pu


def _open_switches(net, allow_bus_bus: bool = False):
    """Lines and transformers disconnected by an open switch."""
    open_lines, open_trafos = set(), set()
    if "switch" not in net or len(net.switch) == 0:
        return open_lines, open_trafos
    for _, sw in net.switch.iterrows():
        if sw["et"] == "b" and sw["closed"] and not allow_bus_bus:
            raise InputError(
                "Closed bus-bus switches are not supported by the classical "
                "method. Merge those buses in the model."
            )
        if not sw["closed"]:
            if sw["et"] == "l":
                open_lines.add(int(sw["element"]))
            elif sw["et"] == "t":
                open_trafos.add(int(sw["element"]))
    return open_lines, open_trafos


def _check_supported(net):
    for table in UNSUPPORTED_TABLES:
        if table in net and len(net[table]) > 0 and "in_service" in net[table]:
            if bool(net[table]["in_service"].any()):
                raise InputError(
                    f"The network contains in-service '{table}' elements, which "
                    "the classical method does not model."
                )


BASE_TOL = 1e-6    # relative difference below which rated and bus voltages count as equal
RATIO_TOL = 1e-4


def _voltage_factor(v_rated, v_bus) -> float:
    """(V rated ÷ V bus)²: converts a per-unit impedance from the element's rated voltage to the bus base."""
    if not _is_pos(v_rated) or not _is_pos(v_bus):
        return 1.0
    return (float(v_rated) / float(v_bus)) ** 2


def _off_nominal(tr, vn_hv_bus, vn_lv_bus) -> bool:
    """True if the transformer's ratio differs from the bus voltage ratio (rated ratio or tap position)."""
    hv, lv = tr.get("vn_hv_kv"), tr.get("vn_lv_kv")
    if _is_pos(hv) and _is_pos(lv) and _is_pos(vn_hv_bus) and _is_pos(vn_lv_bus):
        if abs((float(hv) / float(lv)) / (float(vn_hv_bus) / float(vn_lv_bus)) - 1.0) > RATIO_TOL:
            return True
    pos, neutral, step = tr.get("tap_pos"), tr.get("tap_neutral"), tr.get("tap_step_percent")
    try:
        if all(v is not None and math.isfinite(float(v)) for v in (pos, neutral, step)):
            return abs((float(pos) - float(neutral)) * float(step)) > RATIO_TOL * 100
    except (TypeError, ValueError):
        pass
    return False


def off_nominal_transformers(net) -> tuple[int, int]:
    """(transformers whose rated LV voltage differs from the bus, transformers with an off-nominal ratio)."""
    n_base = n_ratio = 0
    for _, tr in net.trafo.iterrows():
        if not tr["in_service"]:
            continue
        hv, lv = int(tr["hv_bus"]), int(tr["lv_bus"])
        if hv not in net.bus.index or lv not in net.bus.index:
            continue
        n_base += abs(_voltage_factor(tr.get("vn_lv_kv"), net.bus.at[lv, "vn_kv"]) - 1.0) > BASE_TOL
        n_ratio += _off_nominal(tr, net.bus.at[hv, "vn_kv"], net.bus.at[lv, "vn_kv"])
    return int(n_base), int(n_ratio)


def _is_pos(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v)) and float(v) > 0
    except (TypeError, ValueError):
        return False


def _is_nonneg(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v)) and float(v) >= 0
    except (TypeError, ValueError):
        return False
