"""User-configurable screening settings.

Default flag bands follow HVDC planning practice (IEEE Std 1204-1997):
SCR below 2 is "very weak", 2 to below 3 is "weak", and 3 or above is not
flagged. NERC (2018) likewise notes that low-SCR areas typically have SCR
below about 3.

These bands are screening aids only. There is no universal weak-grid
threshold (NERC Reliability Guideline, 2017), and they do not replace an
inverter manufacturer's minimum SCR rating.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    """Flag band boundaries, applied to SCR and WSCR alike.

    Attributes:
        very_weak_below: values strictly below this are flagged "very weak".
        weak_below: values from ``very_weak_below`` up to (but not including)
            this value are flagged "weak". Values at or above it are not flagged.
    """

    very_weak_below: float = 2.0
    weak_below: float = 3.0

    def __post_init__(self) -> None:
        for name in ("very_weak_below", "weak_below"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number, got {value!r}.")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive, finite number, got {value!r}.")
        if self.very_weak_below >= self.weak_below:
            raise ValueError(
                "very_weak_below must be less than weak_below "
                f"(got {self.very_weak_below} and {self.weak_below})."
            )


DEFAULT_THRESHOLDS = Thresholds()
