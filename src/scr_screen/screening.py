"""Run a screening: SCR for every plant, WSCR for every group, with metadata.

This is the "engine" that the file readers, the HTML report and the
command-line tool all share, so they always produce identical numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from . import __version__
from .metrics import Plant, RatingBasis, _to_basis, classify, group_wscr, plant_scr
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


@dataclass(frozen=True)
class GroupResult:
    group: str
    plant_ids: list[str]
    total_rating: float
    wscr: float
    flag: str
    min_individual_scr: float


@dataclass
class ScreeningResult:
    basis: str
    thresholds: dict
    source: str
    tool_version: str
    run_utc: str
    plants: list[PlantResult] = field(default_factory=list)
    groups: list[GroupResult] = field(default_factory=list)

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
