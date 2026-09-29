"""Tests for the HTML report."""

import pytest

from scr_screen.metrics import Plant
from scr_screen.report import DISCLAIMER, render_html, write_html_report
from scr_screen.screening import screen


@pytest.fixture
def result():
    plants = [
        Plant("PV-A", scmva=1000, rating_mw=200, group="G1"),
        Plant("BESS-B", scmva=600, rating_mw=100, group="G1"),
        Plant("Wind-C", scmva=150, rating_mw=100),
    ]
    return screen(plants, poi_names={"PV-A": "Bus 101"})


def test_report_contains_key_results(result):
    html = render_html(result)
    for text in ["PV-A", "BESS-B", "Wind-C", "Bus 101", "5.00", "6.00", "1.50", "2.89",
                 "Very weak", "Weak", "No flag", "Together (WSCR)"]:
        assert text in html


def test_group_note_explains_drop(result):
    # WSCR 2.889 vs weakest plant alone 5.0 -> 42% lower
    assert "42% lower" in render_html(result)


def test_disclaimer_and_method_always_present(result):
    html = render_html(result)
    assert DISCLAIMER in html
    assert "Method and assumptions" in html
    assert "direct input" in html


def test_extra_notes_included(result):
    assert "Assumed X&#x27;&#x27;d" in render_html(result, notes=["Assumed X''d = 0.20 pu"])


def test_user_text_is_escaped():
    r = screen([Plant("<script>alert(1)</script>", scmva=500, rating_mw=100)])
    html = render_html(r)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_self_contained_no_external_resources(result):
    html = render_html(result)
    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "<script" not in html


def test_no_groups_section_when_no_groups():
    r = screen([Plant("A", scmva=500, rating_mw=100)])
    assert "Plants screened together" not in render_html(r)


def test_write_file(tmp_path, result):
    path = write_html_report(result, tmp_path / "report.html", title="My study")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert "<title>My study</title>" in text
