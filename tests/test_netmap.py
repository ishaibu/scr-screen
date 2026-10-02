"""Tests for the network map (V1) and maximum plant size (V2)."""

import re

import pandapower as pp
import pytest

from scr_screen.metrics import Plant
from scr_screen.netmap import MAX_MAP_BUSES, bus_label, render_network_svg
from scr_screen.network import scan_buses
from scr_screen.report import render_html
from scr_screen.screening import screen
from scr_screen.settings import Thresholds

pytestmark = pytest.mark.filterwarnings("ignore")


def small_net(names=True, geo=False):
    net = pp.create_empty_network()
    b = [pp.create_bus(net, vn_kv=138, name=f"N{i}" if names else None,
                       geodata=(i * 10.0, i % 2) if geo else None) for i in range(4)]
    pp.create_ext_grid(net, b[0], s_sc_max_mva=1000, rx_max=0.1)
    for f, t in [(0, 1), (1, 2), (2, 3)]:
        pp.create_line_from_parameters(net, b[f], b[t], length_km=40, r_ohm_per_km=0.05,
                                       x_ohm_per_km=0.4, c_nf_per_km=0, max_i_ka=1)
    return net


def results_for(net, mw=150):
    return {r.bus: (r.scr, r.flag) for r in scan_buses(net, mw, method="classical")}


# --- V1: network map ---------------------------------------------------------

def test_map_auto_layout_when_no_coordinates():
    net = small_net()
    svg, note = render_network_svg(net, results_for(net))
    assert svg.startswith("<svg class='netmap'")
    assert "computed automatically" in note
    assert svg.count("<line") == 3          # three lines
    assert svg.count("<rect") == 1          # one source bus drawn as a square
    assert svg.count("class='node") == 4    # every bus drawn once
    halos = svg.count("class='halo")
    flagged = sum(f != "none" for _, f in results_for(net).values())
    assert halos == flagged                 # pulsing ring only on flagged buses


def test_map_uses_network_coordinates_when_present():
    net = small_net(geo=True)
    _, note = render_network_svg(net, results_for(net))
    assert "own coordinates" in note


def test_weak_buses_are_labeled_and_tooltips_present():
    net = small_net()
    svg, _ = render_network_svg(net, results_for(net, mw=300))
    flags = {f for _, f in results_for(net, mw=300).values()}
    assert flags & {"weak", "very weak"}
    assert "class='lbl'>Bus N" in svg
    assert re.search(r"<title>Bus N\d: SCR \d+\.\d\d", svg)


def test_names_are_escaped_in_svg():
    net = small_net()
    net.bus.at[3, "name"] = "<b>x</b>"
    svg, _ = render_network_svg(net, results_for(net, mw=300))
    assert "<b>x</b>" not in svg and "&lt;b&gt;" in svg


def test_unnamed_bus_label_falls_back_to_index():
    net = small_net(names=False)
    assert bus_label(net, 2) == "2"


def test_large_network_map_is_skipped_with_note():
    net = pp.create_empty_network()
    for _ in range(MAX_MAP_BUSES + 1):
        pp.create_bus(net, vn_kv=138)
    svg, note = render_network_svg(net, {})
    assert svg is None and "exceeds" in note


def test_report_embeds_map_and_legend():
    net = small_net()
    svg, note = render_network_svg(net, results_for(net))
    html = render_html(screen([Plant("A", 500, 100)]), network_svg=svg, network_note=note)
    assert "<h2>Network map</h2>" in html and "Dashed line = transformer" in html


# --- V2: largest plant before a weak flag --------------------------------------

def test_max_size_t3b_value():
    # T3b: 485.86 MVA, weak threshold 3.0 -> 161.95 MW
    r = screen([Plant("POI", scmva=485.86, rating_mw=100)])
    assert r.plants[0].max_rating_no_flag == pytest.approx(161.953, abs=0.001)


def test_max_size_follows_custom_threshold():
    r = screen([Plant("POI", scmva=500, rating_mw=100)], thresholds=Thresholds(1.5, 2.5))
    assert r.plants[0].max_rating_no_flag == pytest.approx(200.0)


def test_max_size_plant_is_exactly_at_threshold():
    r = screen([Plant("POI", scmva=485.86, rating_mw=100)])
    cap = r.plants[0].max_rating_no_flag
    check = screen([Plant("POI", scmva=485.86, rating_mw=cap)])
    assert check.plants[0].scr == pytest.approx(3.0)
    assert check.plants[0].flag == "none"


def test_report_shows_max_size_section():
    html = render_html(screen([Plant("POI", scmva=485.86, rating_mw=100)]))
    assert "Largest plant before a weak flag" in html and "162 MW" in html


def test_map_carries_scmva_for_live_updates():
    net = small_net()
    rows = scan_buses(net, 150, method="classical")
    svg, _ = render_network_svg(net, {r.bus: (r.scr, r.flag) for r in rows},
                                scmva={r.bus: r.scmva for r in rows})
    assert svg.count("data-scmva=") == 4
    assert "animation-delay" in svg


def test_labels_and_rings_limited_to_weakest_eight():
    from scr_screen.netmap import MAX_LABELS
    net = pp.from_json(str(__import__("pathlib").Path(__file__).resolve().parents[1]
                           / "examples" / "ieee39_assumed.json"))
    svg, _ = render_network_svg(net, results_for(net, mw=3000))
    assert svg.count("class='lbl'") == MAX_LABELS == 8
    assert svg.count("class='halo") == 8
    assert "Bus 12 · 0.94" in svg            # the weakest bus is always labeled
