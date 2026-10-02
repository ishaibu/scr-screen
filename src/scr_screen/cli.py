"""Command-line tool: ``scr-screen``.

Examples:
    scr-screen template plants.csv
    scr-screen run plants.csv --report report.html --out results.csv
    scr-screen scan network.json --plant-mw 300 --method classical --report scan.html --open
    scr-screen --version
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from . import __version__
from .io import read_plants_csv, write_results_csv, write_results_json, write_template_csv
from .metrics import InputError, Plant
from .report import write_html_report
from .screening import ScreeningResult, screen
from .settings import Thresholds

METHOD_LABELS = {"classical": "classical flat-start (1.0 pu)", "iec60909": "IEC 60909"}


def main(argv: list[str] | None = None) -> int:
    """Run the command line. Returns an exit code (0 = success, 2 = input error)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except InputError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2


# --- Commands ----------------------------------------------------------------

def _cmd_template(args) -> int:
    path = write_template_csv(args.path)
    print(f"Template written: {path}")
    print("Fill in one row per plant, then run:  scr-screen run " + str(path))
    return 0


def _cmd_run(args) -> int:
    plants, poi = read_plants_csv(args.csv)
    result = screen(plants, basis=args.basis, thresholds=_thresholds(args),
                    source="direct input", poi_names=poi)
    _print_summary(result)
    _write_outputs(result, args, notes=[])
    return 0


def _cmd_scan(args) -> int:
    if not args.plant_mw > 0:
        raise InputError(f"Plant size (--plant-mw) must be greater than zero, got {args.plant_mw:g}.")
    # Imported here so 'run' and 'template' work without loading pandapower.
    import pandapower as pp

    from .network import scan_buses

    path = Path(args.network)
    if not path.exists():
        raise InputError(f"Network file not found: {path}")
    try:
        net = pp.from_json(str(path))
    except Exception as err:  # pandapower raises several error types
        raise InputError(f"Could not read {path.name} as a pandapower network: {err}") from err

    thresholds = _thresholds(args)
    with warnings.catch_warnings():
        # Harmless notices from inside pandapower; they would only confuse users.
        warnings.simplefilter("ignore", FutureWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        rows = scan_buses(net, plant_mw=args.plant_mw, method=args.method,
                          case=args.case, thresholds=thresholds)
    from .netmap import bus_label, render_network_svg

    # Label buses by name (e.g. IEEE bus numbers); fall back to index if names repeat.
    labels = {r.bus: bus_label(net, r.bus) for r in rows}
    use_names = len(set(labels.values())) == len(labels)
    ids = {r.bus: f"Bus {labels[r.bus] if use_names else r.bus}" for r in rows}
    plants = [Plant(ids[r.bus], scmva=r.scmva, rating_mw=args.plant_mw) for r in rows]
    poi = {ids[r.bus]: f"pandapower index {r.bus}" for r in rows}
    label = METHOD_LABELS[args.method]
    if args.method == "iec60909":
        label += f", case '{args.case}'"
    result = screen(plants, basis="MW", thresholds=thresholds,
                    source=f"network model ({path.name}), {label}", poi_names=poi)
    notes = [f"Bus scan: a hypothetical {args.plant_mw:g} MW plant was screened at each bus, "
             "one at a time. Nearby plants should also be checked together with WSCR.",
             ("Bus labels are the bus names in the network file; the POI column gives the "
              "pandapower index." if use_names else
              "Bus labels are pandapower indices (counting from 0); bus names were not unique.")]
    svg, map_note, interactive = None, None, None
    if args.report:
        svg, map_note = render_network_svg(net, {r.bus: (r.scr, r.flag) for r in rows},
                                            scmva={r.bus: r.scmva for r in rows})
        compare = None
        other = "iec60909" if args.method == "classical" else "classical"
        if not args.no_compare:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                warnings.simplefilter("ignore", DeprecationWarning)
                other_rows = scan_buses(net, plant_mw=args.plant_mw, method=other,
                                        case=args.case, thresholds=thresholds)
            compare = {ids[r.bus]: r.scmva for r in other_rows}
        interactive = {"plant_mw": args.plant_mw, "compare": compare,
                       "primary_label": _short_label(args.method),
                       "compare_label": _short_label(other)}
    _print_summary(result)
    _write_outputs(result, args, notes=notes, network_svg=svg, network_note=map_note,
                   interactive=interactive)
    return 0


def _short_label(method: str) -> str:
    return "Classical" if method == "classical" else "IEC 60909"


# --- Helpers -------------------------------------------------------------------

def _thresholds(args) -> Thresholds:
    try:
        return Thresholds(very_weak_below=args.very_weak, weak_below=args.weak)
    except ValueError as err:
        raise InputError(str(err)) from None


def _write_outputs(result: ScreeningResult, args, notes: list[str],
                   network_svg: str | None = None, network_note: str | None = None,
                   interactive: dict | None = None) -> None:
    if args.report:
        path = write_html_report(result, args.report, title=args.title, notes=notes,
                                 network_svg=network_svg, network_note=network_note,
                                 interactive=interactive)
        print(f"Report written:  {path}")
        if args.open:
            import webbrowser

            webbrowser.open(Path(path).resolve().as_uri())
            print("Opened the report in your browser.")
    if args.out:
        out = Path(args.out)
        if out.suffix.lower() == ".json":
            write_results_json(result, out)
        elif out.suffix.lower() == ".csv":
            write_results_csv(result, out)
        else:
            raise InputError("--out must end in .csv or .json")
        print(f"Results written: {out}")


def _print_summary(result: ScreeningResult) -> None:
    print(f"SCR-Screen v{result.tool_version} | basis {result.basis} | source: {result.source}")
    print(f"{'Plant':<20}{'SCMVA':>11}{'Rating':>10}{'SCR':>9}  {'Flag':<10}{'Max, no flag':>13}")
    for p in sorted(result.plants, key=lambda p: p.scr, reverse=True):
        print(f"{p.plant_id[:19]:<20}{p.scmva:>11.1f}{p.rating:>10.1f}{p.scr:>9.3f}  "
              f"{p.flag:<10}{p.max_rating_no_flag:>13.1f}")
    for g in result.groups:
        print(f"Group {g.group}: WSCR {g.wscr:.3f} ({g.flag}); plants {', '.join(g.plant_ids)}")
    flagged = sum(p.flag != "none" for p in result.plants) + sum(g.flag != "none" for g in result.groups)
    print(f"Flagged: {flagged}. Screening indicators only; not a substitute for studies.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scr-screen",
        description="Short-circuit ratio (SCR/WSCR) screening for inverter-based resources.",
    )
    parser.add_argument("--version", action="version", version=f"scr-screen {__version__}")
    sub = parser.add_subparsers(title="commands")

    t = sub.add_parser("template", help="write an input CSV template")
    t.add_argument("path", help="where to save the template, e.g. plants.csv")
    t.set_defaults(func=_cmd_template)

    def common(p):
        p.add_argument("--report", metavar="HTML", help="write an HTML report to this file")
        p.add_argument("--out", metavar="FILE", help="write results to a .csv or .json file")
        p.add_argument("--title", default="SCR-Screen report", help="report title")
        p.add_argument("--very-weak", type=float, default=2.0, metavar="X",
                       help="flag 'very weak' below this value (default 2.0)")
        p.add_argument("--weak", type=float, default=3.0, metavar="X",
                       help="flag 'weak' below this value (default 3.0)")
        p.add_argument("--open", action="store_true",
                       help="open the HTML report in your browser when it is ready")

    r = sub.add_parser("run", help="screen plants listed in a CSV file (direct mode)")
    r.add_argument("csv", help="input CSV (see 'scr-screen template')")
    r.add_argument("--basis", choices=["MW", "MVA", "mw", "mva"], default="MW",
                   help="rating basis (default MW)")
    common(r)
    r.set_defaults(func=_cmd_run)

    s = sub.add_parser("scan", help="scan every bus of a pandapower network (network mode)")
    s.add_argument("network", help="pandapower network saved as JSON")
    s.add_argument("--plant-mw", type=float, required=True, help="plant size to screen at each bus")
    s.add_argument("--method", choices=["classical", "iec60909"], default="classical",
                   help="short-circuit method (default classical)")
    s.add_argument("--case", choices=["max", "min"], default="max",
                   help="IEC 60909 case (default max; ignored for classical)")
    s.add_argument("--no-compare", action="store_true",
                   help="skip the second method (the report's method comparison chart)")
    common(s)
    s.set_defaults(func=_cmd_scan)
    return parser


if __name__ == "__main__":
    sys.exit(main())
