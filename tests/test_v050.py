"""v0.5.0: voltage-base conversion, nominal-ratio note, negative-reactance answer, exact report data, dashboard."""

from __future__ import annotations

import json
import math
import re
import warnings
from pathlib import Path

import pytest

import scr_screen
from scr_screen.check import check_network
from scr_screen.classical import build_zbus, off_nominal_transformers
from scr_screen.cli import main
from scr_screen.dashboard import VIEWS, render_dashboard, thevenin_data
from scr_screen.loaders import load_network
from scr_screen.report import SCRIPT
from scr_screen.triage import NEGATIVE_X, Nearby, PoiInfo, fixed_triggers, thevenin

EX = Path(__file__).resolve().parents[1] / "examples"
NET = EX / "ieee39_assumed.json"
GROUPS = EX / "ieee39_groups_example.csv"


def _read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _v6(v_gen=230.0, v_lv=34.5, v_hv=230.0):
    """Verification V6: a 220 kV / 33 kV system with equipment rated 230 kV / 34.5 kV."""
    import pandapower as pp

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        net = pp.create_empty_network(sn_mva=100)
        b1 = pp.create_bus(net, vn_kv=220.0, name="1")
        b2 = pp.create_bus(net, vn_kv=33.0, name="2")
        pp.create_gen(net, b1, p_mw=0.0, vn_kv=v_gen, sn_mva=1000.0, xdss_pu=0.20, rdss_ohm=0.0, cos_phi=0.85)
        pp.create_transformer_from_parameters(net, hv_bus=b1, lv_bus=b2, sn_mva=100.0, vn_hv_kv=v_hv, vn_lv_kv=v_lv,
                                              vk_percent=12.0, vkr_percent=0.4, pfe_kw=0.0, i0_percent=0.0)
    return net, b1, b2


def _scmva(net, bus):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        zb = build_zbus(net)
    return 100.0 / abs(zb.z[zb.pos[bus], zb.pos[bus]]), zb


# --- Voltage base (V6) ------------------------------------------------------------------

def test_v6_voltage_base_hand_values():
    net, b1, b2 = _v6()
    s1, zb = _scmva(net, b1)
    s2, _ = _scmva(net, b2)
    k = (34.5 / 33.0) ** 2                       # = (230 / 220)^2 = 1.0929752
    xg = 0.20 * 100 / 1000 * k
    zt = complex(0.004, math.sqrt(0.12 ** 2 - 0.004 ** 2)) * k
    assert s1 == pytest.approx(100 / xg, rel=1e-12)
    assert s2 == pytest.approx(100 / abs(zt + 1j * xg), rel=1e-12)
    assert round(s1, 3) == 4574.669 and round(s2, 3) == 653.569     # the hand worksheet's values
    assert any(n.startswith("Voltage base: 1 transformer(s) and 1 generator(s)") for n in zb.notes)
    assert off_nominal_transformers(net) == (1, 0)                  # same ratio as the buses: 230/34.5 = 220/33


def test_rated_voltages_equal_to_bus_voltages_change_nothing():
    net, b1, b2 = _v6(v_gen=220.0, v_lv=33.0, v_hv=220.0)
    s2, zb = _scmva(net, b2)
    assert s2 == pytest.approx(100 / abs(complex(0.004, math.sqrt(0.12 ** 2 - 0.004 ** 2) + 0.02)), rel=1e-12)
    assert round(s2, 3) == 714.334                                   # what v0.4.0 gave for V6 (9.3 % higher)
    assert not any(n.startswith(("Voltage base:", "Nominal ratio:")) for n in zb.notes)


def test_off_nominal_ratio_is_reported_not_modeled():
    net, b1, b2 = _v6(v_hv=242.0)                                     # 242/34.5 differs from 220/33
    base, _ = _scmva(_v6()[0], b2)
    s2, zb = _scmva(net, b2)
    assert s2 == pytest.approx(base, rel=1e-12)                       # the nominal ratio is used
    assert any(n.startswith("Nominal ratio: 1 transformer(s)") for n in zb.notes)
    assert off_nominal_transformers(net) == (1, 1)


def test_ieee39_example_values_are_unchanged_and_taps_are_reported(tmp_path, capsys):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        net = load_network(NET)
    assert off_nominal_transformers(net) == (0, 11)
    names = {str(n): i for i, n in net.bus["name"].items()}
    s12, _ = _scmva(net, names["12"])
    assert round(s12, 1) == 2832.4                                    # V1, unchanged since v0.1
    texts = [f.message for f in check_network(net).findings]
    assert any("11 transformer(s)" in t and "not modeled" in t for t in texts)
    out = tmp_path / "r.html"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--report", str(out)]) == 0
    assert "Nominal ratio: 11 transformer(s)" in _read(out)


# --- Negative reactance and the series_compensation answer ---------------------------------

def test_negative_reactance_line_can_be_answered_no():
    dev = [Nearby("series compensation", f"line 4 ({NEGATIVE_X})", "Bus 1–Bus 2", 0.9, True)]
    trig = fixed_triggers([], dev, None)
    assert len(trig) == 1 and trig[0].level == 1 and "series_compensation = no" in trig[0].detail
    assert fixed_triggers([], dev, PoiInfo({"series_compensation": "unknown"}, None)) != []
    assert fixed_triggers([], dev, PoiInfo({"series_compensation": "no"}, None)) == []
    yes = fixed_triggers([], dev, PoiInfo({"series_compensation": "yes"}, None))
    assert [t.source for t in yes] == ["model", "user"]
    # other devices are not affected by the answer
    facts = [Nearby("FACTS", "svc 0", "Bus 1", 0.9, True)]
    assert len(fixed_triggers([], facts, PoiInfo({"series_compensation": "no"}, None))) == 1


# --- Report data: the live values equal the Python values exactly -----------------------------

def test_report_data_attributes_round_trip_exactly(tmp_path):
    rep, out = tmp_path / "r.html", tmp_path / "r.json"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--n1", "--report", str(rep), "--out", str(out)]) == 0
    html = _read(rep)
    plants = {p["plant_id"]: p for p in json.loads(_read(out))["plants"]}
    rows = re.findall(r"<tr class='res'[^>]*data-scmva='([^']+)'[^>]*data-pid='([^']+)'[^>]*data-n1='([^']+)'", html)
    assert len(rows) == 39
    for scmva, pid, n1 in rows:
        assert float(scmva) == plants[pid]["scmva"]                   # exact, not approximately
        assert float(n1) / 1500.0 == pytest.approx(plants[pid]["n1_scr"], rel=1e-15)


# --- Dashboard ------------------------------------------------------------------------------

def _scan(tmp_path, *extra, name="d.html"):
    out = tmp_path / name
    assert main(["scan", str(NET), "--plant-mw", "1500", "--groups", str(GROUPS), *extra]) == 0
    return out


def _strip_time(html: str) -> str:
    return re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d UTC", "T", html)


def test_dashboard_keeps_everything_in_the_report(tmp_path, capsys):
    dash, rep = tmp_path / "d.html", tmp_path / "r.html"
    cost = ["--cost", "--condenser-cost-per-mva", "100000"]
    _scan(tmp_path, *cost, "--dashboard", str(dash))
    assert "Dashboard written:" in capsys.readouterr().out
    _scan(tmp_path, *cost, "--n1", "--emt-triage", "--report", str(rep))
    d, r = _read(dash), _read(rep)
    assert d.count(SCRIPT) == 1                                       # the report's own script, unchanged
    titles = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<h2>(.*?)</h2>", r)]
    assert len(titles) == 10
    for t in re.findall(r"<h2>.*?</h2>", r):
        assert t in d
    for pattern in (r"<tr class='res'[^>]*>.*?</tr>", r"<tr class='trirow'.*?</tr>", r"<div class='card'>.*?</div></div>",
                    r"<div class='gbox'.*?</div></div>", r"<g class='bus[^>]*>", r"<li>.*?</li>",
                    r"<input id='[^']+'[^>]*>"):
        found = re.findall(pattern, r, re.S)
        assert found, pattern
        for piece in found:
            assert piece in d, piece[:80]
    cfg = re.search(r"<script type='application/json' id='scr-cfg'>(.*?)</script>", r, re.S).group(0)
    assert cfg in d
    assert "<div class='disc'>" not in d and re.search(r"<div class='disc'>(.*?)</div>", r, re.S).group(1) in d
    for key, label, _ in VIEWS:
        assert f"data-view='{key}'" in d, label
    assert d.count("<svg") == r.count("<svg") and d.count("id='mw-num'") == 1
    assert "http://" not in re.sub(r"http://www\.w3\.org/\d+/svg", "", d) and "https://" not in d   # self-contained


def test_dashboard_does_not_change_the_report_or_results(tmp_path):
    a, b, d = tmp_path / "a.html", tmp_path / "b.html", tmp_path / "d.html"
    ca, cb = tmp_path / "a.csv", tmp_path / "b.csv"
    _scan(tmp_path, "--n1", "--emt-triage", "--report", str(a), "--out", str(ca))
    _scan(tmp_path, "--dashboard", str(d), "--report", str(b), "--out", str(cb))
    assert _strip_time(_read(a)) == _strip_time(_read(b))
    assert _strip_time(_read(ca)) == _strip_time(_read(cb))


def test_dashboard_thevenin_data_matches_triage(tmp_path):
    dash, tri = tmp_path / "d.html", tmp_path / "t.json"
    _scan(tmp_path, "--dashboard", str(dash))
    assert main(["triage", str(NET), "--buses", "38,12,16", "--plant-mw", "1500", "--out", str(tri)]) == 0
    data = json.loads(re.search(r"<script type='application/json' id='scr-dash'>(.*?)</script>", _read(dash),
                                re.S).group(1))
    assert data["version"] == scr_screen.__version__ and len(data["buses"]) == 39
    assert data["cmd"].startswith("scr-screen triage ieee39_assumed.json --buses {bus} --plant-mw {size}")
    for poi in json.loads(_read(tri))["pois"]:
        b = data["buses"][poi["poi_id"]]
        intact, n1 = poi["conditions"][0], poi["conditions"][1]
        assert b["kv"] == intact["kv"]
        assert b["z"] == pytest.approx([intact["r_ohm"], intact["x_ohm"], intact["z_ohm"]], rel=1e-12)
        assert b["xr"] == pytest.approx(intact["x_over_r"], rel=1e-12)
        assert b["ka"] == pytest.approx(intact["isc_ka"], rel=1e-12)
        assert b["zn"] == pytest.approx([n1["r_ohm"], n1["x_ohm"], n1["z_ohm"]], rel=1e-12)
        assert b["xrn"] == pytest.approx(n1["x_over_r"], rel=1e-12)


def test_thevenin_data_formulas():
    z = complex(0.002, 0.04)
    t, d = thevenin("intact", "", z, 345.0, 500.0), thevenin_data(345.0, z, complex(0.0, 0.08))
    assert d["z"] == pytest.approx([t.r_ohm, t.x_ohm, t.z_ohm]) and d["ka"] == pytest.approx(t.isc_ka)
    assert d["xr"] == pytest.approx(20.0) and d["xrn"] is None and d["zn"][2] == pytest.approx(0.08 * 345 ** 2 / 100)
    assert "zn" not in thevenin_data(345.0, z)


def test_dashboard_with_iec_method_and_custom_title(tmp_path):
    dash = tmp_path / "d.html"
    assert main(["scan", str(NET), "--plant-mw", "800", "--method", "iec60909", "--dashboard", str(dash),
                 "--title", "My <study>"]) == 0
    d = _read(dash)
    assert "<h1>My &lt;study&gt;</h1>" in d
    assert "data-view='tri'" not in d and "data-view='n1'" not in d and "data-view='rank'" in d
    data = json.loads(re.search(r"id='scr-dash'>(.*?)</script>", d, re.S).group(1))
    assert "cmd" not in data and data["buses"]["Bus 12"] == {"kv": 345.0}


def test_default_title_and_sections_without_groups(tmp_path):
    dash = tmp_path / "d.html"
    assert main(["scan", str(NET), "--plant-mw", "800", "--dashboard", str(dash)]) == 0
    d = _read(dash)
    assert "<title>SCR-Screen dashboard</title>" in d and "<h1>SCR-Screen dashboard</h1>" in d
    assert "data-view='groups'" not in d and "data-view='cost'" not in d
    assert "data-view='tri'" in d and "data-view='n1'" in d             # added by --dashboard (classical)


def test_cost_inputs_move_to_the_cost_view(tmp_path):
    dash = tmp_path / "d.html"
    _scan(tmp_path, "--cost", "--condenser-cost-per-mva", "100000", "--dashboard", str(dash))
    d = _read(dash)
    top = d[d.index("<div class='dctl'>"):d.index("<div class='kpis'>")]
    cost = d[d.index("<section class='view' data-v='cost'>"):]
    assert "id='mw-num'" in top and "id='in-wk'" in top and "id='in-cpm'" not in top
    assert "id='in-cpm'" in cost[:cost.index("</section>")]


def test_unknown_sections_are_kept_and_non_scan_reports_are_refused(tmp_path):
    rep = tmp_path / "r.html"
    _scan(tmp_path, "--report", str(rep))
    html = _read(rep).replace("<h2>Method and assumptions</h2>", "<h2>Something new</h2><p>kept</p>"
                              "<h2>Method and assumptions</h2>", 1)
    d = render_dashboard(html)
    assert "<h2>Something new</h2><p>kept</p>" in d
    with pytest.raises(ValueError):
        render_dashboard("<html><body><div class='wrap'><h2>x</h2></div></body></html>")


def test_run_and_triage_have_no_dashboard_option(capsys):
    for cmd in (["run", "x.csv"], ["triage", "x.json", "--buses", "1", "--plant-mw", "5"]):
        with pytest.raises(SystemExit):
            main([*cmd, "--dashboard", "d.html"])
    assert "unrecognized arguments" in capsys.readouterr().err


def test_version():
    assert scr_screen.__version__ == "0.5.0"
