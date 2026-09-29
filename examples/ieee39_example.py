"""IEEE 39-bus (New England) example: grid-strength scan with both methods.

The IEEE 39-bus case in pandapower is a PUBLIC test system, but it has no
short-circuit data. This example adds ASSUMED, typical values so the scan
can run. They are illustrative only and are listed in ASSUMPTIONS below.
Results are for demonstrating the tool, not for any real system.

Bus numbering: pandapower counts buses from 0, the IEEE case from 1.
So pandapower bus 0 is IEEE bus 1, and so on (IEEE bus = pandapower bus + 1).

Run from the project folder:
    python examples/ieee39_example.py
"""

from __future__ import annotations

import pandapower.networks as pn

from scr_screen.network import scan_buses

PLANT_MW = 300.0  # size of the hypothetical plant screened at every bus

ASSUMPTIONS = {
    "gen_xdss_pu": 0.20,    # sub-transient reactance X''d, on machine base (typical)
    "gen_r_over_x": 0.05,   # machine R/X (typical for large units)
    "gen_power_factor": 0.85,  # rated power factor, sets MVA rating = max_p_mw / pf
    "grid_r_over_x": 0.05,  # R/X of the external-grid equivalent at the slack bus
}


def load_ieee39_with_assumed_sc_data():
    """Return the IEEE 39-bus case with assumed short-circuit data added."""
    net = pn.case39()
    a = ASSUMPTIONS

    # Synchronous generators: MVA rating, X''d, R, voltage and power factor.
    for idx, g in net.gen.iterrows():
        vn = float(net.bus.at[g["bus"], "vn_kv"])
        sn = float(g["max_p_mw"]) / a["gen_power_factor"]
        x_ohm = a["gen_xdss_pu"] * vn**2 / sn
        net.gen.at[idx, "sn_mva"] = sn
        net.gen.at[idx, "vn_kv"] = vn
        net.gen.at[idx, "xdss_pu"] = a["gen_xdss_pu"]
        net.gen.at[idx, "rdss_ohm"] = a["gen_r_over_x"] * x_ohm
        net.gen.at[idx, "cos_phi"] = a["gen_power_factor"]

    # The slack machine is modeled as an external grid: S_sc = S_rated / X''d.
    for idx, eg in net.ext_grid.iterrows():
        s_sc = float(eg["max_p_mw"]) / a["gen_power_factor"] / a["gen_xdss_pu"]
        for col, val in [("s_sc_max_mva", s_sc), ("s_sc_min_mva", s_sc),
                         ("rx_max", a["grid_r_over_x"]), ("rx_min", a["grid_r_over_x"])]:
            net.ext_grid.at[idx, col] = val
    return net


def compare_methods(plant_mw: float = PLANT_MW):
    """Scan all buses with both methods; return rows sorted by classical SCR."""
    net = load_ieee39_with_assumed_sc_data()
    iec = {r.bus: r for r in scan_buses(net, plant_mw, method="iec60909")}
    flat = scan_buses(net, plant_mw, method="classical")
    rows = []
    for r in flat:
        i = iec[r.bus]
        rows.append({
            "bus": r.bus,
            "ieee_bus": r.bus + 1,
            "scmva_classical": r.scmva,
            "scr_classical": r.scr,
            "flag_classical": r.flag,
            "scmva_iec": i.scmva,
            "scr_iec": i.scr,
            "flag_iec": i.flag,
            "iec_vs_classical_pct": 100 * (i.scmva / r.scmva - 1),
        })
    return rows


if __name__ == "__main__":
    import sys
    import warnings

    warnings.simplefilter("ignore", FutureWarning)  # harmless pandapower notice
    mw = float(sys.argv[1]) if len(sys.argv) > 1 else PLANT_MW
    rows = compare_methods(mw)
    print(f"IEEE 39-bus scan, {mw:.0f} MW plant at each bus (ASSUMED short-circuit data)")
    print(f"{'IEEE':>4} {'SCMVA cl.':>10} {'SCR cl.':>8} {'Flag cl.':>10} "
          f"{'SCMVA IEC':>10} {'SCR IEC':>8} {'Flag IEC':>10} {'IEC vs cl.':>10}")
    for r in rows:
        print(f"{r['ieee_bus']:>4} {r['scmva_classical']:>10.0f} {r['scr_classical']:>8.2f} "
              f"{r['flag_classical']:>10} {r['scmva_iec']:>10.0f} {r['scr_iec']:>8.2f} "
              f"{r['flag_iec']:>10} {r['iec_vs_classical_pct']:>9.1f}%")
    print("\nAssumptions:", ASSUMPTIONS)
