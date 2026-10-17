"""WSCR groups in network scans (scan --groups) and the live report."""

from pathlib import Path

import pytest

from scr_screen.cli import main
from scr_screen.io import read_bus_groups_csv
from scr_screen.metrics import InputError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
NET = str(EXAMPLES / "ieee39_assumed.json")
GROUPS = str(EXAMPLES / "ieee39_groups_example.csv")
pytestmark = pytest.mark.filterwarnings("ignore")


def write(tmp_path, text, name="g.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_read_groups_accepts_labels_with_or_without_prefix(tmp_path):
    p = write(tmp_path, "Bus,Group\n11,G1\nBus 13,G1\n\n16,G2\n")
    assert read_bus_groups_csv(p) == {"11": "G1", "13": "G1", "16": "G2"}


@pytest.mark.parametrize("text, match", [
    ("bus\n11\n", "missing column"),
    ("bus,group\n11,G1\n11,G2\n", "more than once"),
    ("bus,group\n11,\n", "group is empty"),
    ("bus,group\n,G1\n", "bus is empty"),
    ("bus,group\n", "no rows"),
])
def test_read_groups_errors(tmp_path, text, match):
    with pytest.raises(InputError, match=match):
        read_bus_groups_csv(write(tmp_path, text))


def test_scan_with_groups_gives_hand_checkable_wscr(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert main(["scan", NET, "--plant-mw", "1500", "--groups", GROUPS, "--out", str(out)]) == 0
    import json

    data = json.loads(out.read_text(encoding="utf-8"))
    plants = {p["plant_id"]: p for p in data["plants"]}
    g1 = next(g for g in data["groups"] if g["group"] == "G1")
    # Equal plants: WSCR = sum(SCMVA) / (n**2 * P)
    expected = (plants["Bus 11"]["scmva"] + plants["Bus 13"]["scmva"]) / (4 * 1500)
    assert g1["wscr"] == pytest.approx(expected)
    assert g1["flag"] == "weak" and g1["min_individual_scr"] > 3   # pass alone, weak together
    assert [g["group"] for g in data["groups"]] == ["G1", "G2"]
    assert "Group G1: WSCR 2.197 (weak)" in capsys.readouterr().out


def test_scan_without_groups_is_unchanged(tmp_path):
    out = tmp_path / "r.json"
    assert main(["scan", NET, "--plant-mw", "1500", "--out", str(out)]) == 0
    assert '"groups": []' in out.read_text(encoding="utf-8")


def test_scan_groups_unknown_bus(tmp_path, capsys):
    p = write(tmp_path, "bus,group\n11,G1\n999,G1\n")
    assert main(["scan", NET, "--plant-mw", "1500", "--groups", str(p)]) == 2
    assert "not in the scan: 999" in capsys.readouterr().err


def test_live_report_has_group_data_and_counts_groups(tmp_path):
    rep = tmp_path / "r.html"
    assert main(["scan", NET, "--plant-mw", "1500", "--groups", GROUPS, "--report", str(rep),
                 "--no-compare"]) == 0
    html = rep.read_text(encoding="utf-8")
    assert "Plants screened together (WSCR)" in html
    assert "class='gbox' data-g='G1'" in html and "class='gres' data-g='G2'" in html
    assert "id='card-glow'" in html and "6 of 41" in html
    assert "class='note g-drop'" in html
    # Groups come right after the SCR chart, before the largest-plant chart
    assert html.index("Plants screened together") < html.index("Largest plant before a weak flag")


def test_threshold_labels_have_room_above_charts(tmp_path):
    rep = tmp_path / "r.html"
    assert main(["scan", NET, "--plant-mw", "1500", "--report", str(rep)]) == 0
    assert ".scr-chart,.cmp{padding-top:20px}" in rep.read_text(encoding="utf-8")


def test_missing_file_hints_at_example_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["example"]) == 0
    capsys.readouterr()
    assert main(["scan", "ieee39_assumed.json", "--plant-mw", "1500"]) == 2
    err = capsys.readouterr().err
    assert "Network file not found: ieee39_assumed.json" in err
    assert "cd scr-screen-example" in err


def test_missing_file_without_example_folder_has_plain_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["run", "nope.csv"]) == 2
    err = capsys.readouterr().err
    assert "Input file not found: nope.csv" in err and "scr-screen-example" not in err



def test_scan_report_shows_model_index_not_pandapower_jargon(tmp_path):
    rep, out = tmp_path / "r.html", tmp_path / "r.csv"
    assert main(["scan", NET, "--plant-mw", "1500", "--report", str(rep), "--out", str(out)]) == 0
    html = rep.read_text(encoding="utf-8")
    assert "<th>Model index</th>" in html and "<td>Bus 30</td><td>29</td>" in html
    assert "pandapower index" not in html
    assert ",29," in out.read_text(encoding="utf-8")


def test_direct_mode_report_keeps_poi_column(tmp_path):
    csv_path, rep = tmp_path / "p.csv", tmp_path / "r.html"
    assert main(["template", str(csv_path)]) == 0
    assert main(["run", str(csv_path), "--report", str(rep)]) == 0
    assert "<th>POI</th>" in rep.read_text(encoding="utf-8")
