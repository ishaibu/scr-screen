"""Tests for scr_screen.metrics and scr_screen.settings.

Expected values come from hand calculations in docs/design-spec.md (Section 8).
Each case must be verified by hand by the author before being relied on.
"""

import math

import pytest

from scr_screen.metrics import (
    Flag,
    InputError,
    Plant,
    RatingBasis,
    classify,
    group_wscr,
    plant_scr,
    scr,
    wscr,
)
from scr_screen.settings import Thresholds


# --- T1: single-plant SCR ----------------------------------------------------

def test_t1_single_plant_scr():
    # 500 MVA / 100 MW = 5.000
    assert scr(500, 100) == pytest.approx(5.0)


# --- T2 / T2b: WSCR vs individual SCR ----------------------------------------

def test_t2_wscr_two_plants():
    # (1000*200 + 600*100) / (200 + 100)^2 = 260000 / 90000 = 2.889
    assert wscr([1000, 600], [200, 100]) == pytest.approx(260000 / 90000)
    assert round(wscr([1000, 600], [200, 100]), 3) == 2.889


def test_t2b_individual_scrs_are_optimistic():
    individual = [scr(1000, 200), scr(600, 100)]
    assert individual == pytest.approx([5.0, 6.0])
    assert wscr([1000, 600], [200, 100]) < min(individual)


def test_wscr_single_plant_equals_scr():
    assert wscr([500], [100]) == pytest.approx(scr(500, 100))


# --- Rating basis (Decision D1/D3: MW default, MVA optional) -----------------

def test_plant_scr_defaults_to_mw():
    p = Plant("PV-A", scmva=500, rating_mw=100, rating_mva=110)
    assert plant_scr(p) == pytest.approx(5.0)


def test_plant_scr_mva_basis():
    p = Plant("PV-A", scmva=550, rating_mw=100, rating_mva=110)
    assert plant_scr(p, RatingBasis.MVA) == pytest.approx(5.0)
    assert plant_scr(p, "mva") == pytest.approx(5.0)  # case-insensitive


def test_mva_basis_without_mva_rating_raises():
    p = Plant("PV-A", scmva=500, rating_mw=100)
    with pytest.raises(InputError, match="no rating_mva"):
        plant_scr(p, "MVA")


def test_invalid_basis_raises():
    p = Plant("PV-A", scmva=500, rating_mw=100)
    with pytest.raises(InputError, match="MW' or 'MVA"):
        plant_scr(p, "kW")


def test_group_wscr_matches_t2():
    plants = [
        Plant("P1", scmva=1000, rating_mw=200, group="G1"),
        Plant("P2", scmva=600, rating_mw=100, group="G1"),
    ]
    assert group_wscr(plants) == pytest.approx(260000 / 90000)


# --- Flags (Decision D4: <2 very weak, 2 to <3 weak, >=3 none) ---------------

@pytest.mark.parametrize(
    "value, expected",
    [
        (1.99, Flag.VERY_WEAK),
        (2.0, Flag.WEAK),
        (2.99, Flag.WEAK),
        (3.0, Flag.NONE),
        (4.859, Flag.NONE),
        (0.5, Flag.VERY_WEAK),
    ],
)
def test_classify_default_bands(value, expected):
    assert classify(value) is expected


def test_classify_custom_thresholds():
    t = Thresholds(very_weak_below=1.5, weak_below=5.0)
    assert classify(1.4, t) is Flag.VERY_WEAK
    assert classify(3.0, t) is Flag.WEAK
    assert classify(5.0, t) is Flag.NONE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"very_weak_below": 3.0, "weak_below": 2.0},   # wrong order
        {"very_weak_below": 2.0, "weak_below": 2.0},   # equal
        {"very_weak_below": -1.0, "weak_below": 3.0},  # negative
        {"very_weak_below": 2.0, "weak_below": math.inf},
    ],
)
def test_invalid_thresholds_raise(kwargs):
    with pytest.raises(ValueError):
        Thresholds(**kwargs)


# --- T5: input errors ---------------------------------------------------------

@pytest.mark.parametrize("bad", [0, -100, None, math.nan, math.inf, "100", True])
def test_scr_rejects_bad_rating(bad):
    with pytest.raises(InputError):
        scr(500, bad)


@pytest.mark.parametrize("bad", [0, -500, None, math.nan])
def test_scr_rejects_bad_scmva(bad):
    with pytest.raises(InputError):
        scr(bad, 100)


def test_wscr_rejects_empty():
    with pytest.raises(InputError, match="at least one plant"):
        wscr([], [])


def test_wscr_rejects_length_mismatch():
    with pytest.raises(InputError, match="one rating per SCMVA"):
        wscr([1000, 600], [200])


def test_wscr_rejects_bad_value_and_names_plant():
    with pytest.raises(InputError, match="plant 2"):
        wscr([1000, 600], [200, 0])


def test_plant_rejects_missing_scmva():
    with pytest.raises(InputError, match="scmva for plant 'PV-A' is missing"):
        Plant("PV-A", scmva=None, rating_mw=100)


def test_plant_rejects_blank_id():
    with pytest.raises(InputError, match="plant_id"):
        Plant("  ", scmva=500, rating_mw=100)
