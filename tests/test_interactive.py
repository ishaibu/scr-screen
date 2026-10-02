"""Tests for the interactive scan report: slider (V3), comparison (V4), --open."""

from pathlib import Path

import pytest

from scr_screen.cli import main
from scr_screen.metrics import Plant
from scr_screen.report import render_html
from scr_screen.screening import screen

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
pytestmark = pytest.mark.filterwarnings("ignore")


def scan_like(mw=100):
    plants = [Plant("Bus 1", scmva=900, rating_mw=mw), Plant("Bus 2", scmva=250, rating_mw=mw)]
    return screen(plants, poi_names={"Bus 1": "pandapower index 0", "Bus 2": "pandapower index 1"})


def test_direct_mode_report_has_no_script_and_no_slider():
    html = render_html(scan_like())
    assert "<script" not in html and "mw-range" not in html


def test_interactive_report_has_slider_config_and_data():
    html = render_html(scan_like(), interactive={"plant_mw": 100, "compare": None})
    assert "id='mw-range'" in html and "id='scr-cfg'" in html
    assert '"mw": 100.0' in html and '"wk": 3.0' in html
    assert html.count("data-scmva='900'") >= 2   # chart row and table row
    assert "Method comparison" not in html


def test_interactive_report_is_still_self_contained():
    html = render_html(scan_like(), interactive={"plant_mw": 100, "compare": None})
    assert "<script src" not in html and "<link" not in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html


def test_comparison_counts_flag_differences():
    # Bus 2: 250/100 = 2.5 (weak) vs 320/100 = 3.2 (no flag) -> flags differ
    html = render_html(scan_like(), interactive={
        "plant_mw": 100, "compare": {"Bus 1": 950, "Bus 2": 320},
        "primary_label": "Classical", "compare_label": "IEC 60909"})
    assert "Method comparison: Classical vs IEC 60909" in html
    assert "id='cmp-diff'>1<" in html
    assert html.count("class='row diff'") == 1


def test_cli_scan_report_has_map_slider_and_comparison(tmp_path):
    out = tmp_path / "scan.html"
    assert main(["scan", str(EXAMPLES / "ieee39_assumed.json"), "--plant-mw", "1500",
                 "--report", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "id='mw-range'" in html and "Method comparison: Classical vs IEC 60909" in html
    # At 1500 MW the methods disagree on IEEE buses 1, 9 and 12 (see the IEEE 39 example).
    assert "id='cmp-diff'>3<" in html


def test_cli_no_compare(tmp_path):
    out = tmp_path / "scan.html"
    main(["scan", str(EXAMPLES / "ieee39_assumed.json"), "--plant-mw", "1500",
          "--report", str(out), "--no-compare"])
    assert "Method comparison" not in out.read_text(encoding="utf-8")


def test_cli_open_calls_browser(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    csv_path = tmp_path / "plants.csv"
    main(["template", str(csv_path)])
    main(["run", str(csv_path), "--report", str(tmp_path / "r.html"), "--open"])
    assert opened and opened[0].startswith("file://") and opened[0].endswith("r.html")


@pytest.mark.parametrize("mw", ["0", "-50"])
def test_cli_scan_rejects_zero_or_negative_plant_size(mw, capsys):
    assert main(["scan", str(EXAMPLES / "ieee39_assumed.json"), "--plant-mw", mw]) == 2
    assert "Plant size (--plant-mw) must be greater than zero" in capsys.readouterr().err


def test_report_has_invalid_size_message_area():
    html = render_html(scan_like(), interactive={"plant_mw": 100, "compare": None})
    assert "id='mw-msg'" in html and "Enter a plant size above 0 MW" in html
