"""Read plant data from CSV, and write screening results to CSV or JSON.

Input CSV columns (header row required; column order does not matter):
    plant_id    required  text label, unique
    scmva       required  short-circuit MVA at the POI, WITHOUT IBR contribution
    rating_mw   required  plant rating in MW
    rating_mva  optional  plant rating in MVA (needed only for the MVA basis)
    group       optional  plants sharing a group are combined in WSCR
    poi_name    optional  display name of the point of interconnection

Files saved from Excel as "CSV UTF-8" are supported.
"""

from __future__ import annotations

import csv
import math
import json
from pathlib import Path

from .metrics import InputError, Plant
from .screening import ScreeningResult

REQUIRED = ("plant_id", "scmva", "rating_mw")
OPTIONAL = ("rating_mva", "inverters", "inverter_mva", "power_factor", "group", "poi_name")

TEMPLATE_ROWS = [
    # Illustrative values only (design-spec test cases), not a real system.
    {"plant_id": "PV-A", "poi_name": "Bus 101", "scmva": "1000", "rating_mw": "200",
     "rating_mva": "210", "group": "G1"},
    {"plant_id": "BESS-B", "poi_name": "Bus 102", "scmva": "600", "rating_mw": "100",
     "rating_mva": "105", "group": "G1"},
    {"plant_id": "Wind-C", "poi_name": "Bus 205", "scmva": "485.86", "rating_mw": "100",
     "rating_mva": "", "group": ""},
]


def read_plants_csv(path: str | Path) -> tuple[list[Plant], dict[str, str]]:
    """Read plants from a CSV file.

    Returns:
        (plants, poi_names) where poi_names maps plant_id to its POI name.

    Raises:
        InputError with the row number and column for any problem.
    """
    plants, poi_names, _ = read_plants_csv_detail(path)
    return plants, poi_names


def read_plants_csv_detail(path: str | Path):
    """Like read_plants_csv, plus where each plant's MVA rating came from.

    A row's MVA rating can be given ONE way: rating_mva (nameplate); inverters
    and inverter_mva (nameplate = inverters × inverter_mva); or power_factor (an
    ESTIMATE, MW ÷ power factor). All are optional; the MW basis does not use them.

    Returns:
        (plants, poi_names, mva_sources) with mva_sources = {plant_id: text}.
    """
    from .metrics import mva_source_text, plant_mva

    path = Path(path)
    if not path.exists():
        raise InputError(f"Input file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise InputError(f"{path.name} is empty.")
        headers = [h.strip().lower() for h in reader.fieldnames]
        missing = [c for c in REQUIRED if c not in headers]
        if missing:
            raise InputError(
                f"{path.name} is missing required column(s): {', '.join(missing)}. "
                f"Required: {', '.join(REQUIRED)}."
            )
        reader.fieldnames = headers

        plants, poi_names, seen, sources = [], {}, set(), {}
        for row_no, raw in enumerate(reader, start=2):  # row 1 is the header
            row = {k: (v or "").strip() for k, v in raw.items() if k is not None}
            if not any(row.values()):
                continue  # skip blank lines
            pid = row.get("plant_id", "")
            if not pid:
                raise InputError(f"Row {row_no}: plant_id is empty.")
            if pid in seen:
                raise InputError(f"Row {row_no}: plant_id '{pid}' appears more than once.")
            seen.add(pid)

            mw = _number(row, "rating_mw", row_no, required=True)
            inv = _number(row, "inverters", row_no, required=False)
            inv_mva = _number(row, "inverter_mva", row_no, required=False)
            pf = _number(row, "power_factor", row_no, required=False)
            try:
                mva, kind = plant_mva(mw, mva=_number(row, "rating_mva", row_no, required=False),
                                      inverters=inv, inverter_mva=inv_mva, power_factor=pf,
                                      where=f"plant '{pid}'")
            except InputError as e:
                raise InputError(f"Row {row_no}: {e}") from None
            if mva is not None:
                sources[pid] = mva_source_text(mw, mva, kind, inv, inv_mva, pf)
            plant = Plant(
                plant_id=pid,
                scmva=_number(row, "scmva", row_no, required=True),
                rating_mw=mw,
                rating_mva=mva,
                group=row.get("group") or None,
            )
            plants.append(plant)
            poi_names[pid] = row.get("poi_name", "")

    if not plants:
        raise InputError(f"{path.name} has a header but no plant rows.")
    return plants, poi_names, sources


def read_bus_groups_csv(path: str | Path) -> dict[str, str]:
    """Read bus groups for a network scan: columns bus, group.

    Buses that share a group are screened together with WSCR, each with a
    plant of the scan's plant size. The bus column can hold the bus label as
    shown in reports ("12") or with the prefix ("Bus 12"). A bus can belong
    to one group only.

    Returns:
        {bus label: group name}
    """
    return {bus: g for bus, (g, _, _) in read_bus_groups_full(path).items()}


def read_bus_groups_full(path: str | Path) -> dict[str, tuple[str, float | None, float | None]]:
    """Read a groups file, including optional per-bus sizes.

    Required columns: bus, group. Optional columns: mw, mva. When a row gives
    both mw and mva, that member keeps this fixed size (for example an existing
    or queued plant, or a STATCOM with mw = 0) instead of the scan's plant size.
    A row must give both or neither.

    Returns:
        {bus label: (group name, mw or None, mva or None)}
    """
    path = Path(path)
    if not path.exists():
        raise InputError(f"Groups file not found: {path}")
    groups: dict[str, tuple[str, float | None, float | None]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise InputError(f"{path.name} is empty.")
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        missing = [c for c in ("bus", "group") if c not in reader.fieldnames]
        if missing:
            raise InputError(f"{path.name} is missing column(s): {', '.join(missing)}. "
                             "Required: bus, group.")
        for row_no, raw in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            if not any(row.values()):
                continue
            bus, group = row.get("bus", ""), row.get("group", "")
            if not bus:
                raise InputError(f"Row {row_no}: bus is empty.")
            if not group:
                raise InputError(f"Row {row_no}: group is empty for bus '{bus}'.")
            key = bus[4:].strip() if bus.lower().startswith("bus ") else bus
            if key in groups:
                raise InputError(f"Row {row_no}: bus '{bus}' appears more than once "
                                 "(a bus can belong to one group only).")
            mw = _number(row, "mw", row_no, required=False)
            mva = _number(row, "mva", row_no, required=False)
            if (mw is None) != (mva is None):
                raise InputError(f"Row {row_no}: give both mw and mva for bus '{bus}', or leave both empty "
                                 "to use the scan's plant size.")
            if mw is not None:
                if not (math.isfinite(mw) and mw >= 0):
                    raise InputError(f"Row {row_no}: mw must be 0 or more, got {mw:g}.")
                if not (math.isfinite(mva) and mva > 0):
                    raise InputError(f"Row {row_no}: mva must be greater than zero, got {mva:g}.")
            groups[key] = (group, mw, mva)
    if not groups:
        raise InputError(f"{path.name} has a header but no rows.")
    return groups


def write_results_json(result: ScreeningResult, path: str | Path) -> Path:
    """Write the full result (metadata, plants, groups) as JSON."""
    path = Path(path)
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return path


def write_results_csv(result: ScreeningResult, path: str | Path) -> Path:
    """Write one row per plant and one row per group, for spreadsheets."""
    path = Path(path)
    cols = ["type", "id", "group", "poi_name", "scmva", f"rating_{result.basis.lower()}",
            "ratio", "flag", f"max_{result.basis.lower()}_no_flag",
            "method_source", "tool_version", "run_utc", "scrif", "escr", "n1_ratio", "n1_outage", "cscr"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in result.plants:
            w.writerow(["plant (SCR)", p.plant_id, p.group or "", p.poi_name,
                        f"{p.scmva:.2f}", f"{p.rating:.2f}", f"{p.scr:.3f}", p.flag,
                        f"{p.max_rating_no_flag:.1f}",
                        result.source, result.tool_version, result.run_utc,
                        _f3(p.scrif), _f3(p.escr), _f3(p.n1_scr), p.n1_outage or "", ""])
        for g in result.groups:
            w.writerow(["group (WSCR)", g.group, g.group, "; ".join(g.plant_ids), "",
                        f"{g.total_rating:.2f}", f"{g.wscr:.3f}", g.flag, "",
                        result.source, result.tool_version, result.run_utc, "", "", "", "", _f3(g.cscr)])
    return path


def _f3(v) -> str:
    return "" if v is None else f"{v:.3f}"


def write_template_csv(path: str | Path) -> Path:
    """Write an input template with illustrative rows."""
    path = Path(path)
    cols = ["plant_id", "poi_name", "scmva", "rating_mw", "rating_mva", "group"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(TEMPLATE_ROWS)
    return path


def _number(row: dict, col: str, row_no: int, required: bool) -> float | None:
    text = row.get(col, "")
    if text == "":
        if required:
            raise InputError(f"Row {row_no}: {col} is empty.")
        return None
    if "," in text:
        # Refuse rather than guess: "1,000" (thousands) vs "485,86" (decimal comma).
        raise InputError(
            f"Row {row_no}: {col} contains a comma ('{text}'). Use a dot for "
            "decimals and no thousands separators, e.g. 1000 or 485.86."
        )
    try:
        return float(text)
    except ValueError:
        raise InputError(f"Row {row_no}: {col} must be a number, got '{text}'.") from None
