"""v0.4.0: EMT triage (scr-screen triage, scan --emt-triage), Thevenin data, devices, nearby IBRs, POI information."""

from __future__ import annotations

import copy
import csv
import json
import math
import warnings
from pathlib import Path

import pytest

from scr_screen.classical import build_zbus
from scr_screen.cli import main
from scr_screen.loaders import load_network
from scr_screen.metrics import InputError
from scr_screen.settings import Thresholds
from scr_screen.strength import n1_worst
from scr_screen.triage import (USER_FIELDS, Nearby, PoiInfo, detect_devices, pair_interaction, prepare_network,
                               read_poi_info, thevenin, triage_poi)

EX = Path(__file__).resolve().parents[1] / "examples"
NET = EX / "ieee39_assumed.json"
TRI = EX / "ieee39_triage_example.json"
TH = Thresholds()


def _net(path=NET):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_network(path)


def _zb(net):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return build_zbus(net)


def _bus(net, name):
    return int(net.bus.index[net.bus["name"].astype(str) == str(name)][0])


# --- Thevenin data -------------------------------------------------------------------

def test_thevenin_formulas():
    t = thevenin("intact", "", complex(0.002, 0.03), 345.0, 1500.0)
    base = 345.0 ** 2 / 100
    assert t.z_pu == pytest.approx(abs(complex(0.002, 0.03)))
    assert t.r_ohm == pytest.approx(0.002 * base) and t.x_ohm == pytest.approx(0.03 * base)
    assert t.z_ohm == pytest.approx(t.z_pu * base)
    assert t.x_over_r == pytest.approx(15.0)
    assert t.scmva == pytest.approx(100 / t.z_pu)
    assert t.isc_ka == pytest.approx(t.scmva / (math.sqrt(3) * 345.0))
    assert t.scr == pytest.approx(t.scmva / 1500) and t.escr is None
    assert thevenin("intact", "", complex(0.002, 0.03), 345.0, 1500.0, qc=200).escr == pytest.approx(
        (t.scmva - 200) / 1500)
    assert thevenin("intact", "", complex(0, 0.03), 345.0, 1.0).x_over_r is None


def test_intact_thevenin_matches_scan_for_every_bus(tmp_path):
    out = tmp_path / "scan.csv"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--out", str(out)]) == 0
    scan = {r["id"]: float(r["scmva"]) for r in csv.DictReader(out.open(encoding="utf-8")) if r["type"].startswith("plant")}
    net, zb = _net(), None
    zb = _zb(net)
    for b, k in zb.pos.items():
        lab = f"Bus {net.bus.at[b, 'name']}"
        t = thevenin("intact", "", complex(zb.z[k, k]), 345.0, 1500.0)
        assert t.scmva == pytest.approx(scan[lab], abs=0.006)


def test_n1_complex_impedance_matches_full_rebuild():
    net = _net()
    zb = _zb(net)
    b12 = _bus(net, 12)
    n1 = n1_worst(zb, [b12])
    assert abs(n1.zth[b12]) == pytest.approx(100 / n1.scmva[b12])
    assert n1.outage[b12].startswith("transformer 3")
    other = copy.deepcopy(net)
    other.trafo.at[3, "in_service"] = False
    zr = _zb(other)
    z = complex(zr.z[zr.pos[b12], zr.pos[b12]])
    assert n1.zth[b12].real == pytest.approx(z.real, rel=1e-9)
    assert n1.zth[b12].imag == pytest.approx(z.imag, rel=1e-9)


def test_n1result_still_built_with_four_fields():
    from scr_screen.strength import N1Result

    r = N1Result({1: 2.0}, {1: "none"}, 0, [])
    assert r.zth == {}


# --- Model checks -------------------------------------------------------------------------

def test_assumed_ibrs_do_not_change_any_scr(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--n1", "--out", str(a)]) == 0
    assert main(["scan", str(TRI), "--plant-mw", "1500", "--n1", "--out", str(b)]) == 0
    strip = lambda p: [r[:11] + r[12:] for r in csv.reader(p.open(encoding="utf-8"))]  # noqa: E731  (drop run_utc)
    ra, rb = strip(a), strip(b)
    assert [r[:9] + r[11:] for r in ra] == [r[:9] + r[11:] for r in rb]  # method_source names the file


def test_pair_interaction_is_max_of_both_directions():
    net = _net()
    zb = _zb(net)
    i, j = _bus(net, 12), _bus(net, 4)
    a, b = zb.pos[i], zb.pos[j]
    want = max(abs(zb.z[a, b] / zb.z[b, b]), abs(zb.z[b, a] / zb.z[a, a]))
    assert pair_interaction(zb, i, j) == pytest.approx(want)
    assert pair_interaction(zb, i, i) == 1.0
    assert pair_interaction(zb, i, 10_000) is None


def test_detect_devices_and_prepare_network():
    import pandapower as pp

    net = _net()
    ln = int(net.line.index[0])
    net.line.at[ln, "x_ohm_per_km"] = -abs(net.line.at[ln, "x_ohm_per_km"])
    pp.create_svc(net, bus=_bus(net, 12), x_l_ohm=1, x_cvar_ohm=-10, set_vm_pu=1.0, thyristor_firing_angle_degree=90,
                  name="SVC test")
    pp.create_dcline(net, from_bus=_bus(net, 16), to_bus=_bus(net, 28), p_mw=100, loss_percent=1, loss_mw=1,
                     vm_from_pu=1.0, vm_to_pu=1.0, name="HVdc test")
    kinds = sorted(d.kind for d in detect_devices(net))
    assert kinds == ["FACTS", "HVdc", "series compensation"]
    notes = prepare_network(net)
    assert not bool(net.dcline["in_service"].any()) and any("dcline" in n for n in notes)
    _zb(net)  # computable after preparation


def test_tcsc_is_refused_with_guidance():
    import pandapower as pp

    net = _net()
    pp.create_tcsc(net, from_bus=_bus(net, 16), to_bus=_bus(net, 17), x_l_ohm=1, x_cvar_ohm=-10, set_p_to_mw=10,
                   thyristor_firing_angle_degree=135)
    with pytest.raises(InputError, match="TCSC"):
        prepare_network(net)


# --- Priority logic ---------------------------------------------------------------------------

def _cond(scr, label="intact"):
    return thevenin(label, "", complex(0, 100 / (scr * 100)), 345.0, 100.0)


def _near(kind="IBR", near=True):
    return Nearby(kind, "x", "Bus 1", 0.8 if near else 0.2, near)


@pytest.mark.parametrize("scrs,ibrs,devs,ans,oem,want", [
    ([5.0, 4.0], [], [], {}, None, 3),
    ([5.0, 2.5], [], [], {}, None, 2),                     # weak in N-1
    ([5.0, 1.9], [], [], {}, None, 1),                     # very weak in N-1
    ([5.0, 4.0], [_near()], [], {}, None, 2),              # other IBRs nearby
    ([5.0, 4.0], [_near(near=False)], [], {}, None, 3),    # IBR below the threshold
    ([5.0, 4.0], [], [_near("HVdc")], {}, None, 1),        # HVdc nearby (found)
    ([5.0, 4.0], [], [_near("FACTS", near=False)], {}, None, 3),
    ([5.0, 4.0], [], [], {"ras": "yes"}, None, 2),
    ([5.0, 4.0], [], [], {"series_compensation": "yes"}, None, 1),
    ([5.0, 4.0], [], [], {"hvdc_nearby": "unknown"}, None, 3),
    ([5.0, 4.0], [], [], {"unexplained_system_event": "yes"}, None, 1),   # NERC: a new EMT study is needed
    ([5.0, 4.0], [], [], {"rms_stability_concerns": "yes"}, None, 2),
    ([5.0, 4.0], [], [], {"pre_existing_oscillation": "yes"}, None, 2),
    ([5.0, 4.0], [], [], {k: "no" for k in USER_FIELDS}, None, 3),
    ([5.0, 4.0], [], [], {}, 4.5, 1),                      # below the OEM minimum SCR
    ([5.0, 4.0], [], [], {}, 3.5, 3),
])
def test_priority_rules(scrs, ibrs, devs, ans, oem, want):
    conds = [_cond(scrs[0]), _cond(scrs[1], "N-1")]
    answers = {k: "unknown" for k in USER_FIELDS} | ans
    it = triage_poi("Bus 1", 1, 345.0, 100.0, "MW", conds, TH, ibrs, devs, PoiInfo(answers, oem))
    assert it.level == want
    assert len(it.unknown) == sum(v == "unknown" for v in answers.values())


def test_group_metrics_trigger():
    it = triage_poi("Bus 1", 1, 345.0, 100.0, "MW", [_cond(5.0)], TH, [], [], None, "G1", 2.2, 3.5, 3.4)
    assert it.level == 2 and any("WSCR" in t.detail for t in it.triggers)
    it = triage_poi("Bus 1", 1, 345.0, 100.0, "MW", [_cond(5.0)], TH, [], [], None, "G1", 3.2, 1.5, 3.4)
    assert it.level == 1


# --- POI information file ----------------------------------------------------------------------

def _write(tmp_path, text):
    p = tmp_path / "info.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_read_poi_info_example_and_all_row():
    info = read_poi_info(EX / "ieee39_poi_info_example.csv")
    assert info["28"].oem_min_scr == 3.0 and info["all"].oem_min_scr is None
    assert info["all"].answers["series_compensation"] == "no"
    assert info["all"].answers["ras"] == "unknown"


@pytest.mark.parametrize("text,msg", [
    ("poi,ras\n12,maybe\n", "yes, no or unknown"),
    ("poi,colour\n12,red\n", "unknown column"),
    ("ras\nyes\n", "'poi' column"),
    ("poi,ras\n12,yes\nBus 12,no\n", "more than once"),
    ("poi,oem_min_scr\n12,0\n", "greater than zero"),
    ("poi,oem_min_scr\n12,abc\n", "a number"),
])
def test_read_poi_info_errors(tmp_path, text, msg):
    with pytest.raises(InputError, match=msg):
        read_poi_info(_write(tmp_path, text))


# --- Command line ----------------------------------------------------------------------------

def test_triage_command_outputs(tmp_path, capsys):
    rep, out, js = tmp_path / "t.html", tmp_path / "t.csv", tmp_path / "t.json"
    args = ["triage", str(TRI), "--buses", "12,16,28", "--plant-mw", "500",
            "--poi-info", str(EX / "ieee39_poi_info_example.csv")]
    assert main(args + ["--report", str(rep), "--out", str(out)]) == 0
    assert main(args + ["--out", str(js)]) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    level = {r["poi"]: int(r["priority"]) for r in rows}
    assert level == {"Bus 28": 1, "Bus 12": 2, "Bus 16": 3}
    assert {r["condition"] for r in rows} == {"intact", "N-1"}
    data = json.loads(js.read_text(encoding="utf-8"))
    assert [p["poi_id"] for p in data["pois"]] == ["Bus 28", "Bus 12", "Bus 16"]
    html = rep.read_text(encoding="utf-8")
    assert "system strength data sheet" in html and "should not rule out the need for EMT studies" in html
    assert "ASSUMED existing solar A (illustrative)" in html


def test_triage_min_generation_and_groups(tmp_path):
    out = tmp_path / "t.csv"
    assert main(["triage", str(NET), "--buses", "11,12,13,16,17", "--plant-mw", "1500", "--groups",
                 str(EX / "ieee39_groups_example.csv"), "--gen-out", "38,39", "--out", str(out)]) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    g1 = {r["poi"]: r for r in rows if r["condition"] == "intact" and r["group"] == "G1"}
    assert float(g1["Bus 11"]["wscr"]) == pytest.approx(2.197, abs=5e-4)
    assert float(g1["Bus 11"]["cscr"]) == pytest.approx(2.464, abs=5e-4)
    assert float(g1["Bus 11"]["scrif"]) == pytest.approx(2.528, abs=5e-4)
    assert float(g1["Bus 13"]["scrif"]) == pytest.approx(2.397, abs=5e-4)
    # minimum generation equals a scan with those generators out
    scan = tmp_path / "s.csv"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--gen-out", "38,39", "--out", str(scan)]) == 0
    s = {r["id"]: float(r["scmva"]) for r in csv.DictReader(scan.open(encoding="utf-8")) if r["type"].startswith("plant")}
    for r in rows:
        if r["condition"] == "minimum generation":
            assert float(r["scmva"]) == pytest.approx(s[r["poi"]], abs=0.006)


def test_scan_triage_matches_triage_command(tmp_path):
    scan = tmp_path / "s.csv"
    assert main(["scan", str(TRI), "--plant-mw", "500", "--emt-triage", "--out", str(scan)]) == 0
    rows = [r for r in csv.DictReader(scan.open(encoding="utf-8")) if r["type"].startswith("plant")]
    lev = {r["id"]: int(r["emt_priority"]) for r in rows}
    out = tmp_path / "t.csv"
    buses = ",".join(k[4:] for k in lev)
    assert main(["triage", str(TRI), "--buses", buses, "--plant-mw", "500", "--out", str(out)]) == 0
    tri = {r["poi"]: int(r["priority"]) for r in csv.DictReader(out.open(encoding="utf-8"))}
    assert tri == lev


def test_scan_triage_counts_and_columns(tmp_path, capsys):
    out, js, rep = tmp_path / "s.csv", tmp_path / "s.json", tmp_path / "s.html"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--groups", str(EX / "ieee39_groups_example.csv"),
                 "--emt-triage", "--out", str(out), "--report", str(rep)]) == 0
    assert "Priority 1: 18  Priority 2: 14  Priority 3: 7" in capsys.readouterr().out
    head = next(csv.reader(out.open(encoding="utf-8")))
    assert head[-2:] == ["emt_priority", "emt_triggers"]
    assert main(["scan", str(NET), "--plant-mw", "1500", "--emt-triage", "--out", str(js)]) == 0
    assert "emt_triage" in json.loads(js.read_text(encoding="utf-8"))
    assert "EMT study triage" in rep.read_text(encoding="utf-8")


def test_scan_without_triage_has_no_triage_output(tmp_path):
    out, js = tmp_path / "s.csv", tmp_path / "s.json"
    assert main(["scan", str(NET), "--plant-mw", "1500", "--out", str(out)]) == 0
    assert main(["scan", str(NET), "--plant-mw", "1500", "--out", str(js)]) == 0
    assert "emt_priority" not in out.read_text(encoding="utf-8") and "emt_triage" not in js.read_text(encoding="utf-8")


@pytest.mark.parametrize("extra,msg", [
    (["triage", str(NET), "--buses", "11,12", "--plant-mw", "1500", "--groups",
      str(EX / "ieee39_groups_example.csv")], "not in --buses"),
    (["triage", str(NET), "--buses", "12", "--plant-mw", "1500", "--ibr-threshold", "1.5"], "ibr-threshold"),
    (["triage", str(NET), "--buses", "99", "--plant-mw", "1500"], "not found"),
    (["triage", str(NET), "--buses", "12,12", "--plant-mw", "1500"], "more than once"),
    (["triage", str(NET), "--buses", "16", "--plant-mw", "1500", "--poi-info",
      str(EX / "ieee39_poi_info_example.csv")], "not in --buses"),
    (["scan", str(NET), "--plant-mw", "1500", "--poi-info", str(EX / "ieee39_poi_info_example.csv")],
     "--emt-triage"),
    (["scan", str(NET), "--plant-mw", "1500", "--emt-triage", "--method", "iec60909"], "classical"),
])
def test_cli_errors(extra, msg, capsys):
    assert main(extra) == 2
    assert msg in capsys.readouterr().err


def test_user_fields_cover_nerc_chapter1():
    """Every NERC (2024) Chapter 1 situation is either found in the model or asked in --poi-info."""
    assert list(USER_FIELDS) == ["rms_stability_concerns", "unexplained_system_event", "pre_existing_oscillation",
                                 "series_compensation", "facts_nearby", "hvdc_nearby", "high_ibr_penetration", "ras",
                                 "distance_relays_declining_fault_current", "decreasing_strength_trend",
                                 "rocof_inertia_trend"]
    level1 = {k for k, (_, lvl) in USER_FIELDS.items() if lvl == 1}
    assert level1 == {"unexplained_system_event", "series_compensation", "facts_nearby", "hvdc_nearby"}
    assert USER_FIELDS["pre_existing_oscillation"][0] == "Pre-existing oscillation or oscillatory modes"


def test_example_poi_info_has_every_question():
    header = (EX / "ieee39_poi_info_example.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
    assert header == ["poi", *USER_FIELDS, "oem_min_scr", "notes"]
