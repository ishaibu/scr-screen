"""Tests for the scr-screen command-line tool."""

import json
from pathlib import Path

import pytest

from scr_screen.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert "scr-screen" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_template_then_run_with_all_outputs(tmp_path, capsys):
    csv_path = tmp_path / "plants.csv"
    assert main(["template", str(csv_path)]) == 0
    code = main(["run", str(csv_path), "--report", str(tmp_path / "r.html"),
                 "--out", str(tmp_path / "r.json")])
    assert code == 0
    out = capsys.readouterr().out
    assert "Group G1: WSCR 2.889 (weak)" in out
    assert (tmp_path / "r.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["groups"][0]["flag"] == "weak"


def test_run_csv_output(tmp_path):
    csv_path = tmp_path / "plants.csv"
    main(["template", str(csv_path)])
    assert main(["run", str(csv_path), "--out", str(tmp_path / "r.csv")]) == 0
    assert "group (WSCR)" in (tmp_path / "r.csv").read_text(encoding="utf-8")


def test_custom_thresholds_change_flags(tmp_path, capsys):
    csv_path = tmp_path / "plants.csv"
    main(["template", str(csv_path)])
    capsys.readouterr()
    main(["run", str(csv_path), "--very-weak", "1.5", "--weak", "2.5"])
    assert "Group G1: WSCR 2.889 (none)" in capsys.readouterr().out


def test_input_error_exit_code_and_message(tmp_path, capsys):
    assert main(["run", str(tmp_path / "missing.csv")]) == 2
    assert "Error: Input file not found" in capsys.readouterr().err


def test_bad_thresholds_are_input_error(tmp_path, capsys):
    csv_path = tmp_path / "plants.csv"
    main(["template", str(csv_path)])
    assert main(["run", str(csv_path), "--very-weak", "3", "--weak", "2"]) == 2


def test_bad_out_extension(tmp_path, capsys):
    csv_path = tmp_path / "plants.csv"
    main(["template", str(csv_path)])
    assert main(["run", str(csv_path), "--out", str(tmp_path / "r.txt")]) == 2


def test_scan_ieee39_classical(tmp_path, capsys):
    code = main(["scan", str(EXAMPLES / "ieee39_assumed.json"), "--plant-mw", "1500",
                 "--report", str(tmp_path / "scan.html")])
    assert code == 0
    out = capsys.readouterr().out
    assert "Bus 11" in out and "1.888  very weak" in out
    html = (tmp_path / "scan.html").read_text(encoding="utf-8")
    assert "classical flat-start" in html and "hypothetical 1500 MW plant" in html


def test_scan_ieee39_iec(capsys):
    assert main(["scan", str(EXAMPLES / "ieee39_assumed.json"), "--plant-mw", "1500",
                 "--method", "iec60909"]) == 0
    assert "IEC 60909" in capsys.readouterr().out


def test_scan_missing_network(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "none.json"), "--plant-mw", "100"]) == 2
