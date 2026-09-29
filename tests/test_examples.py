"""Checks that the IEEE 39-bus example runs and gives sensible results."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from ieee39_example import compare_methods  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")


@pytest.fixture(scope="module")
def rows():
    return compare_methods(300)


def test_every_bus_screened(rows):
    assert len(rows) == 39
    assert {r["ieee_bus"] for r in rows} == set(range(1, 40))


def test_values_positive_and_sorted_strongest_first(rows):
    scrs = [r["scr_classical"] for r in rows]
    assert all(s > 0 for s in scrs)
    assert scrs == sorted(scrs, reverse=True)


def test_iec_higher_than_classical_by_a_plausible_margin(rows):
    # IEC max case includes c = 1.1 plus correction factors, so it should be
    # somewhat higher than classical, but not wildly different.
    for r in rows:
        assert 0 < r["iec_vs_classical_pct"] < 25


def test_large_plant_triggers_flags():
    rows = compare_methods(1500)
    assert any(r["flag_classical"] in ("weak", "very weak") for r in rows)
