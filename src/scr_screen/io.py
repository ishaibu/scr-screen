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
import json
from pathlib import Path

from .metrics import InputError, Plant
from .screening import ScreeningResult

REQUIRED = ("plant_id", "scmva", "rating_mw")
OPTIONAL = ("rating_mva", "group", "poi_name")

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

        plants, poi_names, seen = [], {}, set()
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

            plant = Plant(
                plant_id=pid,
                scmva=_number(row, "scmva", row_no, required=True),
                rating_mw=_number(row, "rating_mw", row_no, required=True),
                rating_mva=_number(row, "rating_mva", row_no, required=False),
                group=row.get("group") or None,
            )
            plants.append(plant)
            poi_names[pid] = row.get("poi_name", "")

    if not plants:
        raise InputError(f"{path.name} has a header but no plant rows.")
    return plants, poi_names


def write_results_json(result: ScreeningResult, path: str | Path) -> Path:
    """Write the full result (metadata, plants, groups) as JSON."""
    path = Path(path)
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return path


def write_results_csv(result: ScreeningResult, path: str | Path) -> Path:
    """Write one row per plant and one row per group, for spreadsheets."""
    path = Path(path)
    cols = ["type", "id", "group", "poi_name", "scmva", f"rating_{result.basis.lower()}",
            "ratio", "flag", "method_source", "tool_version", "run_utc"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in result.plants:
            w.writerow(["plant (SCR)", p.plant_id, p.group or "", p.poi_name,
                        f"{p.scmva:.2f}", f"{p.rating:.2f}", f"{p.scr:.3f}", p.flag,
                        result.source, result.tool_version, result.run_utc])
        for g in result.groups:
            w.writerow(["group (WSCR)", g.group, g.group, "; ".join(g.plant_ids), "",
                        f"{g.total_rating:.2f}", f"{g.wscr:.3f}", g.flag,
                        result.source, result.tool_version, result.run_utc])
    return path


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
