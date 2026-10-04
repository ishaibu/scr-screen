"""Cost screening: condenser sizing, gen-tie and POI costs, ranking, site file."""

from pathlib import Path

import pytest

from scr_screen.cli import main
from scr_screen.cost import (CostInputs, SiteCost, condenser_mva, read_site_costs_csv,
                             screen_costs, write_site_template)
from scr_screen.metrics import InputError, Plant
from scr_screen.report import render_html
from scr_screen.screening import screen

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
pytestmark = pytest.mark.filterwarnings("ignore")


def test_condenser_sizing_hand_check_ieee_bus_12():
    # (1500 x 3 - 2832.43) x (0.20 + 0.10) = 1667.57 x 0.30 = 500.27 MVA
    need, cmva = condenser_mva(1500, 2832.43, 3.0, 0.30)
    assert need == pytest.approx(1667.57, abs=0.01)
    assert cmva == pytest.approx(500.27, abs=0.01)


def test_no_condenser_when_strong_enough():
    assert condenser_mva(800, 2832.43, 3.0, 0.30) == (0.0, 0.0)


def result_for(mw=1500):
    plants = [Plant("Bus 12", 2832.43, mw), Plant("Bus 29", 4561.04, mw), Plant("Bus 16", 8865.0, mw)]
    return screen(plants)


SITES = {"12": SiteCost(4, 15e6), "29": SiteCost(8, 15e6), "16": SiteCost(35, 20e6)}


def test_costs_and_ranking():
    rows = screen_costs(result_for().plants, CostInputs(
        1500, 3.0, condenser_cost_per_mva=100_000, gen_tie_cost_per_mile=2_000_000, sites=SITES))
    by = {r.bus_id: r for r in rows}
    assert by["Bus 12"].condenser_cost == pytest.approx(500.27 * 100_000, rel=1e-4)
    assert by["Bus 12"].total_cost == pytest.approx(500.27e5 + 8e6 + 15e6, rel=1e-4)
    assert by["Bus 29"].total_cost == pytest.approx(16e6 + 15e6)
    assert [r.bus_id for r in rows] == ["Bus 29", "Bus 12", "Bus 16"]
    assert all(r.complete for r in rows)


def test_only_candidate_buses_are_costed_when_sites_given():
    rows = screen_costs(result_for().plants, CostInputs(1500, 3.0, sites={"12": SiteCost(4, None)}))
    assert [r.bus_id for r in rows] == ["Bus 12"]


def test_missing_prices_mark_rows_incomplete():
    rows = screen_costs(result_for().plants, CostInputs(1500, 3.0, sites=SITES))
    by = {r.bus_id: r for r in rows}
    assert by["Bus 12"].condenser_cost is None and not by["Bus 12"].complete
    assert by["Bus 29"].condenser_cost == 0 and by["Bus 29"].gen_tie_cost is None


def test_without_sites_every_bus_costed_for_condenser_only():
    rows = screen_costs(result_for().plants, CostInputs(1500, 3.0, condenser_cost_per_mva=1e5))
    assert len(rows) == 3 and all(r.gen_tie_cost is None and r.poi_cost is None for r in rows)


def test_bad_inputs_rejected():
    with pytest.raises(InputError):
        CostInputs(0, 3.0)
    with pytest.raises(InputError):
        CostInputs(100, 3.0, condenser_cost_per_mva=-1)


def test_site_file_reading(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("bus,distance_mi,poi_cost_usd\nBus 12,4,15000000\n29,,\n")
    sites = read_site_costs_csv(p)
    assert sites["12"] == SiteCost(4.0, 15e6) and sites["29"] == SiteCost(None, None)
    p.write_text('bus,distance_mi\n12,"1,000"\n')
    with pytest.raises(InputError, match="comma"):
        read_site_costs_csv(p)
    p.write_text("bus,distance_mi\n12,4\n12,5\n")
    with pytest.raises(InputError, match="more than once"):
        read_site_costs_csv(p)


def test_site_template(tmp_path):
    p = write_site_template(["1", "2"], tmp_path / "t.csv")
    assert p.read_text(encoding="utf-8").splitlines()[0] == "bus,distance_mi,poi_cost_usd"


def test_report_cost_section():
    r = result_for()
    inputs = CostInputs(1500, 3.0, condenser_cost_per_mva=100_000, gen_tie_cost_per_mile=2e6, sites=SITES)
    html = render_html(r, interactive={"plant_mw": 1500, "compare": None},
                       cost={"rows": screen_costs(r.plants, inputs), "inputs": inputs})
    assert "Interconnection cost screening" in html and "id='cost-body'" in html
    assert "$50.0M" in html and "excludes network upgrades" in html.lower()
    assert '"cpm": 100000' in html


def test_cli_scan_with_costs(tmp_path, capsys):
    sites = tmp_path / "sites.csv"
    sites.write_text("bus,distance_mi,poi_cost_usd\n12,4,15000000\n29,8,15000000\n")
    out = tmp_path / "costs.csv"
    assert main(["scan", str(EXAMPLES / "ieee39_assumed.json"), "--plant-mw", "1500",
                 "--site-costs", str(sites), "--condenser-cost-per-mva", "100000",
                 "--gen-tie-cost-per-mile", "2000000", "--cost-out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Cost screening" in text and "500.3" in text
    assert out.read_text(encoding="utf-8").startswith("bus_id,scmva")


def test_cli_rejects_unknown_site_bus(tmp_path, capsys):
    sites = tmp_path / "sites.csv"
    sites.write_text("bus,distance_mi\n999,4\n")
    assert main(["scan", str(EXAMPLES / "ieee39_assumed.json"), "--plant-mw", "1500",
                 "--site-costs", str(sites)]) == 2
    assert "not in the scan" in capsys.readouterr().err


def test_target_check_fields():
    # IEEE bus 12 at 1500 MW, target 3: below target; max at target = 2832.43 / 3 = 944.1 MW
    rows = screen_costs(result_for().plants, CostInputs(1500, 3.0, condenser_cost_per_mva=1e5, sites=SITES))
    by = {r.bus_id: r for r in rows}
    assert not by["Bus 12"].meets_target
    assert by["Bus 12"].max_at_target_mw == pytest.approx(944.14, abs=0.01)
    assert by["Bus 12"].scr_after == pytest.approx(3.0)
    assert by["Bus 16"].meets_target and by["Bus 16"].scr_after == pytest.approx(8865 / 1500)


def test_raising_target_flags_more_buses_below():
    rows = screen_costs(result_for().plants, CostInputs(1500, 8.0, sites=SITES))
    assert sum(not r.meets_target for r in rows) == 3   # 5.91 < 8 too


def test_report_target_alert_and_columns():
    r = result_for()
    inputs = CostInputs(1500, 3.0, condenser_cost_per_mva=100_000, sites=SITES)
    html = render_html(r, interactive={"plant_mw": 1500, "compare": None},
                       cost={"rows": screen_costs(r.plants, inputs), "inputs": inputs})
    assert "id='cost-alert'" in html and "1 of 3 bus(es) are below your target SCR of 3" in html
    assert "Max at target: <b>944 MW</b>" in html and "SCR after condenser" in html
