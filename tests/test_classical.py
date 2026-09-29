"""Tests for the classical flat-start method (Option B).

Expected values are hand calculations (docs/design-spec.md, Section 8):
    T3b: 485.86 MVA  (138 kV source 1000 MVA, R/X 0.1, + 50 km line)
    T4 : 500.15 MVA  (source 1000 MVA + 100 MVA transformer, vk 10%, vkr 0.5%)
    T5 : 984.30 MVA  (T3b network + 100 MVA generator, X''d 0.2 pu, at the POI)
"""

import pandapower as pp
import pytest

from scr_screen.metrics import InputError
from scr_screen.network import scan_buses, scmva, scmva_flat, scmva_iec


def t3_network(with_ibr=False, with_gen=False):
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
    if with_gen:
        pp.create_gen(net, b2, p_mw=80, sn_mva=100, vn_kv=138, xdss_pu=0.2, rdss_ohm=0.0, cos_phi=0.85)
    return net


def t4_network():
    net = pp.create_empty_network()
    hv = pp.create_bus(net, vn_kv=138, name="HV")
    lv = pp.create_bus(net, vn_kv=34.5, name="Collector")
    pp.create_ext_grid(net, hv, s_sc_max_mva=1000, rx_max=0.1)
    pp.create_transformer_from_parameters(
        net, hv, lv, sn_mva=100, vn_hv_kv=138, vn_lv_kv=34.5,
        vk_percent=10, vkr_percent=0.5, pfe_kw=0, i0_percent=0,
    )
    return net


# --- Hand-calculated cases ----------------------------------------------------

def test_t3b_classical_scmva_at_poi():
    result = scmva_flat(t3_network(), buses=1)
    assert result.scmva[1] == pytest.approx(485.86, abs=0.01)
    assert result.method == "classical"


def test_classical_source_bus_is_specified_mva():
    # No c-factor: the source bus returns exactly the specified 1000 MVA.
    assert scmva_flat(t3_network(), buses=0).scmva[0] == pytest.approx(1000.0, abs=0.01)


def test_t4_transformer():
    assert scmva_flat(t4_network(), buses=1).scmva[1] == pytest.approx(500.15, abs=0.01)


def test_t5_synchronous_generator_adds_strength():
    assert scmva_flat(t3_network(with_gen=True), buses=1).scmva[1] == pytest.approx(984.30, abs=0.01)


# --- Behavior -----------------------------------------------------------------

def test_ibr_never_contributes():
    assert scmva_flat(t3_network(with_ibr=True), buses=1).scmva[1] == pytest.approx(485.86, abs=0.01)


def test_iec_is_higher_than_classical_on_t3():
    iec = scmva_iec(t3_network(), buses=1).scmva[1]
    flat = scmva_flat(t3_network(), buses=1).scmva[1]
    assert iec / flat == pytest.approx(509.68 / 485.86, rel=1e-4)


def test_dispatch_and_scan_use_classical():
    assert scmva(t3_network(), buses=1, method="classical").scmva[1] == pytest.approx(485.86, abs=0.01)
    rows = scan_buses(t3_network(), plant_mw=200, method="classical")
    assert [r.bus for r in rows] == [0, 1]
    assert rows[1].scr == pytest.approx(2.429, abs=0.001)
    assert rows[1].flag == "weak"


def test_open_line_switch_isolates_bus():
    net = t3_network()
    pp.create_switch(net, bus=1, element=0, et="l", closed=False)
    with pytest.raises(InputError, match="isolated|no valid path"):
        scmva_flat(net, buses=1)


def test_out_of_service_bus_requested_raises():
    net = t3_network()
    net.bus.at[1, "in_service"] = False
    with pytest.raises(InputError, match="out of service"):
        scmva_flat(net, buses=1)


# --- Clear errors -------------------------------------------------------------

def test_missing_generator_data_raises():
    net = t3_network()
    pp.create_gen(net, 1, p_mw=50)  # no xdss_pu / sn_mva
    with pytest.raises(InputError, match="xdss_pu"):
        scmva_flat(net)


def test_missing_ext_grid_data_raises():
    net = pp.create_empty_network()
    b = pp.create_bus(net, vn_kv=138)
    pp.create_ext_grid(net, b)
    with pytest.raises(InputError, match="s_sc_max_mva"):
        scmva_flat(net)


def test_no_source_raises():
    net = pp.create_empty_network()
    pp.create_bus(net, vn_kv=138)
    with pytest.raises(InputError, match="no in-service external grid"):
        scmva_flat(net)


def test_unsupported_element_raises():
    net = t4_network()
    b3 = pp.create_bus(net, vn_kv=13.8)
    pp.create_transformer3w_from_parameters(
        net, 0, 1, b3, vn_hv_kv=138, vn_mv_kv=34.5, vn_lv_kv=13.8,
        sn_hv_mva=100, sn_mv_mva=50, sn_lv_mva=50,
        vk_hv_percent=10, vk_mv_percent=10, vk_lv_percent=10,
        vkr_hv_percent=0.5, vkr_mv_percent=0.5, vkr_lv_percent=0.5,
        pfe_kw=0, i0_percent=0,
    )
    with pytest.raises(InputError, match="trafo3w"):
        scmva_flat(net)


def test_meshed_network_matches_pandapower_impedance_model():
    """Independent check of the network matrix on a meshed (looped) network.

    With only lines and one source, IEC gives S = c * Un^2 / |Z| where the
    source impedance also includes c. Scaling our source by 1/c and the result
    by c must therefore reproduce pandapower exactly at every bus.
    """
    c = 1.1

    def meshed(s_sc):
        net = pp.create_empty_network()
        b = [pp.create_bus(net, vn_kv=138) for _ in range(4)]
        pp.create_ext_grid(net, b[0], s_sc_max_mva=s_sc, rx_max=0.1)
        for f, t, km in [(0, 1, 30), (1, 2, 40), (2, 3, 25), (3, 0, 60), (1, 3, 45)]:
            pp.create_line_from_parameters(
                net, b[f], b[t], length_km=km, r_ohm_per_km=0.06,
                x_ohm_per_km=0.38, c_nf_per_km=0, max_i_ka=1,
            )
        return net

    iec = scmva_iec(meshed(1000)).scmva
    flat = scmva_flat(meshed(1000 / c)).scmva
    for bus in iec:
        assert c * flat[bus] == pytest.approx(iec[bus], rel=1e-6)
