"""Short-circuit MVA from a network model, and a scan of every bus.

Option A: IEC 60909 via pandapower's ``calc_sc``.
Option B: classical flat-start, 1.0 pu pre-fault voltage (see classical.py).

Inverter-based resources (IBRs) are EXCLUDED from the short-circuit
calculation by default, as the NERC SCR definitions require. The user's
network is never modified: all work is done on a copy.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import pandapower.shortcircuit as sc

from .classical import scmva_classical
from .metrics import InputError, classify, scr
from .settings import DEFAULT_THRESHOLDS, Thresholds

# pandapower element tables that hold inverter-based resources.
IBR_TABLES = ("sgen", "storage")

METHOD_IEC = "iec60909"
METHOD_CLASSICAL = "classical"


@dataclass
class ShortCircuitResult:
    """Short-circuit MVA at one or more buses, plus how it was calculated."""

    method: str
    case: str
    ibr_excluded: bool
    scmva: dict[int, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def scmva_iec(net, buses=None, case: str = "max", exclude_ibr: bool = True) -> ShortCircuitResult:
    """Three-phase short-circuit MVA per IEC 60909, using pandapower.

    Args:
        net: a pandapower network. It is not modified.
        buses: bus index or list of bus indices. None means every bus.
        case: "max" (voltage factor c = 1.1 above 1 kV) or "min".
        exclude_ibr: set IBRs (sgen, storage) out of service first. Keep True
            for SCR screening, per NERC.

    Returns:
        ShortCircuitResult with SCMVA in MVA for each bus requested.
    """
    if case not in ("max", "min"):
        raise InputError(f"case must be 'max' or 'min', got {case!r}.")

    work = copy.deepcopy(net)
    notes = [f"IEC 60909 via pandapower calc_sc, case='{case}'."]

    if exclude_ibr:
        removed = 0
        for table in IBR_TABLES:
            if table in work and len(work[table]) > 0:
                removed += int(work[table]["in_service"].sum())
                work[table]["in_service"] = False
        notes.append(f"IBR contribution excluded ({removed} element(s) set out of service).")

    bus_list = _bus_list(work, buses)

    try:
        sc.calc_sc(work, bus=bus_list, case=case, fault="3ph")
    except (ValueError, KeyError) as err:
        raise InputError(
            "pandapower could not run the short-circuit calculation. The network "
            f"is probably missing short-circuit data. pandapower said: {err}"
        ) from err

    # pandapower names this column 'skss_mw', but it is apparent power (MVA).
    values = {int(b): float(work.res_bus_sc.at[b, "skss_mw"]) for b in bus_list}
    return ShortCircuitResult(METHOD_IEC, case, exclude_ibr, values, notes)


def scmva_flat(net, buses=None) -> ShortCircuitResult:
    """Three-phase short-circuit MVA by the classical flat-start method.

    Inverter-based resources are never sources in this method, so their
    contribution is always excluded. The user's network is not modified.
    """
    bus_list = _bus_list(net, buses)
    values, notes = scmva_classical(net, bus_list)
    return ShortCircuitResult(METHOD_CLASSICAL, "flat", True, values, notes)


def scmva(net, buses=None, method: str = METHOD_IEC, case: str = "max") -> ShortCircuitResult:
    """Dispatch to the chosen short-circuit method."""
    if method == METHOD_IEC:
        return scmva_iec(net, buses=buses, case=case)
    if method == METHOD_CLASSICAL:
        return scmva_flat(net, buses=buses)
    raise InputError(f"method must be '{METHOD_IEC}' or '{METHOD_CLASSICAL}', got {method!r}.")


@dataclass(frozen=True)
class ScanRow:
    """One bus in a grid-strength scan."""

    bus: int
    name: str
    vn_kv: float
    scmva: float
    scr: float
    flag: str


def scan_buses(
    net,
    plant_mw: float,
    buses=None,
    method: str = METHOD_IEC,
    case: str = "max",
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> list[ScanRow]:
    """SCR a plant of ``plant_mw`` would see at each bus, strongest first.

    This answers the siting question "which buses in this model are strong
    enough for a plant of this size?" It is single-plant SCR only; nearby
    plants should be checked together with WSCR.
    """
    result = scmva(net, buses=buses, method=method, case=case)
    rows = []
    for bus, s in result.scmva.items():
        value = scr(s, plant_mw)
        name = net.bus.at[bus, "name"]
        rows.append(
            ScanRow(
                bus=bus,
                name="" if name is None else str(name),
                vn_kv=float(net.bus.at[bus, "vn_kv"]),
                scmva=s,
                scr=value,
                flag=classify(value, thresholds).value,
            )
        )
    rows.sort(key=lambda r: r.scr, reverse=True)
    return rows


def _bus_list(net, buses) -> list[int]:
    """Normalize the bus argument and check every bus exists and is in service."""
    if buses is None:
        return [int(b) for b in net.bus.index[net.bus["in_service"]]]
    if isinstance(buses, (int,)) and not isinstance(buses, bool):
        buses = [buses]
    bus_list = [int(b) for b in buses]
    missing = [b for b in bus_list if b not in net.bus.index]
    if missing:
        raise InputError(f"Bus index not found in the network: {missing}.")
    return bus_list
