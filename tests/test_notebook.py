"""Run every code cell of examples/walkthrough.ipynb, so the walkthrough never goes stale.

Uses plain Python (no Jupyter needed): the notebook file is JSON, and each code
cell is executed in order in a temporary folder.
"""

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "examples" / "walkthrough.ipynb"


@pytest.mark.filterwarnings("ignore")
def test_walkthrough_notebook_runs(tmp_path, monkeypatch, capsys):
    shutil.copytree(ROOT / "examples", tmp_path / "examples")
    monkeypatch.chdir(tmp_path)
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    namespace = {}
    for i, cell in enumerate(c for c in cells if c["cell_type"] == "code"):
        source = "".join(cell["source"])
        exec(compile(source, f"<notebook cell {i}>", "exec"), namespace)
    out = capsys.readouterr().out
    assert "WSCR 2.889 (weak)" in out
    assert "485.86 MVA" in out and "509.68 MVA" in out
    assert "Exit code: 0" in out
    assert (tmp_path / "notebook_output" / "direct_mode_report.html").exists()
