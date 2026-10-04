"""Command-line tool: ``scr-screen``.

Examples:
    scr-screen example                      (copies example files into ./scr-screen-example)
    scr-screen template plants.csv
    scr-screen run plants.csv --report report.html --out results.csv
    scr-screen check mynetwork.xlsx
    scr-screen convert case.m mynetwork.xlsx
    scr-screen scan mynetwork.xlsx --plant-mw 300 --report scan.html --open
    scr-screen sites-template mynetwork.xlsx sites.csv
    scr-screen scan mynetwork.xlsx --plant-mw 300 --report scan.html --site-costs sites.csv \
        --condenser-cost-per-mva 100000 --gen-tie-cost-per-mile 2000000
    scr-screen --version

Network files: .json (pandapower), .xlsx (pandapower Excel), .m / .mat (MATPOWER).
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

def _cmd_example(args) -> int:
    from .examples import copy_examples

    files = copy_examples(args.folder, overwrite=args.overwrite)
    print(f"Example files written to {Path(args.folder).resolve()}:")
    for f in files:
        print(f"  {f.name}")
    print("Next:  cd " + str(args.folder) + "   then follow README.txt, e.g.")
    print("       scr-screen scan ieee39_assumed.json --plant-mw 1500 --report scan.html --open")
    return 0


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
    from .check import check_network
    from .loaders import load_network
    from .netmap import bus_label, render_network_svg
    from .network import scan_buses

    path = Path(args.network)
    net = load_network(path)
    rep = check_network(net)
    if not rep.ready(args.method):
        _print_check(rep, path.name)
        raise InputError(f"{path.name} is not ready for the {args.method} method; see the list above.")

    thresholds = _thresholds(args)
    calc_notes: list[str] = []
    with warnings.catch_warnings():
        # Harmless notices from inside pandapower; they would only confuse users.
        warnings.simplefilter("ignore", FutureWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        rows = scan_buses(net, plant_mw=args.plant_mw, method=args.method,
                          case=args.case, thresholds=thresholds, notes=calc_notes)

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
    notes += [n for n in calc_notes if "excluded" in n]

    cost = _cost_screening(args, result, thresholds)

    svg, map_note, interactive = None, None, None
    if args.report:
        svg, map_note = render_network_svg(net, {r.bus: (r.scr, r.flag) for r in rows},
                                            scmva={r.bus: r.scmva for r in rows})
        compare = None
        other = "iec60909" if args.method == "classical" else "classical"
        if not args.no_compare and rep.ready(other):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                warnings.simplefilter("ignore", DeprecationWarning)
                other_rows = scan_buses(net, plant_mw=args.plant_mw, method=other,
                                        case=args.case, thresholds=thresholds)
            compare = {ids[r.bus]: r.scmva for r in other_rows if r.bus in ids}
        interactive = {"plant_mw": args.plant_mw, "compare": compare,
                       "primary_label": _short_label(args.method),
                       "compare_label": _short_label(other)}
    _print_summary(result)
    if cost:
        _print_costs(cost["rows"])
    _write_outputs(result, args, notes=notes, network_svg=svg, network_note=map_note,
                   interactive=interactive, cost=cost)
    if cost and args.cost_out:
        from .cost import write_cost_csv

        print(f"Costs written:   {write_cost_csv(cost['rows'], args.cost_out)}")
    return 0


def _cost_screening(args, result, thresholds):
    """Build cost screening if any cost option was given; else None."""
    wanted = any([args.cost, args.site_costs, args.condenser_cost_per_mva is not None,
                  args.gen_tie_cost_per_mile is not None, args.cost_out])
    if not wanted:
        return None
    from .cost import CostInputs, read_site_costs_csv, screen_costs

    sites = read_site_costs_csv(args.site_costs) if args.site_costs else {}
    known = {p.plant_id[4:] if p.plant_id.startswith("Bus ") else p.plant_id for p in result.plants}
    unknown = [b for b in sites if b not in known]
    if unknown:
        raise InputError(f"Site cost file lists bus(es) not in the scan: {', '.join(unknown[:8])}. "
                         "Use the bus labels shown in the scan (see 'scr-screen sites-template').")
    inputs = CostInputs(
        plant_mw=args.plant_mw,
        target_scr=args.target_scr if args.target_scr is not None else thresholds.weak_below,
        condenser_xdss_pu=args.condenser_xdss, condenser_xt_pu=args.condenser_xt,
        condenser_cost_per_mva=args.condenser_cost_per_mva,
        gen_tie_cost_per_mile=args.gen_tie_cost_per_mile, sites=sites,
    )
    return {"rows": screen_costs(result.plants, inputs), "inputs": inputs,
            "target_follows_weak": args.target_scr is None}


def _print_costs(rows, n=10):
    def money(v):
        return "-" if v is None else f"${v / 1e6:,.1f}M"
    print(f"\nCost screening (cheapest first, top {min(n, len(rows))}):")
    print(f"{'#':>3} {'Bus':<12}{'SCR':>7}{'Target':>15}{'Cond. MVA':>11}{'Cond. cost':>12}{'Gen-tie':>10}{'POI':>9}{'Total':>11}")
    for i, r in enumerate(rows[:n], start=1):
        flag = "" if r.complete else "  (incomplete)"
        tc = "meets" if r.meets_target else f"max {r.max_at_target_mw:,.0f} MW"
        print(f"{i:>3} {r.bus_id[:11]:<12}{r.scr:>7.2f}{tc:>15}{r.condenser_mva:>11.1f}{money(r.condenser_cost):>12}"
              f"{money(r.gen_tie_cost):>10}{money(r.poi_cost):>9}{money(r.total_cost):>11}{flag}")
    below = [r for r in rows if not r.meets_target]
    if below:
        print(f"{len(below)} of {len(rows)} bus(es) below the target SCR: use a smaller plant (max shown) or add the condenser.")
    print("Screening-level only: excludes network upgrades. All costs are your inputs.")


def _cmd_check(args) -> int:
    from .check import check_network
    from .loaders import load_network

    path = Path(args.network)
    rep = check_network(load_network(path))
    _print_check(rep, path.name)
    return 0 if (rep.ready("classical") or rep.ready("iec60909")) else 2


def _print_check(rep, name):
    print(f"Network check: {name} ({rep.n_buses} in-service buses)")
    icon = {"error": "ERROR  ", "warning": "WARNING", "info": "info   "}
    scope = {"both": "", "classical": " [classical]", "iec60909": " [IEC 60909]", "report": " [report]"}
    for f in sorted(rep.findings, key=lambda f: ["error", "warning", "info"].index(f.level)):
        print(f"  {icon[f.level]}{scope[f.applies_to]} {f.message}")
    for m in ("classical", "iec60909"):
        print(f"  Ready for {_short_label(m)}: {'yes' if rep.ready(m) else 'no'}")


def _cmd_convert(args) -> int:
    from .loaders import load_network, save_network

    net = load_network(args.source)
    out = save_network(net, args.target)
    print(f"Converted {Path(args.source).name} -> {out}")
    print("Fill in any missing short-circuit columns (gen: xdss_pu, sn_mva, rdss_ohm, cos_phi, vn_kv; "
          "ext_grid: s_sc_max_mva, rx_max), then run: scr-screen check " + str(out))
    return 0


def _cmd_sites_template(args) -> int:
    from .cost import write_site_template
    from .loaders import load_network
    from .netmap import bus_label

    net = load_network(args.network)
    live = [int(b) for b in net.bus.index[net.bus["in_service"]]]
    labels = [bus_label(net, b) for b in live]
    if len(set(labels)) != len(labels):
        labels = [str(b) for b in live]
    path = write_site_template(labels, args.path)
    print(f"Site cost template written: {path} ({len(labels)} buses)")
    print("Fill in distance_mi and/or poi_cost_usd for candidate buses (leave others blank).")
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
                   interactive: dict | None = None, cost: dict | None = None) -> None:
    if args.report:
        path = write_html_report(result, args.report, title=args.title, notes=notes,
                                 network_svg=network_svg, network_note=network_note,
                                 interactive=interactive, cost=cost)
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

    e = sub.add_parser("example", help="copy example files (IEEE 39-bus network, site costs, plants) to a folder")
    e.add_argument("folder", nargs="?", default="scr-screen-example",
                   help="destination folder (default: scr-screen-example)")
    e.add_argument("--overwrite", action="store_true", help="replace existing files")
    e.set_defaults(func=_cmd_example)

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

    c = sub.add_parser("check", help="check a network file is ready for scanning")
    c.add_argument("network", help="network file (.json, .xlsx, .m, .mat)")
    c.set_defaults(func=_cmd_check)

    v = sub.add_parser("convert", help="convert a network file (e.g. MATPOWER) to .xlsx or .json")
    v.add_argument("source", help="input network file (.json, .xlsx, .m, .mat)")
    v.add_argument("target", help="output file (.xlsx to edit in Excel, or .json)")
    v.set_defaults(func=_cmd_convert)

    st = sub.add_parser("sites-template", help="write a site cost CSV listing every bus of a network")
    st.add_argument("network", help="network file (.json, .xlsx, .m, .mat)")
    st.add_argument("path", help="where to save the template, e.g. sites.csv")
    st.set_defaults(func=_cmd_sites_template)

    s = sub.add_parser("scan", help="scan every bus of a network (network mode)")
    s.add_argument("network", help="network file: .json (pandapower), .xlsx (pandapower Excel), "
                   ".m or .mat (MATPOWER)")
    s.add_argument("--plant-mw", type=float, required=True, help="plant size to screen at each bus")
    s.add_argument("--method", choices=["classical", "iec60909"], default="classical",
                   help="short-circuit method (default classical)")
    s.add_argument("--case", choices=["max", "min"], default="max",
                   help="IEC 60909 case (default max; ignored for classical)")
    s.add_argument("--no-compare", action="store_true",
                   help="skip the second method (the report's method comparison chart)")
    g = s.add_argument_group("cost screening (optional; all costs are your own inputs)")
    g.add_argument("--cost", action="store_true", help="add cost screening (condenser sizing) to the scan")
    g.add_argument("--site-costs", metavar="CSV", help="per-bus distance_mi and poi_cost_usd "
                   "(see 'scr-screen sites-template')")
    g.add_argument("--condenser-cost-per-mva", type=float, metavar="USD",
                   help="synchronous condenser installed cost, $ per MVA")
    g.add_argument("--gen-tie-cost-per-mile", type=float, metavar="USD", help="gen-tie line cost, $ per mile")
    g.add_argument("--target-scr", type=float, metavar="X",
                   help="SCR to reach with mitigation (default: the --weak threshold)")
    g.add_argument("--condenser-xdss", type=float, default=0.20, metavar="PU",
                   help="condenser sub-transient reactance on its own base (default 0.20, typical)")
    g.add_argument("--condenser-xt", type=float, default=0.10, metavar="PU",
                   help="condenser step-up transformer reactance on condenser base (default 0.10, typical)")
    g.add_argument("--cost-out", metavar="CSV", help="write the cost table to a CSV file")
    common(s)
    s.set_defaults(func=_cmd_scan)
    return parser


if __name__ == "__main__":
    sys.exit(main())
