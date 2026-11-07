"""EMT study triage at points of interconnection (POIs).

NERC's Reliability Guideline *Recommended Practices for Performing EMT System
Studies for Inverter-Based Resources* (December 2024), Chapter 1, lists
situations in which EMT studies should be considered, and says that if any one
of them applies, EMT studies should be considered. It also says that a high
level of system strength alone should not rule out the need for EMT studies.

SCR-Screen checks the situations it can find in a network model and asks the
user about the rest:

Found in the model (classical flat-start Z-bus, 100 MVA base)
    * low system strength: SCR (and ESCR where capacitor banks exist) with the
      network intact, under the worst single outage (N-1) and, when generators
      are named with --gen-out, in a minimum-generation case; WSCR, CSCR and
      SCRIF for grouped POIs (intact);
    * other IBRs nearby: in-service sgen and storage elements whose pair
      interaction factor with the POI, max(IF_ij, IF_ji), is at least the
      proximity threshold (default 0.5);
    * series compensation (lines with negative series reactance), FACTS (svc,
      ssc, tcsc tables) and HVdc (vsc, dcline tables), and their proximity by
      the same interaction factor.

Asked of the user (a --poi-info file; yes / no / unknown)
    the rest of NERC's Chapter 1 list: poor positive-sequence (RMS) stability
    results ("Stability Criteria"); a system event that positive-sequence
    models cannot reproduce ("EMT Studies Following System Events"); and, under
    "System Topology or Conditions with Stability Risks", pre-existing
    oscillation or oscillatory modes, series-compensated lines, FACTS devices,
    HVdc lines, high IBR penetration level, specialized protection schemes such
    as RAS, distance-relay-protected lines with declining fault current levels,
    a trend of decreasing system strength, and a trend of increasing RoCoF or
    decreasing inertia. Also an optional OEM minimum SCR.

Priority (SCR-Screen's ordering of the work; NERC does not rank the situations)
    1  any strength metric below the very-weak threshold in any condition; or
       series compensation, FACTS or HVdc nearby (found or answered yes); or a
       system event that positive-sequence models cannot reproduce (answered
       yes); or the lowest SCR below the OEM minimum SCR.
    2  any strength metric below the weak threshold; or other IBRs nearby; or any
       other situation answered yes.
    3  no screening trigger found.

Thevenin data at each POI and condition
    Z_th = Z_ii (pu, 100 MVA base); ohms = Z_th × kV² / 100;
    SCMVA = 100 / |Z_th|; I_sc = SCMVA / (√3 × kV) kA, all at 1.0 pu pre-fault
    voltage with inverter-based resources excluded (classical method).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .classical import S_BASE_MVA, ZBus
from .metrics import InputError
from .settings import Thresholds

NERC_EMT_2024 = ("NERC, Reliability Guideline: Recommended Practices for Performing EMT System Studies "
                 "for Inverter-Based Resources, December 2024, Chapter 1")
NERC_RULE = ("NERC (2024, Chapter 1): if any one of the listed situations applies, EMT studies should "
             "be considered.")
NERC_NOT_RULE_OUT = ("NERC (2024, Chapter 1): “having a high level of system strength alone should not "
                     "rule out the need for EMT studies.”")
LEVEL_TEXT = {
    1: "Priority 1: EMT study recommended (high priority)",
    2: "Priority 2: EMT study should be considered",
    3: "Priority 3: no screening trigger found",
}
PRIORITY_NOTE = ("Priorities order the work; they are SCR-Screen's judgment, not NERC's. NERC lists the "
                 "situations without ranking them.")
PRIORITY_RULES = ("Priority 1: any strength metric below the very-weak threshold in any condition; series "
                  "compensation, FACTS or HVdc nearby; a system event that positive-sequence models cannot "
                  "reproduce; or the lowest SCR below the OEM minimum SCR. Priority 2: any strength metric below "
                  "the weak threshold; other IBRs nearby; or any other situation answered yes. Priority 3: no "
                  "screening trigger found.")

# User-answered situations: field -> (description, priority if "yes").
# Descriptions follow the wording of NERC (2024), Chapter 1.
USER_FIELDS: dict[str, tuple[str, int]] = {
    "rms_stability_concerns": ("Positive-sequence (RMS) stability studies show poor performance against the "
                               "criteria (Stability Criteria)", 2),
    "unexplained_system_event": ("A system event that positive-sequence models cannot reproduce "
                                 "(EMT Studies Following System Events)", 1),
    "pre_existing_oscillation": ("Pre-existing oscillation or oscillatory modes", 2),
    "series_compensation": ("Series-compensated lines nearby", 1),
    "facts_nearby": ("Flexible ac transmission system (FACTS) devices nearby", 1),
    "hvdc_nearby": ("HVdc lines nearby", 1),
    "high_ibr_penetration": ("High IBR penetration level", 2),
    "ras": ("Specialized protection schemes, such as RAS", 2),
    "distance_relays_declining_fault_current": ("Transmission lines protected by distance relays, with declining "
                                                "fault current levels", 2),
    "decreasing_strength_trend": ("A trend of decreasing system strength", 2),
    "rocof_inertia_trend": ("A trend of increasing rate of change of frequency (RoCoF) or decreasing inertia", 2),
}
ANSWERS = {"yes": "yes", "y": "yes", "no": "no", "n": "no", "unknown": "unknown", "": "unknown", "?": "unknown"}
# Device kinds found in the model -> (NERC situation, priority)
DEVICE_LEVEL = {"series compensation": 1, "FACTS": 1, "HVdc": 1}
NOT_MODELED = ("ssc", "vsc", "dcline")  # taken out of service for the strength calculation
_TABLE_DEVICE = {"svc": ("FACTS", "SVC"), "ssc": ("FACTS", "STATCOM (SSC)"), "tcsc": ("FACTS", "TCSC"),
                 "vsc": ("HVdc", "VSC converter"), "dcline": ("HVdc", "dc line")}


# --- Data ---------------------------------------------------------------------

@dataclass(frozen=True)
class Thevenin:
    """Thevenin equivalent at a POI in one condition (classical, 1.0 pu, IBRs excluded)."""
    condition: str          # "intact", "N-1" or "minimum generation"
    outage: str             # outage or case description ("" when intact)
    kv: float
    r_pu: float
    x_pu: float
    z_pu: float
    x_over_r: float | None  # None when R = 0
    r_ohm: float
    x_ohm: float
    z_ohm: float
    scmva: float
    isc_ka: float
    scr: float
    escr: float | None      # None when no capacitor bank is at the bus


@dataclass(frozen=True)
class Device:
    kind: str               # "series compensation", "FACTS" or "HVdc"
    what: str               # e.g. "SVC", "line 12 (negative series reactance)"
    name: str
    buses: tuple[int, ...]


@dataclass(frozen=True)
class Nearby:
    """A device or existing IBR and its interaction with a POI."""
    kind: str
    name: str
    where: str              # bus label(s)
    interaction: float | None   # max(IF_ij, IF_ji); None if its bus is isolated
    near: bool
    p_mw: float | None = None
    sn_mva: float | None = None


@dataclass(frozen=True)
class Trigger:
    level: int
    situation: str          # NERC situation it belongs to
    detail: str
    source: str             # "model", "user" or "OEM"


@dataclass
class PoiTriage:
    poi_id: str
    bus: int
    kv: float
    rating: float
    basis: str
    conditions: list[Thevenin]
    group: str | None = None
    wscr: float | None = None
    cscr: float | None = None
    scrif: float | None = None
    nearby_ibrs: list[Nearby] = field(default_factory=list)
    devices: list[Nearby] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    oem_min_scr: float | None = None
    triggers: list[Trigger] = field(default_factory=list)
    level: int = 3

    @property
    def level_text(self) -> str:
        return LEVEL_TEXT[self.level]

    @property
    def lowest_scr(self) -> float:
        return min(c.scr for c in self.conditions)

    @property
    def unknown(self) -> list[str]:
        return [USER_FIELDS[k][0] for k in USER_FIELDS if self.answers.get(k, "unknown") == "unknown"]


@dataclass(frozen=True)
class PoiInfo:
    answers: dict[str, str]
    oem_min_scr: float | None


# --- Model checks ---------------------------------------------------------------

def detect_devices(net) -> list[Device]:
    """Series compensation, FACTS and HVdc devices in service in the model."""
    out: list[Device] = []
    for idx, ln in net.line.iterrows():
        if ln["in_service"] and float(ln["x_ohm_per_km"]) < 0:
            out.append(Device("series compensation", f"line {idx} (negative series reactance)",
                              _name(ln.get("name"), f"line {idx}"), (int(ln["from_bus"]), int(ln["to_bus"]))))
    for table, (kind, what) in _TABLE_DEVICE.items():
        if table not in net or len(net[table]) == 0:
            continue
        for idx, row in net[table].iterrows():
            if "in_service" in row and not bool(row["in_service"]):
                continue
            if "bus" in row and table in ("svc", "ssc", "vsc"):
                buses = (int(row["bus"]),)
            else:
                buses = (int(row["from_bus"]), int(row["to_bus"]))
            k = "series compensation" if table == "tcsc" else kind
            out.append(Device(k, what, _name(row.get("name"), f"{table} {idx}"), buses))
    return out


def prepare_network(net) -> list[str]:
    """Make the network computable by the classical method, in place. Returns notes.

    HVdc converters (vsc), dc lines (dcline) and STATCOMs (ssc) are taken out of
    service for the short-circuit calculation: they are converter-interfaced and,
    like other IBRs, are excluded from the short-circuit MVA. A TCSC is a series
    element that carries the line, so removing it would change the network; it is
    refused with a clear message instead.
    """
    if "tcsc" in net and len(net.tcsc) and bool(net.tcsc["in_service"].any()):
        raise InputError("The network contains an in-service TCSC, which the classical method does not model. "
                         "Replace it with a line of its equivalent series impedance for screening, and answer "
                         "series_compensation = yes for nearby POIs in the --poi-info file.")
    notes = []
    for table in NOT_MODELED:
        if table in net and len(net[table]) and bool(net[table]["in_service"].any()):
            n = int(net[table]["in_service"].sum())
            net[table]["in_service"] = False
            notes.append(f"{n} in-service '{table}' element(s) were left out of the short-circuit calculation "
                         "(converter-interfaced, so excluded like other IBRs); they are still listed for EMT triage.")
    return notes


def existing_ibrs(net) -> list[tuple[str, int, float, float | None]]:
    """In-service sgen and storage elements: (name, bus, p_mw, sn_mva)."""
    out = []
    for table in ("sgen", "storage"):
        if table not in net or len(net[table]) == 0:
            continue
        for idx, row in net[table].iterrows():
            if not bool(row["in_service"]):
                continue
            sn = row.get("sn_mva", np.nan)
            sn = float(sn) if sn is not None and np.isfinite(sn) and float(sn) > 0 else None
            out.append((_name(row.get("name"), f"{table} {idx}"), int(row["bus"]), float(row["p_mw"]), sn))
    return out


def pair_interaction(zb: ZBus, i: int, j: int) -> float | None:
    """max(IF_ij, IF_ji) = max(|Z_ij/Z_jj|, |Z_ji/Z_ii|); None if either bus is not in the Z-bus."""
    if i not in zb.pos or j not in zb.pos:
        return None
    if i == j:
        return 1.0
    a, b = zb.pos[i], zb.pos[j]
    return float(max(abs(zb.z[a, b] / zb.z[b, b]), abs(zb.z[b, a] / zb.z[a, a])))


def thevenin(condition: str, outage: str, z: complex, kv: float, rating: float, qc: float = 0.0) -> Thevenin:
    zmag = abs(z)
    if not (math.isfinite(zmag) and zmag > 0):
        raise InputError("A Thevenin impedance could not be computed (no path to a source).")
    base = kv ** 2 / S_BASE_MVA
    scmva = S_BASE_MVA / zmag
    r, x = float(z.real), float(z.imag)
    return Thevenin(condition=condition, outage=outage, kv=kv, r_pu=r, x_pu=x, z_pu=zmag,
                    x_over_r=(x / r) if r > 0 else None, r_ohm=r * base, x_ohm=x * base, z_ohm=zmag * base,
                    scmva=scmva, isc_ka=scmva / (math.sqrt(3) * kv), scr=scmva / rating,
                    escr=(scmva - qc) / rating if qc > 0 else None)


# --- User information ------------------------------------------------------------

def read_poi_info(path: str | Path) -> dict[str, PoiInfo]:
    """Read a --poi-info CSV: column poi, any of USER_FIELDS (yes / no / unknown), optional oem_min_scr.

    A row with poi = all sets the answers for every POI not listed on its own row.
    Returns {poi label (without 'Bus '): PoiInfo}.
    """
    path = Path(path)
    if not path.exists():
        raise InputError(f"POI information file not found: {path}")
    out: dict[str, PoiInfo] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise InputError(f"{path.name} is empty.")
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        if "poi" not in reader.fieldnames:
            raise InputError(f"{path.name} needs a 'poi' column (the bus label, or 'all').")
        known = set(USER_FIELDS) | {"poi", "oem_min_scr", "notes"}
        extra = [h for h in reader.fieldnames if h and h not in known]
        if extra:
            raise InputError(f"{path.name}: unknown column(s) {', '.join(extra)}. Allowed: poi, "
                             + ", ".join(USER_FIELDS) + ", oem_min_scr, notes.")
        for row_no, raw in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            if not any(row.values()):
                continue
            poi = row.get("poi", "")
            if not poi:
                raise InputError(f"Row {row_no}: poi is empty.")
            key = poi[4:].strip() if poi.lower().startswith("bus ") else poi
            key = "all" if key.lower() == "all" else key
            if key in out:
                raise InputError(f"Row {row_no}: poi '{poi}' appears more than once.")
            answers = {}
            for fld in USER_FIELDS:
                text = row.get(fld, "").lower()
                if text not in ANSWERS:
                    raise InputError(f"Row {row_no}: {fld} must be yes, no or unknown (or blank), got '{row[fld]}'.")
                answers[fld] = ANSWERS[text]
            oem = row.get("oem_min_scr", "")
            value = None
            if oem:
                try:
                    value = float(oem)
                except ValueError:
                    raise InputError(f"Row {row_no}: oem_min_scr must be a number, got '{oem}'.") from None
                if not (math.isfinite(value) and value > 0):
                    raise InputError(f"Row {row_no}: oem_min_scr must be greater than zero, got {oem}.")
            out[key] = PoiInfo(answers, value)
    return out


def info_for(info: dict[str, PoiInfo], label: str) -> PoiInfo | None:
    return info.get(label, info.get("all"))


# --- Triggers ------------------------------------------------------------------

def metric_triggers(values: list[tuple[str, float]], thresholds: Thresholds) -> list[Trigger]:
    """Low system strength triggers from (description, value) pairs."""
    out = []
    vw, wk = thresholds.very_weak_below, thresholds.weak_below
    for text, v in values:
        if v < vw:
            out.append(Trigger(1, "Low system strength", f"{text} {v:.3f} is below the very-weak threshold {vw:g}",
                               "model"))
        elif v < wk:
            out.append(Trigger(2, "Low system strength", f"{text} {v:.3f} is below the weak threshold {wk:g}",
                               "model"))
    return out


def fixed_triggers(ibrs: list[Nearby], devices: list[Nearby], pinfo: PoiInfo | None) -> list[Trigger]:
    """Triggers that do not depend on the plant size: nearby IBRs and devices, and user answers."""
    out = []
    near_ibr = [n for n in ibrs if n.near]
    if near_ibr:
        out.append(Trigger(2, "Other IBRs nearby", "existing IBR(s) electrically close: "
                           + "; ".join(f"{n.name} at {n.where} (interaction {n.interaction:.2f})" for n in near_ibr),
                           "model"))
    for d in devices:
        if d.near:
            out.append(Trigger(DEVICE_LEVEL[d.kind], _situation(d.kind),
                               f"{d.name} ({d.kind}) at {d.where}, interaction {d.interaction:.2f}", "model"))
    if pinfo:
        for fld, (text, lvl) in USER_FIELDS.items():
            if pinfo.answers.get(fld) == "yes":
                out.append(Trigger(lvl, text, "answered yes in the POI information file", "user"))
    return out


def oem_trigger(lowest_scr: float, oem: float | None) -> list[Trigger]:
    if oem is not None and lowest_scr < oem:
        return [Trigger(1, "Below the equipment's minimum SCR",
                        f"lowest SCR {lowest_scr:.3f} is below the OEM minimum SCR {oem:g}", "OEM")]
    return []


def level_of(triggers: list[Trigger]) -> int:
    return min((t.level for t in triggers), default=3)


def _situation(kind: str) -> str:
    return {"series compensation": "Series-compensated lines nearby",
            "FACTS": "Flexible ac transmission system (FACTS) devices nearby", "HVdc": "HVdc lines nearby"}[kind]


# --- Proximity ---------------------------------------------------------------------

def proximity(zb: ZBus, bus: int, ibrs, devices: list[Device], label, threshold: float
              ) -> tuple[list[Nearby], list[Nearby]]:
    """Existing IBRs and devices with their interaction with `bus`, strongest first."""
    out_i = []
    for name, b, p, sn in ibrs:
        v = pair_interaction(zb, bus, b)
        out_i.append(Nearby("IBR", name, label(b), v, v is not None and v >= threshold, p, sn))
    out_d = []
    for d in devices:
        vals = [v for v in (pair_interaction(zb, bus, b) for b in d.buses) if v is not None]
        v = max(vals) if vals else None
        out_d.append(Nearby(d.kind, f"{d.what} '{d.name}'", "–".join(label(b) for b in d.buses), v,
                            v is not None and v >= threshold))
    key = lambda n: -(n.interaction if n.interaction is not None else -1)  # noqa: E731
    return sorted(out_i, key=key), sorted(out_d, key=key)


def _name(value, default: str) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return default
    text = str(value).strip()
    return text if text and text.lower() != "nan" else default


# --- Assembly ---------------------------------------------------------------------

def triage_poi(poi_id: str, bus: int, kv: float, rating: float, basis: str, conditions: list[Thevenin],
               thresholds: Thresholds, ibrs: list[Nearby], devices: list[Nearby], pinfo: PoiInfo | None,
               group: str | None = None, wscr: float | None = None, cscr: float | None = None,
               scrif: float | None = None) -> PoiTriage:
    """Put one POI's data together and set its triggers and priority."""
    values = []
    for c in conditions:
        tag = c.condition + (f", {c.outage}" if c.outage else "")
        values.append((f"SCR ({tag})", c.scr))
        if c.escr is not None:
            values.append((f"ESCR ({tag})", c.escr))
    for name, v in (("group WSCR", wscr), ("group CSCR", cscr), ("SCRIF", scrif)):
        if v is not None:
            values.append((f"{name} (intact)", v))
    trig = metric_triggers(values, thresholds)
    trig += oem_trigger(min(c.scr for c in conditions), pinfo.oem_min_scr if pinfo else None)
    trig += fixed_triggers(ibrs, devices, pinfo)
    return PoiTriage(poi_id=poi_id, bus=bus, kv=kv, rating=rating, basis=basis, conditions=conditions,
                     group=group, wscr=wscr, cscr=cscr, scrif=scrif, nearby_ibrs=ibrs, devices=devices,
                     answers=dict(pinfo.answers) if pinfo else {k: "unknown" for k in USER_FIELDS},
                     oem_min_scr=pinfo.oem_min_scr if pinfo else None, triggers=trig, level=level_of(trig))
