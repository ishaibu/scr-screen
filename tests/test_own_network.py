"""Own-network support: file formats, the check command, convert, isolated buses."""

import warnings
from pathlib import Path

import pandapower as pp
import pytest

from scr_screen.check import check_network
from scr_screen.cli import main
from scr_screen.loaders import load_network, save_network
from scr_screen.metrics import InputError
from scr_screen.network import scan_buses, scmva_flat

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
pytestmark = pytest.mark.filterwarnings("ignore")

MATPOWER_CASE = """function mpc = tiny
mpc.version = '2';
mpc.baseMVA = 100;
mpc.bus = [
\t1\t3\t0\t0\t0\t0\t1\t1\t0\t345\t1\t1.1\t0.9;
\t2\t2\t0\t0\t0\t0\t1\t1\t0\t345\t1\t1.1\t0.9;
\t3\t1\t90\t30\t0\t0\t1\t1\t0\t345\t1\t1.1\t0.9;
];
mpc.gen = [
\t1\t0\t0\t300\t-300\t1\t100\t1\t250\t10\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0;
\t2\t163\t0\t300\t-300\t1\t100\t1\t300\t10\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0;
];
mpc.branch = [
\t1\t3\t0.01\t0.085\t0.176\t250\t250\t250\t0\t0\t1\t-360\t360;
\t2\t3\t0.017\t0.092\t0.158\t250\t250\t250\t0\t0\t1\t-360\t360;
];
"""


def t3(with_island=False):
    net = pp.create_empty_network()
    b1 = pp.create_bus(net, vn_kv=138, name="Source")
    b2 = pp.create_bus(net, vn_kv=138, name="POI")
    pp.create_ext_grid(net, b1, s_sc_max_mva=1000, rx_max=0.1, s_sc_min_mva=800, rx_min=0.1)
    pp.create_line_from_parameters(net, b1, b2, length_km=50, r_ohm_per_km=0.05,
                                   x_ohm_per_km=0.4, c_nf_per_km=0, max_i_ka=1)
    if with_island:
        b3 = pp.create_bus(net, vn_kv=138, name="IslandA")
        b4 = pp.create_bus(net, vn_kv=138, name="IslandB")
        pp.create_line_from_parameters(net, b3, b4, length_km=10, r_ohm_per_km=0.05,
                                       x_ohm_per_km=0.4, c_nf_per_km=0, max_i_ka=1)
    return net


# --- File formats --------------------------------------------------------------

@pytest.mark.parametrize("ext", [".json", ".xlsx"])
def test_round_trip_gives_identical_results(tmp_path, ext):
    path = save_network(t3(), tmp_path / f"net{ext}")
    net = load_network(path)
    assert scmva_flat(net, buses=1).scmva[1] == pytest.approx(485.86, abs=0.01)


def test_ieee39_excel_matches_json(tmp_path):
    json_net = load_network(EXAMPLES / "ieee39_assumed.json")
    xlsx_net = load_network(save_network(json_net, tmp_path / "ieee39.xlsx"))
    a = {r.bus: r.scmva for r in scan_buses(json_net, 1500, method="classical")}
    b = {r.bus: r.scmva for r in scan_buses(xlsx_net, 1500, method="classical")}
    assert a.keys() == b.keys()
    assert all(b[k] == pytest.approx(a[k], rel=1e-9) for k in a)


def test_matpower_m_file_loads_with_empty_sc_columns(tmp_path):
    path = tmp_path / "tiny.m"
    path.write_text(MATPOWER_CASE)
    net = load_network(path)
    assert len(net.bus) == 3
    assert "xdss_pu" in net.gen.columns and "s_sc_max_mva" in net.ext_grid.columns
    rep = check_network(net)
    assert not rep.ready("classical") and not rep.ready("iec60909")
    msgs = " ".join(f.message for f in rep.findings)
    assert "s_sc_max_mva and rx_max" in msgs and "sub-transient data" in msgs


def test_unsupported_extension_and_missing_file(tmp_path):
    with pytest.raises(InputError, match="Unsupported network file type"):
        load_network(_touch(tmp_path / "net.raw"))
    with pytest.raises(InputError, match="not found"):
        load_network(tmp_path / "none.json")


def test_corrupt_file_gives_clear_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(InputError, match="Could not read bad.json"):
        load_network(p)


# --- Check ------------------------------------------------------------------

def test_check_ready_network():
    rep = check_network(load_network(EXAMPLES / "ieee39_assumed.json"))
    assert rep.ready("classical") and rep.ready("iec60909")
    assert not [f for f in rep.findings if f.level == "error"]


def test_check_flags_generator_without_data_and_ibr_info():
    net = t3()
    pp.create_gen(net, 1, p_mw=50, name="G-new")
    pp.create_sgen(net, 1, p_mw=100, k=1.2)
    rep = check_network(net)
    msgs = " ".join(f.message for f in rep.findings)
    assert "G-new (bus POI)" in msgs and "excluded" in msgs
    assert not rep.ready("classical")


def test_check_classical_only_limitation():
    net = t3()
    b3 = pp.create_bus(net, vn_kv=138)
    pp.create_switch(net, 1, b3, et="b", closed=True)
    rep = check_network(net)
    assert not rep.ready("classical")
    assert any("bus-bus switch" in f.message and f.applies_to == "classical" for f in rep.findings)


def test_check_warns_isolated_buses():
    rep = check_network(t3(with_island=True))
    assert any(f.level == "warning" and "IslandA" in f.message for f in rep.findings)
    assert rep.ready("classical")


# --- Isolated buses are skipped in scans, by both methods ----------------------

@pytest.mark.parametrize("method", ["classical", "iec60909"])
def test_scan_skips_isolated_buses_with_note(method):
    notes = []
    rows = scan_buses(t3(with_island=True), 100, method=method, notes=notes)
    assert {r.bus for r in rows} == {0, 1}
    assert any("excluded" in n for n in notes)


def test_isolated_bus_requested_directly_raises():
    with pytest.raises(InputError, match="no path to any source"):
        scmva_flat(t3(with_island=True), buses=2)


# --- CLI ----------------------------------------------------------------------

def test_cli_check_convert_and_scan_excel(tmp_path, capsys):
    xlsx = tmp_path / "ieee39.xlsx"
    assert main(["convert", str(EXAMPLES / "ieee39_assumed.json"), str(xlsx)]) == 0
    assert main(["check", str(xlsx)]) == 0
    assert "Ready for Classical: yes" in capsys.readouterr().out
    assert main(["scan", str(xlsx), "--plant-mw", "1500"]) == 0
    assert "1.888" in capsys.readouterr().out


def test_cli_check_fails_for_matpower_without_sc_data(tmp_path, capsys):
    path = tmp_path / "tiny.m"
    path.write_text(MATPOWER_CASE)
    assert main(["check", str(path)]) == 2
    assert main(["scan", str(path), "--plant-mw", "100"]) == 2
    err = capsys.readouterr()
    assert "not ready for the classical method" in err.err


def _touch(p):
    p.write_text("x")
    return p
