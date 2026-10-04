"""Screening-level interconnection cost for each candidate bus.

For a plant of a given size at each bus, estimates:

1. Weak-grid mitigation: the synchronous condenser needed to raise SCR to a
   target. A condenser at the POI adds short-circuit MVA in parallel with the
   grid, approximately

       added SCMVA = condenser MVA / (X''d + Xt)        (both pu on condenser base)

   so the condenser size needed is

       condenser MVA = max(0, plant MW x target SCR - existing SCMVA) x (X''d + Xt)

   This assumes the condenser is at the POI bus and that the grid and condenser
   impedances are mostly reactive (similar angles), which is typical at
   transmission level.
2. Gen-tie line: user-supplied distance x user-supplied cost per mile.
3. POI substation / switching station: user-supplied cost per bus.

All money values are entered by the user; SCR-Screen ships no cost data.
Not included: network upgrades (thermal, voltage, stability), which are often
the largest interconnection cost and require power flow and queue studies.
Grid-forming inverters are an alternative mitigation that is not costed here.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .metrics import InputError

LIMITATIONS = (
    "Screening-level only. Excludes network upgrades (thermal, voltage, stability), which are "
    "often the largest interconnection cost and need power flow and interconnection-queue "
    "studies. Condenser sizing assumes the condenser is at the POI with mostly reactive "
    "impedances. Grid-forming inverters may mitigate weak-grid conditions at lower cost and "
    "are not costed. All costs are user inputs."
)


@dataclass(frozen=True)
class SiteCost:
    distance_mi: float | None = None
    poi_cost: float | None = None


@dataclass(frozen=True)
class CostInputs:
    plant_mw: float
    target_scr: float
    condenser_xdss_pu: float = 0.20
    condenser_xt_pu: float = 0.10
    condenser_cost_per_mva: float | None = None
    gen_tie_cost_per_mile: float | None = None
    sites: dict[str, SiteCost] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("plant_mw", "target_scr", "condenser_xdss_pu"):
            v = getattr(self, name)
            if not (isinstance(v, (int, float)) and v > 0):
                raise InputError(f"{name} must be greater than zero, got {v!r}.")
        if not (isinstance(self.condenser_xt_pu, (int, float)) and self.condenser_xt_pu >= 0):
            raise InputError(f"condenser_xt_pu must be zero or more, got {self.condenser_xt_pu!r}.")
        for name in ("condenser_cost_per_mva", "gen_tie_cost_per_mile"):
            v = getattr(self, name)
            if v is not None and not (isinstance(v, (int, float)) and v >= 0):
                raise InputError(f"{name} must be zero or more, got {v!r}.")


@dataclass(frozen=True)
class CostRow:
    bus_id: str
    scmva: float
    scr: float
    added_scmva_needed: float
    condenser_mva: float
    condenser_cost: float | None
    gen_tie_mi: float | None
    gen_tie_cost: float | None
    poi_cost: float | None
    total_cost: float | None   # sum of priced parts; None if nothing could be priced
    complete: bool             # False if a needed part has a quantity but no price
    meets_target: bool = True        # SCR already at or above the target SCR
    max_at_target_mw: float = 0.0    # largest plant that meets the target without a condenser
    scr_after: float = 0.0           # SCR with the condenser (= target if one is needed)


def condenser_mva(plant_mw: float, scmva: float, target_scr: float, x_total_pu: float) -> tuple[float, float]:
    """Return (added SCMVA needed, condenser MVA) to bring SCR up to target."""
    need = max(0.0, plant_mw * target_scr - scmva)
    return need, need * x_total_pu


def screen_costs(plants, inputs: CostInputs) -> list[CostRow]:
    """Cost rows for screened plants/buses, cheapest first.

    Args:
        plants: PlantResult rows from a scan (plant_id like "Bus 12", scmva, scr).
        inputs: CostInputs.

    When a site file is given, only the candidate buses listed in it are
    costed (other buses are not candidate sites). Without one, every bus is
    costed for condenser mitigation only.

    Ordering: rows with a total cost first (cheapest first), then the rest by
    condenser MVA and SCR.
    """
    x_total = inputs.condenser_xdss_pu + inputs.condenser_xt_pu
    if inputs.sites:
        plants = [p for p in plants if _key(p.plant_id) in inputs.sites]
    rows = []
    for p in plants:
        need, cmva = condenser_mva(inputs.plant_mw, p.scmva, inputs.target_scr, x_total)
        site = _site_for(inputs.sites, p.plant_id)
        complete = True

        if cmva == 0:
            c_cost = 0.0
        elif inputs.condenser_cost_per_mva is not None:
            c_cost = cmva * inputs.condenser_cost_per_mva
        else:
            c_cost, complete = None, False

        gt_mi = site.distance_mi if site else None
        if gt_mi is None:
            gt_cost = None
        elif inputs.gen_tie_cost_per_mile is not None:
            gt_cost = gt_mi * inputs.gen_tie_cost_per_mile
        else:
            gt_cost, complete = None, False

        poi = site.poi_cost if site else None
        priced = [v for v in (c_cost, gt_cost, poi) if v is not None]
        rows.append(CostRow(p.plant_id, p.scmva, p.scr, need, cmva, c_cost, gt_mi, gt_cost, poi,
                            sum(priced) if priced else None, complete,
                            meets_target=p.scr >= inputs.target_scr,
                            max_at_target_mw=p.scmva / inputs.target_scr,
                            scr_after=inputs.target_scr if cmva > 0 else p.scr))

    rows.sort(key=lambda r: (r.total_cost is None, r.total_cost if r.total_cost is not None else 0,
                             r.condenser_mva, -r.scr))
    return rows


def read_site_costs_csv(path: str | Path) -> dict[str, SiteCost]:
    """Read per-bus site data: columns bus, distance_mi (optional), poi_cost_usd (optional).

    The bus column can hold the bus label as shown in reports ("12") or with
    the prefix ("Bus 12").
    """
    path = Path(path)
    if not path.exists():
        raise InputError(f"Site cost file not found: {path}")
    sites: dict[str, SiteCost] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise InputError(f"{path.name} is empty.")
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        if "bus" not in reader.fieldnames:
            raise InputError(f"{path.name} needs a 'bus' column.")
        for row_no, raw in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            if not any(row.values()):
                continue
            bus = row.get("bus", "")
            if not bus:
                raise InputError(f"Row {row_no}: bus is empty.")
            key = _key(bus)
            if key in sites:
                raise InputError(f"Row {row_no}: bus '{bus}' appears more than once.")
            sites[key] = SiteCost(
                distance_mi=_num(row, "distance_mi", row_no),
                poi_cost=_num(row, "poi_cost_usd", row_no),
            )
    return sites


def write_site_template(bus_ids: list[str], path: str | Path) -> Path:
    """Write a site cost template listing every bus, for the user to fill in."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bus", "distance_mi", "poi_cost_usd"])
        for b in bus_ids:
            w.writerow([b, "", ""])
    return path


def write_cost_csv(rows: list[CostRow], path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()) if rows else ["bus_id"])
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in asdict(r).items()})
    return path


def _key(bus: str) -> str:
    b = bus.strip()
    return b[4:].strip() if b.lower().startswith("bus ") else b


def _site_for(sites: dict[str, SiteCost], plant_id: str) -> SiteCost | None:
    return sites.get(_key(plant_id))


def _num(row, col, row_no):
    text = row.get(col, "")
    if text == "":
        return None
    if "," in text:
        raise InputError(f"Row {row_no}: {col} contains a comma ('{text}'). Use plain numbers, "
                         "e.g. 2500000 or 12.5.")
    try:
        v = float(text.replace("$", ""))
    except ValueError:
        raise InputError(f"Row {row_no}: {col} must be a number, got '{text}'.") from None
    if v < 0:
        raise InputError(f"Row {row_no}: {col} must be zero or more, got {v:g}.")
    return v
