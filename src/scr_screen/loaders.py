"""Load networks from common file formats, and save them for editing.

Supported:
    .json        pandapower JSON
    .xlsx        pandapower Excel workbook (edit in Excel; one sheet per element type)
    .m / .mat    MATPOWER case files (converted by pandapower)

MATPOWER files contain no short-circuit data, so after conversion the
generator and grid-source short-circuit columns are empty. Use
``scr-screen convert case.m mynet.xlsx``, fill in those columns in Excel,
then ``scr-screen check mynet.xlsx`` and ``scr-screen scan mynet.xlsx ...``.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from .metrics import InputError

FORMATS = {
    ".json": "pandapower JSON",
    ".xlsx": "pandapower Excel",
    ".m": "MATPOWER (.m)",
    ".mat": "MATPOWER (.mat)",
}

# Short-circuit columns SCR-Screen uses, so they always exist for the user to fill in.
SC_COLUMNS = {
    "gen": ["sn_mva", "vn_kv", "xdss_pu", "rdss_ohm", "cos_phi"],
    "ext_grid": ["s_sc_max_mva", "rx_max", "s_sc_min_mva", "rx_min"],
}


def load_network(path: str | Path):
    """Load a network file, choosing the reader from the file extension."""
    import pandapower as pp

    path = Path(path)
    if not path.exists():
        raise InputError(f"Network file not found: {path}")
    ext = path.suffix.lower()
    if ext not in FORMATS:
        raise InputError(f"Unsupported network file type '{ext}'. Supported: "
                         + ", ".join(f"{e} ({d})" for e, d in FORMATS.items()) + ".")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if ext == ".json":
                net = pp.from_json(str(path))
            elif ext == ".xlsx":
                net = pp.from_excel(str(path))
            else:
                from pandapower.converter.matpower import from_mpc

                net = from_mpc(str(path))
    except InputError:
        raise
    except Exception as err:  # readers raise many different error types
        raise InputError(f"Could not read {path.name} as {FORMATS[ext]}: {err}") from err
    ensure_sc_columns(net)
    return net


def save_network(net, path: str | Path) -> Path:
    """Save a network as pandapower JSON or Excel (chosen by extension)."""
    import pandapower as pp

    path = Path(path)
    ext = path.suffix.lower()
    ensure_sc_columns(net)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if ext == ".json":
            pp.to_json(net, str(path))
        elif ext == ".xlsx":
            pp.to_excel(net, str(path), include_results=False)
        else:
            raise InputError("Networks can be saved as .json or .xlsx.")
    return path


def ensure_sc_columns(net) -> None:
    """Add any missing short-circuit columns (empty), so users can see and fill them."""
    for table, cols in SC_COLUMNS.items():
        if table in net:
            for col in cols:
                if col not in net[table].columns:
                    net[table][col] = np.nan
