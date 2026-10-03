"""Example files bundled with the package, so anyone can try SCR-Screen right after installing.

``scr-screen example`` copies them into a folder:
    ieee39_assumed.json        IEEE 39-bus network with ASSUMED short-circuit data (public test system)
    ieee39_sites_example.csv   site cost file with ILLUSTRATIVE costs for four candidate buses
    plants_template.csv        direct-mode input with example plants
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from .metrics import InputError

FILES = ("ieee39_assumed.json", "ieee39_sites_example.csv", "plants_template.csv")

GUIDE = """SCR-Screen example files
=========================

ieee39_assumed.json       IEEE 39-bus test system with ASSUMED short-circuit data
                          (generator X''d = 0.20 pu, R/X = 0.05, rating = max MW / 0.85).
                          Results demonstrate the tool, not any real system.
ieee39_sites_example.csv  Site costs for four candidate buses. ILLUSTRATIVE values only.
plants_template.csv       Direct-mode input with example plants.

Try, from inside this folder:

  scr-screen run plants_template.csv --report direct.html --open
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --report scan.html --open
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --report cost.html --open --site-costs ieee39_sites_example.csv --condenser-cost-per-mva 100000 --gen-tie-cost-per-mile 2000000

Screening only: results do not replace interconnection studies.
"""


def copy_examples(folder: str | Path = "scr-screen-example", overwrite: bool = False) -> list[Path]:
    """Copy the bundled example files (and a short guide) into ``folder``."""
    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)
    targets = [dest / name for name in FILES] + [dest / "README.txt"]
    existing = [t for t in targets if t.exists()]
    if existing and not overwrite:
        raise InputError(f"{existing[0]} already exists. Choose another folder, or add --overwrite.")
    data = resources.files("scr_screen") / "data"
    written = []
    for name in FILES:
        target = dest / name
        target.write_bytes((data / name).read_bytes())
        written.append(target)
    guide = dest / "README.txt"
    guide.write_text(GUIDE, encoding="utf-8")
    written.append(guide)
    return written
