"""v0.6.0: group N-1 WSCR, group hosting capacity, interaction factors, every flagged bus pulses, dashboard layout."""

from __future__ import annotations

import copy
import csv
import json
import random
import re
import warnings
from pathlib import Path

import pytest

import scr_screen
from scr_screen.classical import build_zbus, scmva_classical
from scr_screen.cli import main
from scr_screen.dashboard import VIEWS, render_dashboard
from scr_screen.loaders import load_network
from scr_screen.metrics import wscr
from scr_screen.report import SCRIPT
from scr_screen.strength import group_n1_cases, group_n1_wscr, interaction_matrix

EX = Path(__file__).resolve().parents[1] / "examples"
NET = EX / "ieee39_assumed.json"
GROUPS = EX / "ieee39_groups_example.csv"


def _read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _net():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_network(NET)


@pytest.fixture(scope="module")
def all_cases():
    """SCMVA at every bus, intact and with each line, transformer and generator removed (full rebuild)."""
    net = _net()
    zb = build_zbus(net)
    buses = list(zb.pos)
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        base, _ = scmva_classical(net, buses)
        out.append(base)
        for table in ("line", "trafo", "gen"):
            for idx in net[table].index:
                m = copy.deepcopy(net)
                m[table].at[idx, "in_service"] = False
                v, _ = scmva_classical(m, buses, skip_isolated=True)
                out.append(v)
    return net, zb, out


@pytest.mark.parametrize("labels", [["11", "13"], ["16", "17"], ["4", "5", "6", "7"], ["25", "26", "27", "28", "29"]])
def test_group_n1_wscr_equals_full_rebuild_for_any_sizes(all_cases, labels):
    net, zb, cases_all = all_cases
    names = {str(n): i for i, n in net.bus["name"].items()}
    buses = [names[x] for x in labels]
    cases = group_n1_cases(zb, buses)
    assert 1 <= len(cases) < len(cases_all)       # pruned: only cases that can be the lowest for some sizes
    rng = random.Random(7)
    for _ in range(40):
        sizes = [rng.choice([1.0, 50.0, 300.0, 1500.0, 2500.0]) for _ in buses]
        value, _ = group_n1_wscr(cases, sizes)
        brute = min(sum(c[b] * p for b, p in zip(buses, sizes)) / sum(sizes) ** 2 for c in cases_all)
        assert value == pytest.approx(brute, rel=1e-9)


def test_group_n1_wscr_is_not_above_intact_wscr():
    net = _net()
    zb = build_zbus(net)
    names = {str(n): i for i, n in net.bus["name"].items()}
    buses = [names["11"], names["13"]]
    cases = group_n1_cases(zb, buses)
    v, text = group_n1_wscr(cases, [1500.0, 1500.0])
    assert v <= wscr(cases[0][1], [1500.0, 1500.0]) and text != "none"


def _scan(tmp_path, *extra, groups=GROUPS):
    out, csv_out, rep = tmp_path / "r.json", tmp_path / "r.csv", tmp_path / "r.html"
    args = ["scan", str(NET), "--plant-mw", "1500"] + (["--groups", str(groups)] if groups else []) + list(extra)
    assert main(args + ["--out", str(out), "--report", str(rep)]) == 0
    assert main(args + ["--out", str(csv_out)]) == 0
    data = json.loads(_read(out))
    return data, list(csv.DictReader(_read(csv_out).splitlines())), _read(rep)


def test_group_hosting_capacity_and_n1_in_outputs(tmp_path):
    data, rows, html = _scan(tmp_path, "--n1", "--emt-triage")
    wk = data["thresholds"]["weak_below"]
    plants = {p["plant_id"]: p for p in data["plants"]}
    for g in data["groups"]:
        s = [plants[pid]["scmva"] for pid in g["plant_ids"]]
        total = g["total_rating"]
        assert g["max_total_no_flag"] == pytest.approx(g["wscr"] * total / wk, rel=1e-12)
        k = g["max_total_no_flag"] / total                       # scale every member by k ...
        assert wscr(s, [1500.0 * k] * len(s)) == pytest.approx(wk, rel=1e-12)   # ... and WSCR equals the weak threshold
        assert g["n1_wscr"] < g["wscr"] and g["n1_outage"]
        assert g["n1_max_total_no_flag"] == pytest.approx(g["n1_wscr"] * total / wk, rel=1e-12)
        ifm = g["interaction"]
        assert set(ifm) == set(g["plant_ids"]) and all(0 < v <= 1.0 + 1e-9 for d in ifm.values() for v in d.values())
    g1 = next(g for g in data["groups"] if g["group"] == "G1")
    assert round(g1["n1_wscr"], 3) == 1.588 and g1["n1_outage"] == "line 11 (Bus 6–Bus 11)"
    assert round(g1["max_total_no_flag"], 1) == 2197.2 and round(g1["n1_max_total_no_flag"], 1) == 1588.3
    gr = {r["id"]: r for r in rows if r["type"] == "group (WSCR)"}
    assert gr["G1"]["max_mw_no_flag"] == "2197.2" and gr["G1"]["n1_ratio"] == "1.588"
    assert gr["G1"]["n1_outage"] == "line 11 (Bus 6–Bus 11)" and gr["G1"]["emt_priority"] == "2"
    # report: N-1 line, hosting line, worst-member priority and the interaction table
    assert "Together, worst single outage (N-1 WSCR)" in html and "line 11 (Bus 6–Bus 11) out" in html
    assert "<span class='val g-host'>2,197.2</span> MW intact" in html and "1,588.3</span> MW N-1" in html
    assert "EMT study priority (worst member)" in html and "class='iftab'" in html
    assert f"<td class='n'>{g1['interaction']['Bus 11']['Bus 13']:.2f}</td>" in html
    assert "<th class='n'>N-1 WSCR</th>" in html and "c-gmax" in html


def test_interaction_factors_match_the_impedance_matrix(tmp_path):
    data, _, _ = _scan(tmp_path)
    net = _net()
    zb = build_zbus(net)
    names = {str(n): i for i, n in net.bus["name"].items()}
    ifs = interaction_matrix(zb, [names["11"], names["13"]])
    g1 = next(g for g in data["groups"] if g["group"] == "G1")
    assert g1["interaction"]["Bus 11"]["Bus 13"] == pytest.approx(ifs[(names["11"], names["13"])], rel=1e-12)
    assert g1["interaction"]["Bus 13"]["Bus 11"] == pytest.approx(ifs[(names["13"], names["11"])], rel=1e-12)
    assert g1["n1_wscr"] is None                                        # only with --n1


def test_groups_without_network_get_hosting_capacity(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("plant_id,scmva,rating_mw,group\nA,3000,400,G\nB,2000,200,G\n", encoding="utf-8")
    out = tmp_path / "r.json"
    assert main(["run", str(f), "--out", str(out)]) == 0
    g = json.loads(_read(out))["groups"][0]
    assert g["max_total_no_flag"] == pytest.approx((3000 * 400 + 2000 * 200) / 600 / 3.0)
    assert g["n1_wscr"] is None and g["interaction"] is None


def test_every_flagged_bus_pulses_in_the_report(tmp_path):
    rep = tmp_path / "r.html"
    assert main(["scan", str(NET), "--plant-mw", "3000", "--report", str(rep), "--no-compare"]) == 0
    html = _read(rep)
    nodes = re.findall(r"class='node (vw|wk|ok)'", html)
    assert nodes.count("vw") + nodes.count("wk") == html.count("class='halo ") > 8
    assert html.count("class='lbl'") == 8
    assert "if(big){if(!h){" in SCRIPT                                   # live: every flagged bus pulses


def test_member_size_boxes_and_reset(tmp_path):
    _, _, html = _scan(tmp_path, groups=EX / "ieee39_groups_mva_example.csv")
    boxes = re.findall(r"<input class='g-size'[^>]*>", html)
    assert len(boxes) == 4 and all("data-v0=" in b for b in boxes)  # bus 12 (0 MW) is left out on the MW basis
    assert "value='0' data-v0='0'" not in html                        # 0 MW members are left out on the MW basis
    assert "el.value=el.dataset.v0" in SCRIPT and "A plant size must be a number above 0" in SCRIPT


# --- dashboard ----------------------------------------------------------------------------------

def _dash(tmp_path, *extra):
    d, r = tmp_path / "d.html", tmp_path / "r.html"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--groups", str(GROUPS), "--dashboard", str(d),
                 "--report", str(r), *extra]) == 0
    return _read(d), _read(r)


def test_dashboard_layout_v060(tmp_path):
    d, r = _dash(tmp_path, "--cost", "--condenser-cost-per-mva", "100000")
    assert d.count(SCRIPT) == 1
    nav = re.search(r"<nav class='nav'.*?</nav>", d, re.S).group(0)
    sheet = re.search(r"<div class='sheet' id='nav-sheet'.*?</div></div>", d, re.S).group(0)
    keys = re.findall(r"data-view='(\w+)'", nav)
    assert keys == [k for k, _, _ in VIEWS] and re.findall(r"data-view='(\w+)'", sheet) == keys
    assert f"All {len(keys)} ▾" in d and "data-act='print'" in sheet and "data-act='csv'" in sheet
    assert "id='ctl-sum'" in d and "id='mchart'" in d and "id='mc-sort'" in d
    # the report's two charts stay in the page (hidden) for its script; the merged chart replaces them
    assert d.count("class='panel legacy' aria-hidden='true'") == 2 and "<h2>Largest plant before a weak flag</h2>" in d
    for piece in re.findall(r"<div class='gbox'.*?</div></div>", r, re.S)[:2]:
        assert piece[:200] in d


def test_dashboard_without_a_map_has_no_map_view(tmp_path, monkeypatch):
    import scr_screen.netmap as nm
    monkeypatch.setattr(nm, "MAX_MAP_BUSES", 10)
    d, _ = _dash(tmp_path)
    nav = re.search(r"<nav class='nav'.*?</nav>", d, re.S).group(0)
    assert "data-view='map'" not in nav and "Network map omitted" in d and "or on the map" not in d


def test_dashboard_report_and_results_agree(tmp_path):
    d, r = _dash(tmp_path)
    for row in re.findall(r"<tr class='res'[^>]*>", r):
        assert row in d
    assert scr_screen.__version__ in d
