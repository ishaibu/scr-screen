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
        rating_mw: plant rating in MW (always required). It can be 0 for a device
            that produces no active power, such as a STATCOM, if rating_mva is
            given: such a device counts only on the MVA basis (NERC's WSCR-MVA).
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
        if self.rating_mva is not None:
            _check_positive(self.rating_mva, f"rating_mva for plant '{self.plant_id}'")
        no_active_power = (not isinstance(self.rating_mw, bool) and isinstance(self.rating_mw, (int, float))
                           and self.rating_mw == 0)
        if no_active_power:
            # A device with no active power (e.g. a STATCOM) counts only on the MVA basis.
            if self.rating_mva is None:
                raise InputError(f"rating_mw for plant '{self.plant_id}' must be greater than zero, got 0. "
                                 "A device with no active power (such as a STATCOM) can have rating_mw 0 only "
                                 "with rating_mva, and then counts only on the MVA basis.")
        else:
            _check_positive(self.rating_mw, f"rating_mw for plant '{self.plant_id}'")

    def rating(self, basis: RatingBasis | str = RatingBasis.MW) -> float:
        """Return the plant rating on the requested basis (MW or MVA)."""
        basis = _to_basis(basis)
        if basis is RatingBasis.MW:
            return self.rating_mw
        if self.rating_mva is None:
            raise InputError(
                f"Plant '{self.plant_id}' has no rating_mva, so the MVA basis "
                "cannot be used. Provide rating_mva (nameplate), or inverters and inverter_mva, or a "
                "power_factor (an estimate; or run --power-factor 0.95), or use the MW basis."
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


# ---------------------------------------------------------------------------
# Plant MVA rating: nameplate, inverter count x inverter MVA, or a power-factor estimate.

MVA_NAMEPLATE, MVA_INVERTERS, MVA_ESTIMATED = "nameplate", "inverters", "estimated"


def plant_mva(mw: float, mva: float | None = None, inverters: float | None = None,
              inverter_mva: float | None = None, power_factor: float | None = None,
              where: str = "the plant") -> tuple[float | None, str | None]:
    """The plant's MVA rating for the MVA basis, and how it was obtained.

    NERC's MVA-based metrics use the nominal (nameplate) MVA rating of the
    inverter-based resource. Give ONE of:
      * mva: the aggregate nameplate MVA, if known;
      * inverters and inverter_mva: nameplate = inverters x inverter_mva
        (e.g. 55 x 4.2 MVA = 231 MVA);
      * power_factor: an ESTIMATE, MVA = MW / power factor (e.g. the 0.95
        required at the point of interconnection). Inverter nameplate MVA is
        usually higher, so the estimate gives higher, less conservative ratios.

    Returns:
        (MVA or None, MVA_NAMEPLATE / MVA_INVERTERS / MVA_ESTIMATED or None).
    """
    has_inv = inverters is not None or inverter_mva is not None
    given = [mva is not None, has_inv, power_factor is not None]
    if sum(given) > 1:
        raise InputError(f"Give only one MVA rating for {where}: the nameplate MVA, OR the number of "
                         "inverters with each inverter's MVA, OR a power factor for an estimate.")
    if mva is not None:
        _check_positive(mva, f"MVA rating for {where}")
        return float(mva), MVA_NAMEPLATE
    if has_inv:
        if inverters is None or inverter_mva is None:
            raise InputError(f"For {where}, give both the number of inverters and each inverter's MVA.")
        _check_positive(inverters, f"number of inverters for {where}")
        if float(inverters) != int(inverters):
            raise InputError(f"The number of inverters for {where} must be a whole number, got {inverters:g}.")
        _check_positive(inverter_mva, f"inverter MVA for {where}")
        return float(inverters) * float(inverter_mva), MVA_INVERTERS
    if power_factor is not None:
        if isinstance(power_factor, bool) or not isinstance(power_factor, (int, float)) \
                or not (0 < power_factor <= 1):
            raise InputError(f"Power factor for {where} must be above 0 and at most 1, got {power_factor!r}.")
        if not mw > 0:
            raise InputError(f"A power factor cannot estimate the MVA of {where}, which has 0 MW "
                             "(e.g. a STATCOM); give its nameplate MVA.")
        return float(mw) / float(power_factor), MVA_ESTIMATED
    return None, None


def mva_source_text(mw: float, mva: float, kind: str, inverters=None, inverter_mva=None,
                    power_factor=None) -> str:
    """One sentence saying where an MVA rating came from (for notes and reports)."""
    if kind == MVA_INVERTERS:
        return (f"{mva:,.1f} MVA = {int(inverters)} inverters × {inverter_mva:g} MVA "
                "(aggregate inverter nameplate)")
    if kind == MVA_ESTIMATED:
        return (f"{mva:,.1f} MVA ESTIMATED as {mw:,.1f} MW ÷ power factor {power_factor:g}; inverter nameplate "
                "MVA is usually higher, which gives lower (more conservative) ratios, so use the nameplate "
                "rating when it is known")
    return f"{mva:,.1f} MVA (nameplate)"
