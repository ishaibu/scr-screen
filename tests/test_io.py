"""Tests for CSV input/output and the screening engine."""

import csv
import json

import pytest

from scr_screen.io import read_plants_csv, write_results_csv, write_results_json, write_template_csv
from scr_screen.metrics import InputError
from scr_screen.screening import screen


def write(tmp_path, text, name="plants.csv", encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


VALID = (
    "plant_id,poi_name,scmva,rating_mw,rating_mva,group\n"
    "P1,Bus 1,1000,200,210,G1\n"
    "P2,Bus 2,600,100,,G1\n"
    "P3,Bus 3,485.86,100,,\n"
)


# --- Reading ------------------------------------------------------------------

def test_read_valid_csv(tmp_path):
    plants, poi = read_plants_csv(write(tmp_path, VALID))
    assert [p.plant_id for p in plants] == ["P1", "P2", "P3"]
    assert plants[0].rating_mva == 210 and plants[1].rating_mva is None
    assert plants[2].group is None
    assert poi["P3"] == "Bus 3"


def test_excel_utf8_bom_and_column_order_and_case(tmp_path):
    text = "Rating_MW,SCMVA,Plant_ID\n100,500,X\n"
    plants, _ = read_plants_csv(write(tmp_path, text, encoding="utf-8-sig"))
    assert plants[0].scmva == 500 and plants[0].rating_mw == 100


def test_blank_lines_skipped(tmp_path):
    plants, _ = read_plants_csv(write(tmp_path, "plant_id,scmva,rating_mw\n\nA,500,100\n,,\n"))
    assert len(plants) == 1


def test_missing_required_column(tmp_path):
    with pytest.raises(InputError, match="missing required column.*rating_mw"):
        read_plants_csv(write(tmp_path, "plant_id,scmva\nA,500\n"))


def test_bad_number_reports_row(tmp_path):
    with pytest.raises(InputError, match="Row 3: scmva must be a number"):
        read_plants_csv(write(tmp_path, "plant_id,scmva,rating_mw\nA,500,100\nB,abc,100\n"))


def test_comma_in_number_refused(tmp_path):
    with pytest.raises(InputError, match="Row 2: scmva contains a comma"):
        read_plants_csv(write(tmp_path, 'plant_id,scmva,rating_mw\nA,"1,000",100\n'))


def test_empty_required_value(tmp_path):
    with pytest.raises(InputError, match="Row 2: rating_mw is empty"):
        read_plants_csv(write(tmp_path, "plant_id,scmva,rating_mw\nA,500,\n"))


def test_zero_rating_rejected(tmp_path):
    with pytest.raises(InputError, match="greater than zero"):
        read_plants_csv(write(tmp_path, "plant_id,scmva,rating_mw\nA,500,0\n"))


def test_duplicate_plant_id(tmp_path):
    with pytest.raises(InputError, match="Row 3: plant_id 'A' appears more than once"):
        read_plants_csv(write(tmp_path, "plant_id,scmva,rating_mw\nA,500,100\nA,600,100\n"))


def test_header_only_and_empty_file(tmp_path):
    with pytest.raises(InputError, match="no plant rows"):
        read_plants_csv(write(tmp_path, "plant_id,scmva,rating_mw\n"))
    with pytest.raises(InputError, match="empty"):
        read_plants_csv(write(tmp_path, ""))


def test_missing_file(tmp_path):
    with pytest.raises(InputError, match="not found"):
        read_plants_csv(tmp_path / "nope.csv")


# --- Screening engine ---------------------------------------------------------

def test_screen_matches_t2_and_flags(tmp_path):
    plants, poi = read_plants_csv(write(tmp_path, VALID))
    r = screen(plants, poi_names=poi)
    scrs = {p.plant_id: p.scr for p in r.plants}
    assert scrs["P1"] == pytest.approx(5.0) and scrs["P2"] == pytest.approx(6.0)
    g = r.groups[0]
    assert g.group == "G1" and g.plant_ids == ["P1", "P2"]
    assert g.wscr == pytest.approx(260000 / 90000)
    assert g.flag == "weak"
    assert g.min_individual_scr == pytest.approx(5.0)
    assert r.basis == "MW" and r.tool_version


def test_screen_mva_basis_needs_mva(tmp_path):
    plants, _ = read_plants_csv(write(tmp_path, VALID))
    with pytest.raises(InputError, match="no rating_mva"):
        screen(plants, basis="MVA")


# --- Writing ------------------------------------------------------------------

def test_json_output_round_trip(tmp_path):
    plants, poi = read_plants_csv(write(tmp_path, VALID))
    out = write_results_json(screen(plants, poi_names=poi), tmp_path / "r.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["basis"] == "MW"
    assert len(data["plants"]) == 3 and len(data["groups"]) == 1
    assert data["thresholds"] == {"very_weak_below": 2.0, "weak_below": 3.0}


def test_csv_output_rows(tmp_path):
    plants, poi = read_plants_csv(write(tmp_path, VALID))
    out = write_results_csv(screen(plants, poi_names=poi), tmp_path / "r.csv")
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["type"] for r in rows] == ["plant (SCR)"] * 3 + ["group (WSCR)"]
    assert rows[3]["ratio"] == "2.889" and rows[3]["flag"] == "weak"


def test_template_is_valid_input(tmp_path):
    path = write_template_csv(tmp_path / "template.csv")
    plants, _ = read_plants_csv(path)
    assert len(plants) == 3
    r = screen(plants)
    assert r.groups[0].wscr == pytest.approx(260000 / 90000)
