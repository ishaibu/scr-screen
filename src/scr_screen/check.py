"""Check whether a network is ready for SCR-Screen, before scanning.

Lists, in plain language, anything missing or unsupported (for example a
generator without sub-transient reactance), and says which short-circuit
methods can run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .classical import UNSUPPORTED_TABLES, connected_to_source
from .netmap import MAX_MAP_BUSES, bus_label

ERROR, WARNING, INFO = "error", "warning", "info"
CLASSICAL_SLOW_ABOVE = 5000


@dataclass
class Finding:
    level: str      # error, warning, info
    applies_to: str  # "both", "classical", "iec60909", or "report"
    message: str


@dataclass
class CheckReport:
    n_buses: int
    findings: list[Finding] = field(default_factory=list)

    def ready(self, method: str) -> bool:
        return not any(f.level == ERROR and f.applies_to in ("both", method) for f in self.findings)

    def add(self, level, applies_to, message):
        self.findings.append(Finding(level, applies_to, message))


def check_network(net) -> CheckReport:
    live = [int(b) for b in net.bus.index[net.bus["in_service"]]] if len(net.bus) else []
    rep = CheckReport(n_buses=len(live))
    if not live:
        rep.add(ERROR, "both", "The network has no in-service buses.")
        return rep

    # --- Sources --------------------------------------------------------------
    eg = net.ext_grid[net.ext_grid["in_service"]] if "ext_grid" in net else []
    gens = net.gen[net.gen["in_service"]] if "gen" in net else []
    if len(eg) == 0 and len(gens) == 0:
        rep.add(ERROR, "both", "No in-service external grid or synchronous generator: "
                "there is no source of short-circuit current.")

    for idx, row in (eg.iterrows() if len(eg) else []):
        name = _name(row, f"external grid {idx}")
        if not _pos(row.get("s_sc_max_mva")) or not _nonneg(row.get("rx_max")):
            rep.add(ERROR, "both", f"{name} (bus {bus_label(net, int(row['bus']))}) needs "
                    "s_sc_max_mva and rx_max (short-circuit MVA and R/X of the grid source).")

    missing_classical, missing_iec = [], []
    for idx, row in (gens.iterrows() if len(gens) else []):
        name = f"{_name(row, f'generator {idx}')} (bus {bus_label(net, int(row['bus']))})"
        if not _pos(row.get("xdss_pu")) or not _pos(row.get("sn_mva")):
            missing_classical.append(name)
        elif not (_pos(row.get("vn_kv")) and _nonneg(row.get("rdss_ohm")) and _pos(row.get("cos_phi"))):
            missing_iec.append(name)
    if missing_classical:
        rep.add(ERROR, "both", f"{len(missing_classical)} generator(s) lack sub-transient data "
                f"(xdss_pu and sn_mva): {_short(missing_classical)}.")
    if missing_iec:
        rep.add(ERROR, "iec60909", f"{len(missing_iec)} generator(s) lack vn_kv, rdss_ohm or cos_phi, "
                f"which IEC 60909 needs: {_short(missing_iec)}.")

    # --- Elements the classical method does not model in v0.1 ---------------
    for table in UNSUPPORTED_TABLES:
        if table in net and len(net[table]) and "in_service" in net[table]:
            n = int(net[table]["in_service"].sum())
            if n:
                rep.add(ERROR, "classical", f"{n} in-service '{table}' element(s): not modeled by "
                        "the classical method in v0.1 (try --method iec60909).")
    if "switch" in net and len(net.switch):
        n = int(((net.switch["et"] == "b") & net.switch["closed"]).sum())
        if n:
            rep.add(ERROR, "classical", f"{n} closed bus-bus switch(es): not supported by the "
                    "classical method in v0.1 (merge those buses, or try --method iec60909).")

    # --- Connectivity ---------------------------------------------------------
    if len(eg) or len(gens):
        reach = connected_to_source(net, set(live))
        isolated = [b for b in live if b not in reach]
        if isolated:
            rep.add(WARNING, "both", f"{len(isolated)} bus(es) have no path to any source and will "
                    f"be skipped in scans: {_short([bus_label(net, b) for b in isolated])}.")

    # --- Information ------------------------------------------------------------
    n_ibr = sum(int(net[t]["in_service"].sum()) for t in ("sgen", "storage") if t in net and len(net[t]))
    if n_ibr:
        rep.add(INFO, "both", f"{n_ibr} inverter-based resource(s) (sgen/storage) found; their "
                "contribution is excluded from short-circuit MVA, as NERC's SCR definition requires.")
    labels = [bus_label(net, b) for b in live]
    if len(set(labels)) != len(labels):
        rep.add(INFO, "report", "Bus names are not unique, so reports label buses by pandapower index.")
    if "geo" in net.bus.columns and net.bus.loc[live, "geo"].notna().all():
        rep.add(INFO, "report", "All buses have coordinates: the map will use them.")
    else:
        rep.add(INFO, "report", "Not all buses have coordinates: the map will use an automatic layout.")
    if len(live) > MAX_MAP_BUSES:
        rep.add(INFO, "report", f"{len(live)} buses: above the {MAX_MAP_BUSES}-bus limit, so the "
                "report will omit the network map.")
    if len(live) > CLASSICAL_SLOW_ABOVE:
        rep.add(WARNING, "classical", f"{len(live)} buses: the classical method may be slow or run "
                "out of memory at this size in v0.1; IEC 60909 may be faster.")
    return rep


def _name(row, default):
    n = row.get("name")
    if n is None or (isinstance(n, float) and math.isnan(n)) or str(n).strip() == "":
        return default
    return str(n)


def _pos(v):
    try:
        return v is not None and math.isfinite(float(v)) and float(v) > 0
    except (TypeError, ValueError):
        return False


def _nonneg(v):
    try:
        return v is not None and math.isfinite(float(v)) and float(v) >= 0
    except (TypeError, ValueError):
        return False


def _short(items, n=8):
    items = [str(i) for i in items]
    return ", ".join(items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")
