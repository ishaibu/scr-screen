"""Network-aware strength metrics (v0.3.0): interaction factors, SCRIF, CSCR, ESCR, N-1,
suggested groups, the shared IEEE 39-bus drawing, and the heat-map report.

Expected values are hand-calculated or come from an independent calculation path
(rebuilding the network), never from the code under test.
"""

import copy
import itertools
import json
import math
from pathlib import Path

import pandapower as pp
import pytest

from scr_screen.classical import build_zbus, scmva_classical
from scr_screen.cli import main
from scr_screen.loaders import load_network
from scr_screen.strength import (capacitor_mvar, composite_scmva, interaction_factor, n1_worst, scrif,
                                 suggest_groups)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
NET = str(EXAMPLES / "ieee39_assumed.json")
GROUPS = str(EXAMPLES / "ieee39_groups_example.csv")
pytestmark = pytest.mark.filterwarnings("ignore")


def radial3():
    """Source (1000 MVA, R/X 0.1) - 50 km line - bus 1 - 50 km line - bus 2, at 138 kV."""
    net = pp.create_empty_network()
    b0, b1, b2 = (pp.create_bus(net, vn_kv=138, name=str(k)) for k in range(3))
    pp.create_ext_grid(net, b0, s_sc_max_mva=1000, rx_max=0.1)
    for a, b in ((b0, b1), (b1, b2)):
        pp.create_line_from_parameters(net, a, b, length_km=50, r_ohm_per_km=0.04, x_ohm_per_km=0.4,
                                       c_nf_per_km=0, max_i_ka=1)
    return net


def hand_impedances():
    zmag = 100 / 1000
    xs = zmag / math.sqrt(1 + 0.1**2)
    zs = complex(0.1 * xs, xs)
    zl = complex(0.04, 0.4) * 50 / (138**2 / 100)
    return zs, zl


# --- Interaction factors and SCRIF ---------------------------------------------

def test_interaction_factor_hand_calculation():
    zs, zl = hand_impedances()
    zb = build_zbus(radial3())
    # Injection at bus 2 moves bus 1 by (Zs+Zl)/(Zs+2Zl); injection at bus 1 moves bus 2 equally.
    assert interaction_factor(zb, 1, 2) == pytest.approx(abs((zs + zl) / (zs + 2 * zl)), rel=1e-12)
    assert interaction_factor(zb, 2, 1) == pytest.approx(1.0, rel=1e-12)
    assert interaction_factor(zb, 1, 1) == 1.0


def test_scrif_formula_and_bounds():
    s = {1: 1000.0, 2: 600.0}
    p = {1: 200.0, 2: 100.0}
    ifs = {(1, 2): 0.5, (2, 1): 0.8, (1, 1): 1, (2, 2): 1}
    out = scrif(s, p, ifs)
    assert out[1] == pytest.approx(1000 / (200 + 0.5 * 100))
    assert out[2] == pytest.approx(600 / (100 + 0.8 * 200))
    # With no interaction SCRIF = SCR; it never exceeds SCR
    none = scrif(s, p, {(1, 2): 0, (2, 1): 0, (1, 1): 1, (2, 2): 1})
    assert none == {1: pytest.approx(5.0), 2: pytest.approx(6.0)}


def test_scrif_between_scr_and_wscr_for_close_buses_on_ieee39(tmp_path):
    out = tmp_path / "r.json"
    assert main(["scan", NET, "--plant-mw", "1500", "--groups", GROUPS, "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    plants = {p["plant_id"]: p for p in data["plants"]}
    for g in data["groups"]:
        for pid in g["plant_ids"]:
            assert g["wscr"] <= plants[pid]["scrif"] <= plants[pid]["scr"]
    assert plants["Bus 11"]["scrif"] == pytest.approx(2.528, abs=5e-4)
    assert plants["Bus 13"]["scrif"] == pytest.approx(2.397, abs=5e-4)


# --- CSCR ------------------------------------------------------------------------

def test_composite_scmva_single_bus_equals_scmva():
    net = load_network(NET)
    zb = build_zbus(net)
    values, _ = scmva_classical(net, [11])
    assert composite_scmva(zb, [11]) == pytest.approx(values[11], rel=1e-12)


@pytest.mark.parametrize("group", [[10, 12], [25, 27, 28], [3, 28]])
def test_composite_scmva_matches_buses_tied_with_tiny_lines(group):
    net = load_network(NET)
    tied = copy.deepcopy(net)
    for b in group[1:]:
        pp.create_line_from_parameters(tied, group[0], b, length_km=1, r_ohm_per_km=1e-7,
                                       x_ohm_per_km=1e-6, c_nf_per_km=0, max_i_ka=1)
    brute, _ = scmva_classical(tied, [group[0]])
    assert composite_scmva(build_zbus(net), group) == pytest.approx(brute[group[0]], rel=1e-6)


# --- ESCR --------------------------------------------------------------------------

def test_escr_subtracts_capacitor_mvar(tmp_path):
    net = radial3()
    pp.create_shunt(net, 2, q_mvar=-50, p_mw=0)      # 50 Mvar capacitor
    pp.create_shunt(net, 2, q_mvar=20, p_mw=0)       # reactor: not subtracted
    assert capacitor_mvar(net) == {2: pytest.approx(50.0)}
    path = tmp_path / "net.json"
    pp.to_json(net, str(path))
    out = tmp_path / "r.json"
    assert main(["scan", str(path), "--plant-mw", "100", "--out", str(out), "--no-compare"]) == 0
    p = {x["plant_id"]: x for x in json.loads(out.read_text(encoding="utf-8"))["plants"]}
    assert p["Bus 2"]["escr"] == pytest.approx((p["Bus 2"]["scmva"] - 50) / 100)
    assert p["Bus 1"]["escr"] == pytest.approx(p["Bus 1"]["scr"])


# --- N-1 -----------------------------------------------------------------------------

def test_n1_matches_full_rebuild_for_every_outage():
    net = load_network(NET)
    zb = build_zbus(net)
    buses = list(zb.pos)
    fast = n1_worst(zb, buses)
    base, _ = scmva_classical(net, buses)
    worst = dict(base)
    for table in ("line", "trafo"):
        for idx in net[table].index:
            m = copy.deepcopy(net)
            m[table].at[idx, "in_service"] = False
            values, _ = scmva_classical(m, buses, skip_isolated=True)
            for b, v in values.items():
                worst[b] = min(worst[b], v)
    assert fast.studied == 46 and not fast.skipped
    for b in buses:
        assert fast.scmva[b] == pytest.approx(worst[b], rel=1e-9)


def test_n1_skips_outages_that_island_buses():
    """In a radial network every outage leaves buses with no source, so both are skipped."""
    net = radial3()
    zb = build_zbus(net)
    res = n1_worst(zb, [0, 1, 2])
    base, _ = scmva_classical(net, [0, 1, 2])
    assert res.studied == 0 and len(res.skipped) == 2
    assert res.scmva == pytest.approx(base) and set(res.outage.values()) == {"none"}


def test_n1_parallel_circuit_removes_one_circuit_only():
    net = radial3()
    net.line.at[0, "parallel"] = 2
    zb = build_zbus(net)
    res = n1_worst(zb, [1])
    zs, zl = hand_impedances()
    # One of the two parallel circuits out: bus 1 sees Zs + Zl (instead of Zs + Zl/2)
    assert res.scmva[1] == pytest.approx(100 / abs(zs + zl), rel=1e-9)


def test_scan_n1_requires_classical(capsys):
    assert main(["scan", NET, "--plant-mw", "1500", "--method", "iec60909", "--n1"]) == 2
    assert "classical method" in capsys.readouterr().err


def test_scan_n1_outputs(tmp_path):
    out = tmp_path / "r.json"
    assert main(["scan", NET, "--plant-mw", "1500", "--n1", "--out", str(out)]) == 0
    p = {x["plant_id"]: x for x in json.loads(out.read_text(encoding="utf-8"))["plants"]}
    assert p["Bus 28"]["n1_scr"] == pytest.approx(0.974, abs=5e-4)
    assert "Bus 28–Bus 29" in p["Bus 28"]["n1_outage"]
    assert all(x["n1_scr"] <= x["scr"] + 1e-12 for x in p.values())


# --- Suggested groups ------------------------------------------------------------------

def test_suggest_groups_complete_linkage_avoids_chains():
    ifs = {(a, b): 0.0 for a in "abc" for b in "abc"}
    ifs.update({("a", "b"): 0.6, ("b", "c"): 0.6, ("a", "c"): 0.1, ("b", "a"): 0.6, ("c", "b"): 0.6, ("c", "a"): 0.1})
    groups = suggest_groups(ifs, ["a", "b", "c"], 0.5)
    assert len(groups) == 1 and len(groups[0]) == 2       # a-b or b-c, never all three


def test_interactions_command_suggests_groups_usable_by_scan(tmp_path, capsys):
    out = tmp_path / "g.csv"
    assert main(["interactions", NET, "--buses", "4,11,12,13,16,17,26,28,29", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "G1: Bus 4, Bus 11, Bus 12, Bus 13" in text and "G2: Bus 16, Bus 17" in text
    assert "G3: Bus 26, Bus 28, Bus 29" in text
    assert main(["scan", NET, "--plant-mw", "500", "--groups", str(out)]) == 0


@pytest.mark.parametrize("args, msg", [
    (["--buses", "11"], "at least two"),
    (["--buses", "11,999"], "not found"),
    (["--buses", "11,13", "--threshold", "0"], "threshold"),
])
def test_interactions_errors(args, msg, capsys):
    assert main(["interactions", NET] + args) == 2
    assert msg in capsys.readouterr().err


# --- Shared IEEE 39-bus drawing and heat map -------------------------------------------

def _segments_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = orient(p3, p4, p1), orient(p3, p4, p2), orient(p1, p2, p3), orient(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def test_ieee39_drawing_positions_complete_and_no_lines_cross():
    net = load_network(NET)
    pos = {}
    for b in net.bus.index:
        geo = json.loads(net.bus.at[b, "geo"])
        assert geo["drawing"] is True
        pos[b] = tuple(geo["coordinates"])
    assert len(pos) == 39
    edges = [(r.from_bus, r.to_bus) for r in net.line.itertuples()] + \
            [(r.hv_bus, r.lv_bus) for r in net.trafo.itertuples()]
    assert len(edges) == 46
    for (a, b), (c, d) in itertools.combinations(edges, 2):
        if {a, b} & {c, d}:
            continue
        assert not _segments_cross(pos[a], pos[b], pos[c], pos[d]), (a, b, c, d)


def test_report_map_uses_drawing_and_heat_controls(tmp_path):
    rep = tmp_path / "r.html"
    assert main(["scan", NET, "--plant-mw", "1500", "--n1", "--report", str(rep), "--no-compare"]) == 0
    html = rep.read_text(encoding="utf-8")
    assert "one-line drawing of this network" in html and "not geographic" in html
    assert "id='heat-toggle'" in html and "scr-heat-blur" in html and "id='map-mode'" in html
    assert "Worst single outage (N-1)" in html and "id='card-n1'" in html
    rep2 = tmp_path / "r2.html"
    assert main(["scan", NET, "--plant-mw", "1500", "--report", str(rep2), "--no-compare", "--no-heatmap"]) == 0
    html2 = rep2.read_text(encoding="utf-8")
    assert "scr-heat-blur" not in html2 and "id='map-mode'" not in html2


def test_results_unchanged_by_new_features(tmp_path):
    """v0.3 adds columns; SCR, flags and WSCR are exactly as before."""
    out = tmp_path / "r.json"
    assert main(["scan", NET, "--plant-mw", "1500", "--groups", GROUPS, "--n1", "--out", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    p = {x["plant_id"]: x for x in d["plants"]}
    assert p["Bus 12"]["scr"] == pytest.approx(1.888, abs=5e-4) and p["Bus 12"]["flag"] == "very weak"
    g = {x["group"]: x for x in d["groups"]}
    assert g["G1"]["wscr"] == pytest.approx(2.197, abs=5e-4)
    assert g["G1"]["cscr"] == pytest.approx(7391.031 / 3000, rel=1e-6)
