"""Short-circuit ratio metrics for screening inverter-based resources (IBRs).

This module contains only the math. It does not calculate short-circuit MVA
itself; that comes from the user (direct mode) or from ``network.py``
(network mode). Keeping the math separate lets every formula be checked by
hand and tested in isolation.

References:
    NERC, "Integrating Inverter-Based Resources into Low Short Circuit
    Strength Systems," Reliability Guideline, Dec 2017.
    NERC, "Short-Circuit Modeling and System Strength," White Paper, Feb 2018.
    Zhang et al., "Evaluating system strength for large-scale wind plant
    integration," IEEE PES General Meeting, 2014 (origin of WSCR).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .settings import DEFAULT_THRESHOLDS, Thresholds


class InputError(ValueError):
    """Raised when an input value is missing, non-numeric, or out of range."""


class RatingBasis(str, Enum):
    """Which plant rating to divide by. MW is the default, per NERC."""

    MW = "MW"
    MVA = "MVA"


class Flag(str, Enum):
    """Screening flag for an SCR or WSCR value."""

    VERY_WEAK = "very weak"
    WEAK = "weak"
    NONE = "none"


@dataclass(frozen=True)
class Plant:
    """One inverter-based resource at its point of interconnection (POI).

    Attributes:
        plant_id: user label, e.g. "PV-A".
        scmva: three-phase short-circuit MVA at the POI, WITHOUT the
            contribution of inverter-based resources.
        rating_mw: plant rating in MW (always required).
        rating_mva: plant rating in MVA (optional; needed only for the MVA basis).
        group: optional label; plants sharing a group are combined in WSCR.
    """

    plant_id: str
    scmva: float
    rating_mw: float
    rating_mva: float | None = None
    group: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plant_id, str) or not self.plant_id.strip():
            raise InputError("plant_id must be a non-empty text label.")
        _check_positive(self.scmva, f"scmva for plant '{self.plant_id}'")
        _check_positive(self.rating_mw, f"rating_mw for plant '{self.plant_id}'")
        if self.rating_mva is not None:
            _check_positive(self.rating_mva, f"rating_mva for plant '{self.plant_id}'")

    def rating(self, basis: RatingBasis | str = RatingBasis.MW) -> float:
        """Return the plant rating on the requested basis (MW or MVA)."""
        basis = _to_basis(basis)
        if basis is RatingBasis.MW:
            return self.rating_mw
        if self.rating_mva is None:
            raise InputError(
                f"Plant '{self.plant_id}' has no rating_mva, so the MVA basis "
                "cannot be used. Provide rating_mva or use the MW basis."
            )
        return self.rating_mva


# ---------------------------------------------------------------------------
# Core formulas
# ---------------------------------------------------------------------------

def scr(scmva: float, rating: float) -> float:
    """Short-circuit ratio at a single POI.

        SCR = SCMVA / P_rated

    Args:
        scmva: short-circuit MVA at the POI, without IBR contribution.
        rating: plant rating (MW by default, or MVA).

    Returns:
        The SCR value.
    """
    _check_positive(scmva, "scmva")
    _check_positive(rating, "rating")
    return scmva / rating


def wscr(scmva: Sequence[float], ratings: Sequence[float]) -> float:
    """Weighted short-circuit ratio for plants assumed fully interacting.

        WSCR = sum(SCMVA_i * P_i) / (sum(P_i))**2

    Args:
        scmva: short-circuit MVA at each plant's POI, without IBR contribution.
        ratings: each plant's rating (MW by default, or MVA), same order.

    Returns:
        The WSCR value.
    """
    scmva = list(scmva)
    ratings = list(ratings)
    if not scmva:
        raise InputError("WSCR needs at least one plant.")
    if len(scmva) != len(ratings):
        raise InputError(
            f"WSCR needs one rating per SCMVA value (got {len(scmva)} SCMVA "
            f"values and {len(ratings)} ratings)."
        )
    for i, (s, p) in enumerate(zip(scmva, ratings), start=1):
        _check_positive(s, f"scmva for plant {i}")
        _check_positive(p, f"rating for plant {i}")
    numerator = sum(s * p for s, p in zip(scmva, ratings))
    denominator = sum(ratings) ** 2
    return numerator / denominator


def classify(value: float, thresholds: Thresholds = DEFAULT_THRESHOLDS) -> Flag:
    """Assign a screening flag to an SCR or WSCR value.

    With default thresholds: below 2 is "very weak", 2 to below 3 is "weak",
    and 3 or above is "none" (not flagged).
    """
    _check_positive(value, "value")
    if value < thresholds.very_weak_below:
        return Flag.VERY_WEAK
    if value < thresholds.weak_below:
        return Flag.WEAK
    return Flag.NONE


# ---------------------------------------------------------------------------
# Plant-level helpers
# ---------------------------------------------------------------------------

def plant_scr(plant: Plant, basis: RatingBasis | str = RatingBasis.MW) -> float:
    """SCR for one plant on the chosen rating basis."""
    return scr(plant.scmva, plant.rating(basis))


def group_wscr(plants: Sequence[Plant], basis: RatingBasis | str = RatingBasis.MW) -> float:
    """WSCR for a set of plants on the chosen rating basis."""
    plants = list(plants)
    if not plants:
        raise InputError("WSCR needs at least one plant.")
    return wscr([p.scmva for p in plants], [p.rating(basis) for p in plants])


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _check_positive(value: object, name: str) -> None:
    """Raise InputError unless value is a positive, finite number."""
    if value is None:
        raise InputError(f"{name} is missing.")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{name} must be a number, got {value!r}.")
    if not math.isfinite(value):
        raise InputError(f"{name} must be a finite number, got {value!r}.")
    if value <= 0:
        raise InputError(f"{name} must be greater than zero, got {value!r}.")


def _to_basis(basis: RatingBasis | str) -> RatingBasis:
    """Accept "MW"/"MVA" (any case) or a RatingBasis."""
    if isinstance(basis, RatingBasis):
        return basis
    try:
        return RatingBasis(str(basis).upper())
    except ValueError:
        raise InputError(f"Rating basis must be 'MW' or 'MVA', got {basis!r}.") from None
