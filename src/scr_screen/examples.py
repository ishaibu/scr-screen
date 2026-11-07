"""Example files bundled with the package, so anyone can try SCR-Screen right after installing.

``scr-screen example`` copies them into a folder:
    ieee39_assumed.json        IEEE 39-bus network with ASSUMED short-circuit data (public test system)
    ieee39_sites_example.csv   site cost file with ILLUSTRATIVE costs for four candidate buses
    ieee39_groups_example.csv  bus groups screened together with WSCR (scan --groups)
    ieee39_groups_mva_example.csv  the same groups plus an ILLUSTRATIVE 200 MVA STATCOM at bus 12 (MVA basis)
    ieee39_triage_example.json the same network plus three ASSUMED existing IBRs, for EMT triage
    ieee39_poi_info_example.csv ILLUSTRATIVE answers for situations a model cannot show (triage --poi-info)
    plants_template.csv        direct-mode input with example plants
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from .metrics import InputError

FILES = ("ieee39_assumed.json", "ieee39_sites_example.csv", "ieee39_groups_example.csv",
         "ieee39_groups_mva_example.csv", "ieee39_triage_example.json", "ieee39_poi_info_example.csv",
         "plants_template.csv")

GUIDE = """SCR-Screen example files
=========================

ieee39_assumed.json       IEEE 39-bus test system with ASSUMED short-circuit data
                          (generator X''d = 0.20 pu, R/X = 0.05, rating = max MW / 0.85).
                          Results demonstrate the tool, not any real system.
ieee39_sites_example.csv  Site costs for four candidate buses. ILLUSTRATIVE values only.
ieee39_groups_example.csv Two groups of nearby buses screened together with WSCR
                          (G1: buses 11 and 13; G2: buses 16 and 17).
ieee39_groups_mva_example.csv  The same groups plus an ILLUSTRATIVE 200 MVA STATCOM
                          (0 MW) at bus 12 in G1, for the MVA basis.
ieee39_triage_example.json  The same network plus three ASSUMED existing IBRs
                          (solar at bus 13, wind at bus 26, battery at bus 4), for
                          EMT triage. They are illustrative, not part of the IEEE
                          test system; as IBRs they do not change any SCR.
ieee39_poi_info_example.csv ILLUSTRATIVE answers (yes / no / unknown) for situations
                          a network model cannot show, and an assumed OEM minimum
                          SCR of 3.0 at bus 28 (triage --poi-info).
plants_template.csv       Direct-mode input with example plants.

Try, from inside this folder:

  scr-screen run plants_template.csv --report direct.html --open
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --report scan.html --open
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --report cost.html --open --site-costs ieee39_sites_example.csv --condenser-cost-per-mva 100000 --gen-tie-cost-per-mile 2000000
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --report groups.html --open --groups ieee39_groups_example.csv
  scr-screen interactions ieee39_assumed.json --buses 4,11,12,13,16,17,26,28,29 --out my_groups.csv
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --groups my_groups.csv --n1 --report full.html --open
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --plant-mva 1650 --basis MVA --groups ieee39_groups_mva_example.csv --report mva.html --open
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --power-factor 0.95 --basis MVA --report mva_estimate.html --open
  scr-screen scan ieee39_assumed.json --plant-mw 1500 --gen-out 38,39 --report mingen.html --open
  scr-screen triage ieee39_triage_example.json --buses 12,16,28 --plant-mw 500 --poi-info ieee39_poi_info_example.csv --report triage.html --open
  scr-screen triage ieee39_assumed.json --buses 11,12,13,16,17 --plant-mw 1500 --groups ieee39_groups_example.csv --gen-out 38,39 --report triage1500.html --open
  scr-screen scan ieee39_triage_example.json --plant-mw 500 --emt-triage --report scan_triage.html --open

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
