"""The bundled example files: copied by 'scr-screen example' and identical to examples/."""

import filecmp
from pathlib import Path

import pytest

from scr_screen.cli import main
from scr_screen.examples import FILES, copy_examples
from scr_screen.metrics import InputError

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.mark.parametrize("name", FILES)
def test_bundled_copy_matches_examples_folder(name):
    assert filecmp.cmp(ROOT / "src" / "scr_screen" / "data" / name, ROOT / "examples" / name, shallow=False)


def test_copy_examples_and_refuse_overwrite(tmp_path):
    files = copy_examples(tmp_path / "ex")
    assert {f.name for f in files} == set(FILES) | {"README.txt"}
    with pytest.raises(InputError, match="already exists"):
        copy_examples(tmp_path / "ex")
    copy_examples(tmp_path / "ex", overwrite=True)


def test_cli_example_then_scan_works_out_of_the_box(tmp_path, capsys):
    folder = tmp_path / "scr-screen-example"
    assert main(["example", str(folder)]) == 0
    assert main(["scan", str(folder / "ieee39_assumed.json"), "--plant-mw", "1500",
                 "--site-costs", str(folder / "ieee39_sites_example.csv"),
                 "--condenser-cost-per-mva", "100000", "--gen-tie-cost-per-mile", "2000000"]) == 0
    out = capsys.readouterr().out
    assert "1.888" in out and "500.3" in out
