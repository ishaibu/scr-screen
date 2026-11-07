"""Run a screening: SCR for every plant, WSCR for every group, with metadata.

This is the "engine" that the file readers, the HTML report and the
command-line tool all share, so they always produce identical numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from . import __version__
from .metrics import InputError, Plant, RatingBasis, _to_basis, classify, group_wscr, plant_scr
from .settings import DEFAULT_THRESHOLDS, Thresholds


@dataclass(frozen=True)
class PlantResult:
    plant_id: str
    poi_name: str
    group: str | None
    scmva: float
    rating: float
    scr: float
    flag: str
    max_rating_no_flag: float  # largest plant (same basis) that would not be flagged weak
    # Network-aware metrics (network scans with the classical method; None otherwise)
    scrif: float | None = None       # SCR with interaction factors, within the plant's group
    escr: float | None = None        # effective SCR (capacitive shunt compensation subtracted)
    n1_scr: float | None = None      # worst single-outage (N-1) SCR
    n1_outage: str | None = None     # the outage that causes it


@dataclass(frozen=True)
class GroupResult:
    group: str
    plant_ids: list[str]
    total_rating: float
    wscr: float
    flag: str
    min_individual_scr: float
    cscr: float | None = None        # composite SCR at the group's POIs tied together
    member_ratings: list[float] | None = None  # each member's rating, when the groups file sets sizes
    member_scrif: list[float] | None = None    # each member's SCRIF (network scans, classical method)


@dataclass
class ScreeningResult:
    basis: str
    thresholds: dict
    source: str
    tool_version: str
    run_utc: str
    plants: list[PlantResult] = field(default_factory=list)
    groups: list[GroupResult] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)  # 0 MW devices left out on the MW basis

    def to_dict(self) -> dict:
        return asdict(self)


def screen(
    plants: Sequence[Plant],
    basis: RatingBasis | str = RatingBasis.MW,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    source: str = "direct input",
    poi_names: dict[str, str] | None = None,
) -> ScreeningResult:
    """Screen a list of plants.

    Args:
        plants: the plants, each with its SCMVA (without IBR contribution).
        basis: "MW" (default) or "MVA".
        thresholds: flag bands.
        source: short description of where SCMVA values came from, shown in
            reports (e.g. "direct input" or "network model, classical method").
        poi_names: optional {plant_id: POI name} for display.
    """
    basis = _to_basis(basis)
    poi_names = poi_names or {}
    result = ScreeningResult(
        basis=basis.value,
        thresholds=asdict(thresholds),
        source=source,
        tool_version=__version__,
        run_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    if basis is RatingBasis.MW:
        # Devices with no active power (rating_mw = 0, e.g. STATCOMs) count only on the MVA basis.
        result.excluded = [p.plant_id for p in plants if p.rating_mw == 0]
        plants = [p for p in plants if p.rating_mw > 0]
        if not plants:
            raise InputError("Every plant has rating_mw = 0; use the MVA basis (--basis MVA).")

    for p in plants:
        value = plant_scr(p, basis)
        result.plants.append(PlantResult(
            plant_id=p.plant_id,
            poi_name=poi_names.get(p.plant_id, ""),
            group=p.group,
            scmva=p.scmva,
            rating=p.rating(basis),
            scr=value,
            flag=classify(value, thresholds).value,
            max_rating_no_flag=p.scmva / thresholds.weak_below,
        ))

    groups: dict[str, list[Plant]] = {}
    for p in plants:
        if p.group:
            groups.setdefault(p.group, []).append(p)
    for name, members in groups.items():
        value = group_wscr(members, basis)
        result.groups.append(GroupResult(
            group=name,
            plant_ids=[m.plant_id for m in members],
            total_rating=sum(m.rating(basis) for m in members),
            wscr=value,
            flag=classify(value, thresholds).value,
            min_individual_scr=min(plant_scr(m, basis) for m in members),
        ))
    return result
