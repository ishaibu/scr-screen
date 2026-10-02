"""Tests for scr_screen.network (Option A: IEC 60909).

T3 expected value comes from the hand calculation in docs/design-spec.md.
"""

import pandapower as pp
import pytest

from scr_screen.metrics import InputError
from scr_screen.network import scan_buses, scmva, scmva_iec


def t3_network(with_ibr: bool = False):
    """Design-spec T3: 138 kV source (1000 MVA, R/X 0.1) + 50 km line."""
    net = pp.create_empty_network()
    b1 = pp.create_bus(net, vn_kv=138, name="Source")
    b2 = pp.create_bus(net, vn_kv=138, name="POI")
    pp.create_ext_grid(net, b1, s_sc_max_mva=1000, rx_max=0.1, s_sc_min_mva=800, rx_min=0.1)
    pp.create_line_from_parameters(
        net, b1, b2, length_km=50, r_ohm_per_km=0.05, x_ohm_per_km=0.4,
        c_nf_per_km=0, max_i_ka=1,
    )
    if with_ibr:
        pp.create_sgen(net, b2, p_mw=100, sn_mva=110, k=1.2)
    return net


def test_t3_iec_scmva_at_poi():
    result = scmva_iec(t3_network(), buses=1)
    assert result.scmva[1] == pytest.approx(509.68, abs=0.01)
    assert result.method == "iec60909"


def test_source_bus_returns_specified_1000_mva():
    # IEC defines the source impedance so the source bus gives back S''kQ.
    result = scmva_iec(t3_network(), buses=0)
    assert result.scmva[0] == pytest.approx(1000.0, abs=0.01)


def test_ibr_is_excluded_by_default():
    # With the IBR included, pandapower adds its current (about 642 MVA).
    # SCR screening must exclude it, so the answer stays 509.68 MVA.
    result = scmva_iec(t3_network(with_ibr=True), buses=1)
    assert result.scmva[1] == pytest.approx(509.68, abs=0.01)


def test_ibr_included_only_when_asked():
    result = scmva_iec(t3_network(with_ibr=True), buses=1, exclude_ibr=False)
    assert result.scmva[1] > 600


def test_user_network_is_not_modified():
    net = t3_network(with_ibr=True)
    scmva_iec(net, buses=1)
    assert bool(net.sgen.at[0, "in_service"]) is True


def test_all_buses_by_default():
    result = scmva_iec(t3_network())
    assert set(result.scmva) == {0, 1}


def test_scan_ranks_strongest_first_and_flags():
    rows = scan_buses(t3_network(), plant_mw=100)
    assert [r.bus for r in rows] == [0, 1]
    assert rows[0].scr == pytest.approx(10.0, abs=0.001)
    assert rows[1].scr == pytest.approx(5.097, abs=0.001)
    assert rows[1].name == "POI"
    assert all(r.flag == "none" for r in rows)


def test_scan_flags_weak_bus_for_large_plant():
    rows = scan_buses(t3_network(), plant_mw=200, buses=[1])
    assert rows[0].scr == pytest.approx(2.548, abs=0.001)
    assert rows[0].flag == "weak"


def test_missing_short_circuit_data_gives_clear_error():
    net = pp.create_empty_network()
    b = pp.create_bus(net, vn_kv=138)
    pp.create_ext_grid(net, b)  # no s_sc_max_mva
    with pytest.raises(InputError, match="missing short-circuit data"):
        scmva_iec(net)


def test_unknown_bus_raises():
    with pytest.raises(InputError, match="not found"):
        scmva_iec(t3_network(), buses=[7])


def test_bad_case_raises():
    with pytest.raises(InputError, match="'max' or 'min'"):
        scmva_iec(t3_network(), case="typical")




def test_bus_given_as_pandapower_index_type():
    # pandapower.create_bus returns numpy.int64, not a plain int.
    net = t3_network()
    poi = net.bus.index[1]
    assert type(poi).__name__ != "int"
    assert scmva_iec(net, buses=poi).scmva[1] == pytest.approx(509.68, abs=0.01)
