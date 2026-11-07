"""v0.3.1: MVA basis in scans, 0 MW devices (STATCOMs), group member sizes, generator outages, --gen-out.

Expected values are computed independently in each test (hand formulas or a full network
rebuild), not taken from the tool.
"""

import copy
import json
from pathlib import Path

import pytest

from scr_screen.classical import build_zbus, scmva_classical
from scr_screen.cli import main
from scr_screen.io import read_bus_groups_full, read_plants_csv
from scr_screen.loaders import load_network
from scr_screen.metrics import InputError, Plant
from scr_screen.screening import screen
from scr_screen.strength import composite_scmva

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
NET = str(EXAMPLES / "ieee39_assumed.json")
GROUPS = str(EXAMPLES / "ieee39_groups_example.csv")
GROUPS_MVA = str(EXAMPLES / "ieee39_groups_mva_example.csv")


def _scan(tmp_path, *extra):
    out = tmp_path / "r.json"
    assert main(["scan", NET, "--plant-mw", "1500", "--out", str(out), "--no-compare", *extra]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    return {p["plant_id"]: p for p in d["plants"]}, {g["group"]: g for g in d["groups"]}, d


def _z(net):
    zb = build_zbus(net)
    idx = {str(net.bus.at[b, "name"]): b for b in zb.pos}
    return zb, idx


# --- direct mode: devices with no active power ---------------------------------------

def test_statcom_counts_only_on_mva_basis():
    plants = [Plant("PV-A", 1000, 200, 210, "G1"), Plant("BESS-B", 600, 100, 110, "G1"),
              Plant("STATCOM-C", 800, 0, 150, "G1")]
    mw = screen(plants, basis="MW")
    assert mw.excluded == ["STATCOM-C"] and [p.plant_id for p in mw.plants] == ["PV-A", "BESS-B"]
    assert mw.groups[0].wscr == pytest.approx((1000 * 200 + 600 * 100) / 300 ** 2)
    mva = screen(plants, basis="MVA")
    assert mva.excluded == [] and len(mva.plants) == 3
    assert mva.groups[0].wscr == pytest.approx((1000 * 210 + 600 * 110 + 800 * 150) / 470 ** 2)


def test_zero_mw_needs_mva_rating():
    with pytest.raises(InputError, match="greater than zero.*only with rating_mva"):
        Plant("X", 500, 0)
    with pytest.raises(InputError, match="greater than zero"):
        Plant("X", 500, -1, 100)


def test_run_command_notes_excluded_device(tmp_path, capsys):
    f = tmp_path / "p.csv"
    f.write_text("plant_id,scmva,rating_mw,rating_mva,group\nA,1000,200,210,G1\nS,800,0,150,G1\n", encoding="utf-8")
    assert main(["run", str(f)]) == 0
    assert "Left out on the MW basis (0 MW, e.g. STATCOMs): S" in capsys.readouterr().out
    plants, _ = read_plants_csv(f)
    assert plants[1].rating_mw == 0 and plants[1].rating_mva == 150


def test_all_zero_mw_on_mw_basis_is_refused():
    with pytest.raises(InputError, match="use the MVA basis"):
        screen([Plant("S", 800, 0, 150)], basis="MW")


# --- groups file with sizes --------------------------------------------------------------

def test_groups_file_sizes_parsing(tmp_path):
    f = tmp_path / "g.csv"
    f.write_text("bus,group,mw,mva\n11,G1,,\n12,G1,0,200\nBus 16,G2,300,330\n", encoding="utf-8")
    assert read_bus_groups_full(f) == {"11": ("G1", None, None), "12": ("G1", 0.0, 200.0),
                                       "16": ("G2", 300.0, 330.0)}
    for body, msg in [("12,G1,0,\n", "give both mw and mva"), ("12,G1,,200\n", "give both mw and mva"),
                      ("12,G1,-1,200\n", "mw must be 0 or more"), ("12,G1,10,0\n", "mva must be greater than zero")]:
        f.write_text("bus,group,mw,mva\n" + body, encoding="utf-8")
        with pytest.raises(InputError, match=msg):
            read_bus_groups_full(f)


# --- scan on the MVA basis -----------------------------------------------------------------

def test_scan_mva_basis_ratios_and_cscr(tmp_path):
    p, g, d = _scan(tmp_path, "--plant-mva", "1650", "--basis", "MVA", "--groups", GROUPS)
    assert d["basis"] == "MVA"
    assert p["Bus 12"]["scr"] == pytest.approx(p["Bus 12"]["scmva"] / 1650)
    assert p["Bus 12"]["rating"] == 1650
    net = load_network(NET)
    zb, idx = _z(net)
    cs = composite_scmva(zb, [idx["11"], idx["13"]])
    assert g["G1"]["cscr"] == pytest.approx(cs / 3300)                      # NERC: ÷ nominal MVA
    assert g["G1"]["wscr"] == pytest.approx((p["Bus 11"]["scmva"] + p["Bus 13"]["scmva"]) / (4 * 1650))


def test_scan_mva_basis_needs_plant_mva(capsys):
    assert main(["scan", NET, "--plant-mw", "1500", "--basis", "MVA", "--no-compare"]) != 0
    assert "The MVA basis needs the plant's MVA rating" in capsys.readouterr().err


def test_scan_default_unchanged_from_v030(tmp_path):
    """Without the new options, the v0.3.0 values (verified in V1-V3) are unchanged."""
    p, g, d = _scan(tmp_path, "--groups", GROUPS)
    assert d["basis"] == "MW" and d["excluded"] == []
    assert p["Bus 12"]["scr"] == pytest.approx(1.888, abs=5e-4)
    assert g["G1"]["wscr"] == pytest.approx(2.197, abs=5e-4)
    assert g["G1"]["cscr"] == pytest.approx(7391.031 / 3000, rel=1e-6)
    assert p["Bus 11"]["scrif"] == pytest.approx(2.5277, abs=1e-4)
    assert p["Bus 13"]["scrif"] == pytest.approx(2.3972, abs=1e-4)
    assert g["G1"]["member_ratings"] is None


# --- group member sizes and STATCOM in a scan ------------------------------------------------

def test_scan_statcom_member_mva_basis(tmp_path):
    p, g, d = _scan(tmp_path, "--plant-mva", "1650", "--basis", "MVA", "--groups", GROUPS_MVA)
    net = load_network(NET)
    zb, idx = _z(net)
    s = {b: p[f"Bus {b}"]["scmva"] for b in ("11", "12", "13")}
    size = {"11": 1650.0, "13": 1650.0, "12": 200.0}
    g1 = g["G1"]
    assert g1["plant_ids"] == ["Bus 11", "Bus 13", "Bus 12"]
    assert g1["member_ratings"] == [1650.0, 1650.0, 200.0]
    assert g1["total_rating"] == pytest.approx(3500)
    assert g1["wscr"] == pytest.approx(sum(s[b] * size[b] for b in s) / 3500 ** 2)
    assert g1["cscr"] == pytest.approx(composite_scmva(zb, [idx[b] for b in ("11", "13", "12")]) / 3500)
    z = zb.z
    pos = {b: zb.pos[idx[b]] for b in s}

    def IF(i, j):
        return abs(z[pos[i], pos[j]] / z[pos[j], pos[j]])
    for k, b in enumerate(("11", "13", "12")):
        want = s[b] / (size[b] + sum(IF(b, j) * size[j] for j in s if j != b))
        assert g1["member_scrif"][k] == pytest.approx(want, rel=1e-12)
    # the results table row of a fixed-size member describes the scan's plant, so it carries no SCRIF
    assert p["Bus 12"]["scrif"] is None and p["Bus 11"]["scrif"] == pytest.approx(g1["member_scrif"][0])


def test_scan_statcom_left_out_on_mw_basis(tmp_path):
    p, g, d = _scan(tmp_path, "--groups", GROUPS_MVA, "--report", str(tmp_path / "r.html"))
    assert g["G1"]["plant_ids"] == ["Bus 11", "Bus 13"]
    assert g["G1"]["wscr"] == pytest.approx(2.197, abs=5e-4)                # same as without the STATCOM
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Left out of their groups on the MW basis (0 MW, e.g. STATCOMs): Bus 12" in html


def test_scan_fixed_size_plant_member(tmp_path):
    f = tmp_path / "g.csv"
    f.write_text("bus,group,mw,mva\n16,G2,300,330\n17,G2,,\n", encoding="utf-8")
    p, g, _ = _scan(tmp_path, "--groups", str(f), "--report", str(tmp_path / "r.html"))
    s16, s17 = p["Bus 16"]["scmva"], p["Bus 17"]["scmva"]
    assert g["G2"]["wscr"] == pytest.approx((s16 * 300 + s17 * 1500) / 1800 ** 2)
    assert g["G2"]["min_individual_scr"] == pytest.approx(min(s16 / 300, s17 / 1500))
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Bus 16 alone (300 MW)" in html and "data-p='300'" in html and "data-if='" in html


# --- generator outages and --gen-out ----------------------------------------------------------

def test_gen_out_matches_network_with_units_removed(tmp_path):
    p, _, d = _scan(tmp_path, "--gen-out", "38,39")
    net = load_network(NET)
    names = {str(net.bus.at[b, "name"]): b for b in net.bus.index}
    net.gen.loc[net.gen["bus"].isin([names["38"], names["39"]]), "in_service"] = False
    values, _ = scmva_classical(net, list(names.values()))
    for lab, b in names.items():
        assert p[f"Bus {lab}"]["scmva"] == pytest.approx(values[b], rel=1e-9)


@pytest.mark.parametrize("arg,msg", [("31", "external grid"), ("99", "not found"), ("1", "no in-service generator")])
def test_gen_out_errors(arg, msg, capsys):
    assert main(["scan", NET, "--plant-mw", "1500", "--gen-out", arg, "--no-compare"]) != 0
    assert msg in capsys.readouterr().err


def test_n1_includes_generator_outages_in_scan(tmp_path):
    p, _, _ = _scan(tmp_path, "--n1")
    assert p["Bus 38"]["n1_outage"].startswith("generator") and p["Bus 38"]["n1_outage"].endswith("(Bus 38)")
    assert p["Bus 28"]["n1_outage"] == "line 34 (Bus 28–Bus 29)"             # unchanged from v0.3.0
    assert p["Bus 28"]["n1_scr"] == pytest.approx(0.974, abs=5e-4)


# --- report units and wording -------------------------------------------------------------------

def test_report_uses_mva_units_on_mva_basis(tmp_path):
    out = tmp_path / "r.html"
    assert main(["scan", NET, "--plant-mw", "1500", "--plant-mva", "1650", "--basis", "MVA",
                 "--report", str(out), "--no-compare"]) == 0
    html = out.read_text(encoding="utf-8")
    assert "aria-label='Plant size in MVA'> MVA" in html and '"unit": "MVA"' in html
    assert "SCR = SCMVA ÷ plant MVA" in html and "Rating basis: MVA" in html


def test_map_caption_names_no_other_tool(tmp_path):
    out = tmp_path / "r.html"
    assert main(["scan", NET, "--plant-mw", "1500", "--report", str(out), "--no-compare"]) == 0
    html = out.read_text(encoding="utf-8")
    assert "Bus positions follow a one-line drawing of this network" in html
    assert "faultscreen" not in html.lower()


# --- plant MVA rating: nameplate, inverters x inverter MVA, or power-factor estimate -------------

from scr_screen.metrics import MVA_ESTIMATED, MVA_INVERTERS, MVA_NAMEPLATE, plant_mva  # noqa: E402


def test_plant_mva_three_ways():
    assert plant_mva(220, mva=231) == (231.0, MVA_NAMEPLATE)
    assert plant_mva(220, inverters=55, inverter_mva=4.2) == (pytest.approx(231.0), MVA_INVERTERS)
    v, k = plant_mva(220, power_factor=0.95)
    assert v == pytest.approx(220 / 0.95) and k == MVA_ESTIMATED
    assert plant_mva(220) == (None, None)


@pytest.mark.parametrize("kw,msg", [
    (dict(mva=231, power_factor=0.95), "Give only one MVA rating"),
    (dict(mva=231, inverters=55, inverter_mva=4.2), "Give only one MVA rating"),
    (dict(inverters=55), "give both"),
    (dict(inverters=55.5, inverter_mva=4.2), "whole number"),
    (dict(power_factor=1.2), "at most 1"),
    (dict(power_factor=0), "above 0"),
])
def test_plant_mva_errors(kw, msg):
    with pytest.raises(InputError, match=msg):
        plant_mva(220, **kw)


def test_power_factor_cannot_estimate_statcom():
    with pytest.raises(InputError, match="0 MW"):
        plant_mva(0, power_factor=0.95)


@pytest.mark.parametrize("args,mva,word", [
    (["--plant-mva", "231"], 231.0, "(nameplate)"),
    (["--inverters", "55", "--inverter-mva", "4.2"], 231.0, "55 inverters × 4.2 MVA"),
    (["--power-factor", "0.95"], 220 / 0.95, "ESTIMATED as 220.0 MW ÷ power factor 0.95"),
])
def test_scan_mva_sources(tmp_path, args, mva, word):
    out, rep = tmp_path / "r.json", tmp_path / "r.html"
    assert main(["scan", NET, "--plant-mw", "220", "--basis", "MVA", *args, "--out", str(out),
                 "--report", str(rep), "--no-compare"]) == 0
    p = {x["plant_id"]: x for x in json.loads(out.read_text(encoding="utf-8"))["plants"]}
    assert p["Bus 12"]["rating"] == pytest.approx(mva)
    assert p["Bus 12"]["scr"] == pytest.approx(p["Bus 12"]["scmva"] / mva)
    html = rep.read_text(encoding="utf-8")
    assert word in html
    if "power-factor" in args[0]:
        assert "plant MVA estimated from power factor 0.95" in html  # also in the report header


def test_scan_mva_given_but_mw_basis_is_noted(tmp_path):
    out = tmp_path / "r.html"
    assert main(["scan", NET, "--plant-mw", "220", "--power-factor", "0.95", "--report", str(out),
                 "--no-compare"]) == 0
    assert "every ratio uses MW (the default); add --basis MVA" in out.read_text(encoding="utf-8")


def test_plants_csv_mva_columns_and_run_power_factor(tmp_path, capsys):
    f = tmp_path / "p.csv"
    f.write_text("plant_id,scmva,rating_mw,rating_mva,inverters,inverter_mva,power_factor,group\n"
                 "PV-A,1000,200,,55,4.2,,G1\nBESS-B,600,100,110,,,,G1\nWind-C,485.86,100,,,,0.95,\n"
                 "PV-E,300,100,,,,,\n", encoding="utf-8")
    out = tmp_path / "r.json"
    assert main(["run", str(f), "--basis", "MVA", "--power-factor", "0.95", "--out", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    r = {p["plant_id"]: p["rating"] for p in d["plants"]}
    assert r == {"PV-A": pytest.approx(231.0), "BESS-B": 110.0, "Wind-C": pytest.approx(100 / 0.95),
                 "PV-E": pytest.approx(100 / 0.95)}
    assert d["groups"][0]["wscr"] == pytest.approx((1000 * 231 + 600 * 110) / 341 ** 2)
    assert "ESTIMATED" in capsys.readouterr().out
    f.write_text("plant_id,scmva,rating_mw,rating_mva,power_factor\nX,1000,200,210,0.95\n", encoding="utf-8")
    assert main(["run", str(f)]) != 0
    assert "Give only one MVA rating" in capsys.readouterr().err


def test_readme_animation_links_to_demo():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    gif = root / "docs" / "images" / "network-map.gif"
    assert gif.exists() and gif.read_bytes()[:6] in (b"GIF89a", b"GIF87a")
    block = readme[:readme.index("## Why use it")]
    assert ('<a href="https://ishaibu.github.io/scr-screen/demo/"><img src="https://raw.githubusercontent.com/'
            'ishaibu/scr-screen/main/docs/images/network-map.gif"') in block
