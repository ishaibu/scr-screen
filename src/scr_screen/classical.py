"""Classical flat-start short-circuit MVA (Option B).

Method (common U.S. planning practice for SCR screening):
    1. Every bus starts at 1.0 pu voltage ("flat start").
    2. Sources are modeled as impedances to ground:
         - external grids: Z = 1 / S_sc (pu), split by R/X, with NO IEC c-factor;
         - synchronous generators: sub-transient reactance X''d (plus R).
       Inverter-based resources (sgen, storage) are not sources, so their
       contribution is excluded automatically.
    3. Lines and transformers are series impedances. Loads, shunts and line
       charging are ignored; transformers are at nominal ratio.
    4. Build the bus admittance matrix Y, then for each bus i:
         Z_th,i = [Y^-1]_ii   and   SCMVA_i = S_base / |Z_th,i|   (V = 1.0 pu)

v0.1 supports: bus, ext_grid, gen, line, trafo (two-winding), and
line/transformer switches. Other in-service elements raise a clear error
rather than being silently ignored.
"""

from __future__ import annotations

import math

import numpy as np

from .metrics import InputError

S_BASE_MVA = 100.0

# Element tables that would change the result but aren't modeled in v0.1.
UNSUPPORTED_TABLES = ("trafo3w", "impedance", "xward", "ward", "dcline", "tcsc", "ssc", "vsc")


def scmva_classical(net, bus_list: list[int]) -> tuple[dict[int, float], list[str]]:
    """Return {bus: SCMVA} using the classical flat-start method, plus notes."""
    _check_supported(net)

    buses = [int(b) for b in net.bus.index[net.bus["in_service"]]]
    pos = {b: k for k, b in enumerate(buses)}
    n = len(buses)
    y = np.zeros((n, n), dtype=complex)
    notes = [
        "Classical flat-start: 1.0 pu pre-fault voltage, no IEC c-factor or "
        "correction factors; loads, shunts and line charging ignored; "
        "transformers at nominal ratio.",
    ]

    open_lines, open_trafos = _open_switches(net)

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
        _add_branch(y, pos[f], pos[t], z_pu, f"line {idx}")

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
        z_pu = complex(rk, xk) * (S_BASE_MVA / tr["sn_mva"]) / par
        _add_branch(y, pos[hv], pos[lv], z_pu, f"transformer {idx}")

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
        x_pu = xdss * S_BASE_MVA / sn
        _add_shunt(y, pos[b], complex(r_pu, x_pu), f"generator {idx}")
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

    values = {}
    for b in bus_list:
        if b not in pos:
            raise InputError(f"Bus {b} is out of service.")
        z_th = abs(z_bus[pos[b], pos[b]])
        if not math.isfinite(z_th) or z_th <= 0:
            raise InputError(f"Bus {b} has no valid path to a source.")
        values[b] = S_BASE_MVA / z_th
    return values, notes


# ---------------------------------------------------------------------------

def _add_branch(y, i, j, z_pu, label):
    if abs(z_pu) == 0:
        raise InputError(f"{label} has zero impedance; merge the buses instead.")
    adm = 1.0 / z_pu
    y[i, i] += adm
    y[j, j] += adm
    y[i, j] -= adm
    y[j, i] -= adm


def _add_shunt(y, i, z_pu, label):
    if abs(z_pu) == 0:
        raise InputError(f"{label} has zero impedance.")
    y[i, i] += 1.0 / z_pu


def _open_switches(net):
    """Lines and transformers disconnected by an open switch."""
    open_lines, open_trafos = set(), set()
    if "switch" not in net or len(net.switch) == 0:
        return open_lines, open_trafos
    for _, sw in net.switch.iterrows():
        if sw["et"] == "b" and sw["closed"]:
            raise InputError(
                "Closed bus-bus switches are not supported by the classical "
                "method in v0.1. Merge those buses in the model."
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
                    "the classical method does not model in v0.1."
                )


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
