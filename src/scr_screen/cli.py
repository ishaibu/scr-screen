"""Command-line tool: ``scr-screen``.

Examples:
    scr-screen example                      (copies example files into ./scr-screen-example)
    scr-screen template plants.csv
    scr-screen run plants.csv --report report.html --out results.csv
    scr-screen check mynetwork.xlsx
    scr-screen convert case.m mynetwork.xlsx
    scr-screen scan mynetwork.xlsx --plant-mw 300 --report scan.html --open
    scr-screen sites-template mynetwork.xlsx sites.csv
    scr-screen interactions mynetwork.xlsx --buses 11,12,13,16,17 --out groups.csv
    scr-screen scan mynetwork.xlsx --plant-mw 300 --report scan.html --n1
    scr-screen scan mynetwork.xlsx --plant-mw 300 --report scan.html --groups groups.csv
    scr-screen scan mynetwork.xlsx --plant-mw 300 --report scan.html --emt-triage
    scr-screen triage mynetwork.xlsx --buses 12,16 --plant-mw 300 --poi-info poi_info.csv --report triage.html
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
    from dataclasses import replace

    from .io import read_plants_csv_detail
    from .metrics import mva_source_text, plant_mva

    plants, poi, sources = read_plants_csv_detail(_existing(args.csv, "Input file"))
    notes = []
    if args.power_factor is not None:
        # Fill in an ESTIMATED MVA (MW ÷ power factor) for plants with no MVA rating of their own.
        for k, p in enumerate(plants):
            if p.rating_mva is None:
                mva, kind = plant_mva(p.rating_mw, power_factor=args.power_factor, where=f"plant '{p.plant_id}'")
                plants[k] = replace(p, rating_mva=mva)
                sources[p.plant_id] = mva_source_text(p.rating_mw, mva, kind, power_factor=args.power_factor)
    if args.basis.upper() == "MVA" and sources:
        est = [pid for pid, t in sources.items() if "ESTIMATED" in t]
        notes.append("MVA ratings used on the MVA basis: "
                     + "; ".join(f"{pid}: {t.split(';')[0]}" for pid, t in sources.items()) + "."
                     + (" Estimated ratings use MW ÷ power factor; inverter nameplate MVA is usually higher, "
                        "which gives lower (more conservative) ratios, so use the nameplate when it is known."
                        if est else ""))
        print(notes[-1])
    result = screen(plants, basis=args.basis, thresholds=_thresholds(args),
                    source="direct input", poi_names=poi)
    if result.excluded:
        notes.append(_excluded_note(result.excluded))
        print(notes[-1])
    _print_summary(result)
    _write_outputs(result, args, notes=notes)
    return 0


def _excluded_note(ids) -> str:
    return ("Left out on the MW basis (0 MW, e.g. STATCOMs): " + ", ".join(ids)
            + ". Devices with no active power count only on the MVA basis (NERC's WSCR-MVA); use --basis MVA.")


def _cmd_scan(args) -> int:
    if not args.plant_mw > 0:
        raise InputError(f"Plant size (--plant-mw) must be greater than zero, got {args.plant_mw:g}.")
    basis = args.basis.upper()
    if args.dashboard and args.method == "classical":
        args.emt_triage = True  # the dashboard shows every view the classical method offers
    if args.emt_triage:
        if args.method != "classical":
            raise InputError("EMT triage (--emt-triage) uses the classical method. Remove --method iec60909.")
        _check_ibr_threshold(args.ibr_threshold)
        args.n1 = True  # the triage uses the worst single outage
    elif args.poi_info or args.ibr_threshold != 0.5:
        raise InputError("--poi-info and --ibr-threshold are used with --emt-triage; add --emt-triage.")
    mva_note = _resolve_plant_mva(args, basis)
    rating = args.plant_mva if basis == "MVA" else args.plant_mw  # the size used in every ratio
    from .check import check_network
    from .loaders import load_network
    from .netmap import bus_label, render_network_svg
    from .network import scan_buses

    path = _existing(args.network, "Network file")
    net = load_network(path)
    gen_out_note = _apply_gen_out(args, net)
    devices, triage_notes = [], []
    if args.emt_triage:
        from .triage import detect_devices, prepare_network

        devices = detect_devices(net)
        triage_notes = prepare_network(net)
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
        rows = scan_buses(net, plant_mw=rating, method=args.method,
                          case=args.case, thresholds=thresholds, notes=calc_notes)

    # Label buses by name (e.g. IEEE bus numbers); fall back to index if names repeat.
    ids, use_names = _bus_ids(net, [r.bus for r in rows])
    groups_full = _scan_groups_full(args, ids)
    # Fixed member sizes from the groups file, on the chosen basis. On the MW basis a
    # member with mw = 0 (e.g. a STATCOM) is left out of its group.
    sizes: dict[str, float] = {}
    dropped: list[str] = []
    for pid, (_, mw, mva) in groups_full.items():
        if mw is None:
            continue
        if basis == "MW" and mw == 0:
            dropped.append(pid)
        else:
            sizes[pid] = mva if basis == "MVA" else mw
    groups = {pid: g for pid, (g, _, _) in groups_full.items() if pid not in dropped}
    plants = [Plant(ids[r.bus], scmva=r.scmva, rating_mw=args.plant_mw,
                    rating_mva=args.plant_mva if basis == "MVA" else None, group=groups.get(ids[r.bus]))
              for r in rows]
    poi = {ids[r.bus]: str(r.bus) for r in rows}  # position in the network file (from 0)
    label = METHOD_LABELS[args.method]
    if args.method == "iec60909":
        label += f", case '{args.case}'"
    est = (f"; plant MVA estimated from power factor {args.power_factor:g}"
           if basis == "MVA" and getattr(args, "mva_kind", None) == "estimated" else "")
    result = screen(plants, basis=basis, thresholds=thresholds,
                    source=f"network model ({path.name}), {label}{est}", poi_names=poi)
    if sizes:
        result = _resize_groups(result, sizes, rating, thresholds)
    result.groups.sort(key=lambda g: g.group)  # scan order is by SCR; list groups by name
    size_txt = (f"{args.plant_mw:g} MW / {args.plant_mva:g} MVA" if basis == "MVA" else f"{args.plant_mw:g} MW")
    notes = [f"Bus scan: a hypothetical {size_txt} plant was screened at each bus, "
             "one at a time" + (" (ratios on the MVA basis)" if basis == "MVA" else "") + ". "
             + ("Buses listed in the groups file were also screened together with WSCR, "
                + ("each with a plant of the same size" if not sizes else
                   "using the sizes given in the groups file where present and the plant size above elsewhere")
                + "; WSCR assumes the plants in a group are "
                "fully interacting, so group only buses that are electrically close."
                if groups else
                "Nearby plants should also be checked together with WSCR (add --groups)."),
             ("Bus labels are the bus names in the network file. The Model index column is "
              "each bus's position in the file, counting from 0 (so Bus 30 can be index 29)."
              if use_names else
              "Bus labels are model indices (each bus's position in the network file, counting from 0); "
              "bus names were not unique.")]
    notes += [n for n in calc_notes if "excluded" in n or n.startswith(("Voltage base:", "Nominal ratio:"))]
    if gen_out_note:
        notes.append(gen_out_note)
    if mva_note:
        notes.append(mva_note)
    if dropped:
        notes.append("Left out of their groups on the MW basis (0 MW, e.g. STATCOMs): " + ", ".join(dropped)
                     + ". Devices with no active power count only on the MVA basis (NERC's WSCR-MVA); "
                     "use --basis MVA with --plant-mva.")
    result, extra, strength_notes = _network_strength(args, net, rows, ids, result, rating, sizes)
    zb = extra.pop("_zb", None)
    n1z = extra.pop("_n1z", {})
    notes += strength_notes
    tri = None
    if args.emt_triage:
        tri, tri_notes = _scan_triage(args, net, zb, rows, ids, result, devices, thresholds)
        notes += triage_notes + tri_notes
        extra["tri"] = {pid: {**t["live"], "L": t["level"],
                              "w": [f"P{x.level} {x.situation}: {x.detail}" for x in t["triggers"]]}
                        for pid, t in tri.items()}

    cost = _cost_screening(args, result, thresholds)

    svg, map_note, interactive = None, None, None
    dash = None
    if args.report or args.dashboard:
        svg, map_note = render_network_svg(net, {r.bus: (r.scr, r.flag) for r in rows},
                                            scmva={r.bus: r.scmva for r in rows},
                                            n1={r.bus: extra["n1"][ids[r.bus]] for r in rows
                                                if ids[r.bus] in extra["n1"]},
                                            heat=not args.no_heatmap)
        compare = None
        other = "iec60909" if args.method == "classical" else "classical"
        if not args.no_compare and rep.ready(other):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                warnings.simplefilter("ignore", DeprecationWarning)
                other_rows = scan_buses(net, plant_mw=rating, method=other,
                                        case=args.case, thresholds=thresholds)
            compare = {ids[r.bus]: r.scmva for r in other_rows if r.bus in ids}
        interactive = {"plant_mw": rating, "unit": basis, "compare": compare,
                       "primary_label": _short_label(args.method),
                       "compare_label": _short_label(other), **extra}
    if args.dashboard:
        from .dashboard import thevenin_data

        dash = {"buses": {}, "version": result.tool_version}
        for r in rows:
            kv = float(net.bus.at[r.bus, "vn_kv"])
            if not kv > 0:
                continue
            if zb is not None and r.bus in zb.pos:  # Thevenin data (classical method)
                k = zb.pos[r.bus]
                dash["buses"][ids[r.bus]] = thevenin_data(kv, complex(zb.z[k, k]), n1z.get(r.bus))
            else:
                dash["buses"][ids[r.bus]] = {"kv": float(f"{kv:g}")}
        if zb is not None:
            if basis == "MW":
                name = f'"{path.name}"' if " " in path.name else path.name
                dash["cmd"] = f"scr-screen triage {name} --buses {{bus}} --plant-mw {{size}} --report bus.html"
    _print_summary(result)
    if tri:
        _print_scan_triage(tri)
    if cost:
        _print_costs(cost["rows"], unit=basis)
    _write_outputs(result, args, notes=notes, network_svg=svg, network_note=map_note,
                   interactive=interactive, cost=cost, triage=tri, dashboard=dash)
    if cost and args.cost_out:
        from .cost import write_cost_csv

        print(f"Costs written:   {write_cost_csv(cost['rows'], args.cost_out)}")
    return 0


def _scan_triage(args, net, zb, rows, ids, result, devices, thresholds):
    """EMT triage for every scanned bus at the scan's plant size.

    Returns ({plant_id: {"level", "triggers", "unknown", "live"}}, notes). "live" holds the
    size-independent part (nearby IBRs and devices, user answers, OEM minimum, group) for the
    report, which re-evaluates the strength triggers as the plant size changes.
    """
    from .triage import (NERC_NOT_RULE_OUT, NERC_RULE, PRIORITY_NOTE, PRIORITY_RULES, USER_FIELDS, fixed_triggers,
                         info_for, level_of, metric_triggers, oem_trigger, proximity, read_poi_info)

    info = read_poi_info(_existing(args.poi_info, "POI information file")) if args.poi_info else {}
    labels = {pid[4:] for pid in ids.values()}
    unknown = [k for k in info if k != "all" and k not in labels]
    if unknown:
        raise InputError(f"POI information file lists bus(es) not in the scan: {', '.join(unknown[:8])}.")
    label = lambda b: ids.get(b, f"Bus {b}")  # noqa: E731
    pid_bus = {ids[r.bus]: r.bus for r in rows}
    ibrs = _ibrs(net)
    from .strength import capacitor_mvar

    caps = capacitor_mvar(net)
    gof, gval, sval = {}, {}, {}
    for g in result.groups:
        gval[g.group] = (g.wscr, g.cscr)
        for k, pid in enumerate(g.plant_ids):
            gof[pid] = g.group
            if g.member_scrif is not None:
                sval[pid] = g.member_scrif[k]
    out = {}
    for p in result.plants:
        b = pid_bus[p.plant_id]
        near_i, near_d = proximity(zb, b, ibrs, devices, label, args.ibr_threshold)
        pinfo = info_for(info, p.plant_id[4:])
        fixed = fixed_triggers(near_i, near_d, pinfo)
        values = [("SCR (intact)", p.scr)]
        if p.n1_scr is not None:
            values.append(("SCR (N-1)", p.n1_scr))
        if caps.get(b, 0.0) > 0 and p.escr is not None:
            values.append(("ESCR (intact)", p.escr))
        if p.plant_id in sval:
            values.append(("SCRIF (intact)", sval[p.plant_id]))
        grp = gof.get(p.plant_id)
        if grp:
            w, cs = gval[grp]
            values.append(("group WSCR (intact)", w))
            if cs is not None:
                values.append(("group CSCR (intact)", cs))
        oem = pinfo.oem_min_scr if pinfo else None
        low = min(p.scr, p.n1_scr) if p.n1_scr is not None else p.scr
        trig = metric_triggers(values, thresholds) + oem_trigger(low, oem) + fixed
        n_unknown = (sum(v == "unknown" for v in pinfo.answers.values()) if pinfo else len(USER_FIELDS))
        out[p.plant_id] = {"level": level_of(trig), "triggers": trig, "unknown": n_unknown,
                           "live": {"f": level_of(fixed), "r": [f"P{t.level} {t.situation}: {t.detail}" for t in fixed],
                                    "o": oem, "g": grp or "", "u": n_unknown}}
    notes = [f"EMT triage: {NERC_RULE} {NERC_NOT_RULE_OUT} {PRIORITY_NOTE} {PRIORITY_RULES} In a scan, the "
             "conditions are the intact network and the worst single outage.",
             f"EMT triage, nearby: an existing IBR or device is nearby when max(IF_ij, IF_ji) with the bus is at least "
             f"{args.ibr_threshold:g} (--ibr-threshold; SCR-Screen's default judgment value). Series compensation is "
             "found as lines with negative series reactance, FACTS as svc/ssc/tcsc and HVdc as vsc/dcline elements."
             " A negative reactance can also be an equivalent branch of a reduced model; answering series_compensation = no in the POI information file tells the triage it is not a series capacitor."]
    if not args.poi_info:
        notes.append("EMT triage: no POI information file (--poi-info) was given, so the situations a network model "
                     "cannot show (e.g. pre-existing oscillation, RAS, system events) are not checked. For a full data sheet per "
                     "POI, use: scr-screen triage.")
    return out, notes


def _print_scan_triage(tri) -> None:
    counts = [sum(t["level"] == k for t in tri.values()) for k in (1, 2, 3)]
    print(f"EMT triage: Priority 1: {counts[0]}  Priority 2: {counts[1]}  Priority 3: {counts[2]}"
          " (details in the report; per-POI data sheets: scr-screen triage).")


def _bus_ids(net, buses) -> tuple[dict[int, str], bool]:
    """{bus index: "Bus <name>"}; falls back to indices if names repeat."""
    from .netmap import bus_label

    labels = {b: bus_label(net, b) for b in buses}
    use_names = len(set(labels.values())) == len(labels)
    return {b: f"Bus {labels[b] if use_names else b}" for b in buses}, use_names


def _resolve_plant_mva(args, basis: str) -> str | None:
    """Set args.plant_mva from --plant-mva, --inverters x --inverter-mva, or --power-factor.

    Returns a note on where the MVA came from (None when no MVA rating is given).
    """
    from .metrics import mva_source_text, plant_mva

    mva, kind = plant_mva(args.plant_mw, mva=args.plant_mva, inverters=args.inverters,
                          inverter_mva=args.inverter_mva, power_factor=args.power_factor,
                          where="the scanned plant")
    args.plant_mva = mva
    args.mva_kind = kind
    if basis == "MVA" and mva is None:
        raise InputError("The MVA basis needs the plant's MVA rating. Give ONE of: --plant-mva 1650 "
                         "(nameplate), --inverters 55 --inverter-mva 4.2 (55 × 4.2 MVA), or "
                         "--power-factor 0.95 (an estimate: MW ÷ power factor).")
    if mva is None:
        return None
    text = mva_source_text(args.plant_mw, mva, kind, args.inverters, args.inverter_mva, args.power_factor)
    if basis != "MVA":
        return (f"A plant MVA rating ({mva:,.1f} MVA) is available, but every ratio uses MW (the default); "
                "add --basis MVA to use it.")
    print(f"Plant MVA rating: {text}.")
    return f"Plant MVA rating (used on the MVA basis): {text}."


def _resize_groups(result, sizes, rating, thresholds):
    """Recompute group WSCR with the member sizes from the groups file (others use `rating`)."""
    from dataclasses import replace

    from .metrics import classify, wscr

    scm = {p.plant_id: p.scmva for p in result.plants}
    out = []
    for g in result.groups:
        ps = [sizes.get(pid, rating) for pid in g.plant_ids]
        ss = [scm[pid] for pid in g.plant_ids]
        value = wscr(ss, ps)
        out.append(replace(g, total_rating=sum(ps), wscr=value, flag=classify(value, thresholds).value,
                           min_individual_scr=min(s / p for s, p in zip(ss, ps)), member_ratings=ps))
    result.groups = out
    return result


def _apply_gen_out(args, net) -> str | None:
    """Take the generators at the --gen-out buses out of service (a minimum-generation case)."""
    if not getattr(args, "gen_out", None):
        return None
    from .netmap import bus_label

    live = [int(b) for b in net.bus.index[net.bus["in_service"]]]
    ids, _ = _bus_ids(net, live)
    by_label = {pid[4:]: b for b, pid in ids.items()}
    wanted = [x.strip() for x in args.gen_out.split(",") if x.strip()]
    wanted = [w[4:].strip() if w.lower().startswith("bus ") else w for w in wanted]
    if not wanted:
        raise InputError("--gen-out needs at least one bus label, e.g. --gen-out 30,32.")
    taken = []
    for w in wanted:
        if w not in by_label:
            raise InputError(f"--gen-out: bus {w} not found. Use the bus labels shown in scan reports.")
        b = by_label[w]
        mask = (net.gen["bus"] == b) & net.gen["in_service"] if len(net.gen) else []
        if not len(net.gen) or not bool(mask.any()):
            if len(net.ext_grid) and bool(((net.ext_grid["bus"] == b) & net.ext_grid["in_service"]).any()):
                raise InputError(f"--gen-out: bus {w} has an external grid (a network equivalent), not a "
                                 "generator unit; it cannot be taken out with --gen-out.")
            raise InputError(f"--gen-out: bus {w} has no in-service generator.")
        net.gen.loc[mask, "in_service"] = False
        taken.append(f"Bus {w}")
    return ("Minimum-generation case: the generators at " + ", ".join(taken) + " were taken out of service "
            "for this scan (--gen-out), so their short-circuit contribution is excluded.")


def _network_strength(args, net, rows, ids, result, rating=None, sizes=None):
    """SCRIF and CSCR for groups, ESCR where capacitors exist, and N-1 worst case.

    Returns (updated result, extra data for the live report, notes). Interaction
    factors, CSCR and N-1 use the classical flat-start Z-bus, so they are computed
    only when the classical method is the primary method.
    """
    from dataclasses import replace

    from .classical import build_zbus
    from .strength import capacitor_mvar, composite_scmva, interaction_matrix, interaction_sums, n1_worst

    extra = {"ifsum": {}, "ifm": {}, "cscmva": {}, "n1": {}, "n1_outage": {}, "qc": {}}
    sizes = sizes or {}
    notes: list[str] = []
    caps = {b: q for b, q in capacitor_mvar(net).items() if b in ids}
    if not (result.groups or args.n1 or caps):
        return result, extra, notes
    if args.method != "classical":
        if args.n1:
            raise InputError("N-1 screening (--n1) uses the classical method. Remove --method iec60909 "
                             "or remove --n1.")
        if result.groups:
            notes.append("SCRIF and CSCR use the classical network model, so they are shown only "
                         "when the classical method is the primary method.")
        zb = None
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            zb = build_zbus(net)
    p_mw = rating if rating is not None else args.plant_mw  # plant size on the chosen basis
    unit = args.basis.upper() if getattr(args, "basis", None) else "MW"
    pid_bus = {ids[r.bus]: r.bus for r in rows}
    scm = {r.bus: r.scmva for r in rows}
    plant_upd: dict[str, dict] = {}
    group_upd: dict[str, dict] = {}
    if zb is not None and result.groups:
        for g in result.groups:
            buses = [pid_bus[p] for p in g.plant_ids]
            ifs = interaction_matrix(zb, buses)
            sums = interaction_sums(ifs, buses)
            size = {b: sizes.get(pid, p_mw) for pid, b in zip(g.plant_ids, buses)}
            member_scrif = []
            for pid, b in zip(g.plant_ids, buses):
                value = scm[b] / (size[b] + sum(ifs[(b, j)] * size[j] for j in buses if j != b))
                member_scrif.append(value)
                if pid not in sizes:  # the results table shows SCRIF only for members of the scan's size
                    plant_upd.setdefault(pid, {})["scrif"] = value
                extra["ifsum"][pid] = sums[b]
                extra["ifm"][pid] = {qid: ifs[(b, j)] for qid, j in zip(g.plant_ids, buses) if j != b}
            cs = composite_scmva(zb, buses)
            group_upd[g.group] = {"cscr": cs / sum(size.values()), "member_scrif": member_scrif}
            extra["cscmva"][g.group] = cs
        notes.append("SCRIF_i = SCMVA_i ÷ (P_i + Σ IF_ij·P_j), with interaction factors IF_ij = |Z_ij ÷ Z_jj| "
                     "from the classical network impedance matrix (NERC Reliability Guideline, 2017). "
                     f"CSCR = short-circuit MVA with the group's POIs tied together ÷ total {unit}; NERC's "
                     "definition ties the plants' medium-voltage buses, which are not in a transmission model"
                     + (", and divides by the plants' nominal MVA ratings (use --basis MVA to match)."
                        if unit == "MW" else ", and divides by the plants' nominal MVA ratings, as here."))
    n1z: dict = {}
    if zb is not None and args.n1:
        n1 = n1_worst(zb, [r.bus for r in rows], label=lambda b: ids.get(b, f"Bus {b}"))
        n1z = dict(n1.zth)
        for r in rows:
            pid = ids[r.bus]
            plant_upd.setdefault(pid, {}).update(n1_scr=n1.scmva[r.bus] / p_mw, n1_outage=n1.outage[r.bus])
            extra["n1"][pid] = n1.scmva[r.bus]
            extra["n1_outage"][pid] = n1.outage[r.bus]
        notes.append(f"N-1: each of {n1.studied} line circuits, transformer units and generator units was "
                     "removed in turn (classical method); the lowest short-circuit MVA at each bus and the outage causing it are "
                     "shown." + (f" {len(n1.skipped)} outage(s) were skipped because they would leave buses "
                                 "with no source: " + "; ".join(n1.skipped[:6])
                                 + (" …" if len(n1.skipped) > 6 else "") + "." if n1.skipped else ""))
    if caps:
        for r in rows:
            pid = ids[r.bus]
            qc = caps.get(r.bus, 0.0)
            plant_upd.setdefault(pid, {})["escr"] = (r.scmva - qc) / p_mw
            extra["qc"][pid] = qc
        notes.append(f"ESCR = (SCMVA − capacitive shunt Mvar at the bus) ÷ plant {unit}, using the network's "
                     "in-service capacitor banks (the classical 'Effective SCR'; NERC 2017 notes it is distinct "
                     "from the 'Equivalent SCR' of CIGRE, which is SCRIF).")
    result.plants = [replace(p, **plant_upd[p.plant_id]) if p.plant_id in plant_upd else p for p in result.plants]
    result.groups = [replace(g, **group_upd[g.group]) if g.group in group_upd else g for g in result.groups]
    extra["_zb"] = zb  # for EMT triage; removed by the caller
    extra["_n1z"] = n1z  # worst-outage Thevenin impedance per bus, for the dashboard; removed by the caller
    return result, extra, notes


def _cmd_interactions(args) -> int:
    from .classical import build_zbus
    from .loaders import load_network
    from .strength import interaction_matrix, suggest_groups

    if not 0 < args.threshold <= 1:
        raise InputError(f"--threshold must be above 0 and at most 1, got {args.threshold:g}.")
    path = _existing(args.network, "Network file")
    net = load_network(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        zb = build_zbus(net)
    ids, _ = _bus_ids(net, list(zb.pos))
    by_label = {pid[4:]: b for b, pid in ids.items()}
    wanted = [x.strip() for x in args.buses.split(",") if x.strip()]
    wanted = [w[4:].strip() if w.lower().startswith("bus ") else w for w in wanted]
    unknown = [w for w in wanted if w not in by_label]
    if unknown:
        raise InputError(f"Bus(es) not found or isolated: {', '.join(unknown[:8])}. Use the bus labels "
                         "shown in scan reports.")
    if len(set(wanted)) != len(wanted) or len(wanted) < 2:
        raise InputError("List at least two different buses with --buses, e.g. --buses 11,12,13.")
    buses = [by_label[w] for w in wanted]
    ifs = interaction_matrix(zb, buses)
    width = max(len(w) for w in wanted) + 5
    print(f"Interaction factors IF(row, column) = voltage change at the row bus per unit change at the "
          f"column bus\n(classical network model of {path.name}; 1 = same bus, 0 = no interaction)\n")
    print(" " * width + "".join(f"{('Bus ' + w):>{width}}" for w in wanted))
    for w, i in zip(wanted, buses):
        print(f"{('Bus ' + w):<{width}}" + "".join(f"{ifs[(i, j)]:>{width}.2f}" for j in buses))
    groups = suggest_groups(ifs, buses, args.threshold)
    print(f"\nSuggested groups (every pair of members has an interaction factor ≥ {args.threshold:g} "
          "in at least one direction):")
    if not groups:
        print("  none: the listed buses interact weakly; screen them one at a time.")
    rows = []
    for k, g in enumerate(groups, start=1):
        print(f"  G{k}: " + ", ".join(ids[b] for b in g))
        rows += [(ids[b][4:], f"G{k}") for b in g]
    alone = [ids[b] for b in buses if all(b not in g for g in groups)]
    if alone:
        print("  Screened alone: " + ", ".join(alone))
    print("The threshold is SCR-Screen's default judgment value, not an industry standard; adjust with --threshold.")
    if args.out:
        import csv

        out = Path(args.out)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bus", "group"])
            w.writerows(rows)
        print(f"Groups written:  {out}  (use with: scr-screen scan {path.name} --plant-mw ... --groups {out.name})")
    return 0


def _cmd_triage(args) -> int:
    """EMT study triage: a system strength data sheet and a priority for each listed POI."""
    import copy
    from datetime import datetime, timezone

    from .check import check_network
    from .classical import build_zbus
    from .loaders import load_network
    from .strength import capacitor_mvar, composite_scmva, interaction_matrix, n1_worst
    from .triage import (NERC_NOT_RULE_OUT, NERC_RULE, PRIORITY_NOTE, detect_devices, info_for,
                         prepare_network, read_poi_info, thevenin, triage_poi)
    from .triage_report import write_triage_csv, write_triage_html, write_triage_json

    if not args.plant_mw > 0:
        raise InputError(f"Plant size (--plant-mw) must be greater than zero, got {args.plant_mw:g}.")
    _check_ibr_threshold(args.ibr_threshold)
    basis = args.basis.upper()
    mva_note = _resolve_plant_mva(args, basis)
    rating = args.plant_mva if basis == "MVA" else args.plant_mw
    thresholds = _thresholds(args)
    path = _existing(args.network, "Network file")
    net = load_network(path)
    devices = detect_devices(net)
    notes = prepare_network(net)
    rep = check_network(net)
    if not rep.ready("classical"):
        _print_check(rep, path.name)
        raise InputError(f"{path.name} is not ready for the classical method; see the list above.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        zb = build_zbus(net)
    ids, use_names = _bus_ids(net, list(zb.pos))
    label = lambda b: ids.get(b, f"Bus {b}")  # noqa: E731
    pois = _pick_buses(args.buses, ids, at_least=1)
    pid_of = {b: ids[b] for b in pois}
    info = read_poi_info(_existing(args.poi_info, "POI information file")) if args.poi_info else {}
    unknown = [k for k in info if k != "all" and f"Bus {k}" not in pid_of.values()]
    if unknown:
        raise InputError(f"POI information file lists POI(s) not in --buses: {', '.join(unknown[:8])}.")

    # Groups (optional): members must be among the POIs; fixed member sizes as in scan.
    groups: dict[str, list[int]] = {}
    sizes: dict[int, float] = {}
    if args.groups:
        from .io import read_bus_groups_full

        by_label = {pid[4:]: b for b, pid in pid_of.items()}
        raw = read_bus_groups_full(_existing(args.groups, "Groups file"))
        missing = [b for b in raw if b not in by_label]
        if missing:
            raise InputError(f"Groups file lists bus(es) not in --buses: {', '.join(missing[:8])}. "
                             "List every group member as a POI.")
        for b, (g, mw, mva) in raw.items():
            if mw is not None:
                if basis == "MW" and mw == 0:
                    notes.append(f"Bus {b} (0 MW) was left out of group {g} on the MW basis; use --basis MVA.")
                    continue
                sizes[by_label[b]] = mva if basis == "MVA" else mw
            groups.setdefault(g, []).append(by_label[b])
        groups = {g: m for g, m in groups.items() if len(m) > 1}

    # Conditions: intact, worst N-1, and minimum generation when --gen-out is given.
    n1 = n1_worst(zb, pois, label=label)
    zmin, min_note = None, None
    if args.gen_out:
        net_min = copy.deepcopy(net)
        min_note = _apply_gen_out(args, net_min)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            zmin = build_zbus(net_min)
        lost = [pid_of[b] for b in pois if b not in zmin.pos]
        if lost:
            raise InputError("In the minimum-generation case these POIs have no path to a source: "
                             + ", ".join(lost) + ".")
    caps = capacitor_mvar(net)
    ibr_list = _ibrs(net)
    items = []
    gmetrics: dict[int, tuple] = {}
    for g, members in groups.items():
        size = {b: sizes.get(b, rating) for b in members}
        ifs = interaction_matrix(zb, members)
        tot = sum(size.values())
        scm = {b: 100.0 / abs(zb.z[zb.pos[b], zb.pos[b]]) for b in members}
        w = sum(scm[b] * size[b] for b in members) / tot ** 2
        cs = composite_scmva(zb, members) / tot
        for b in members:
            sif = scm[b] / (size[b] + sum(ifs[(b, j)] * size[j] for j in members if j != b))
            gmetrics[b] = (g, w, cs, sif)
    for b in pois:
        pid = pid_of[b]
        kv = float(net.bus.at[b, "vn_kv"])
        r = sizes.get(b, rating)
        qc = caps.get(b, 0.0)
        conds = [thevenin("intact", "", complex(zb.z[zb.pos[b], zb.pos[b]]), kv, r, qc)]
        out_text = (f"{n1.outage[b]} out" if n1.outage[b] != "none" else "no single outage lowers it")
        conds.append(thevenin("N-1", out_text, n1.zth[b], kv, r, qc))
        if zmin is not None:
            conds.append(thevenin("minimum generation", "generators at " + args.gen_out.replace(",", ", ")
                                  + " out", complex(zmin.z[zmin.pos[b], zmin.pos[b]]), kv, r, qc))
        from .triage import proximity

        near_i, near_d = proximity(zb, b, ibr_list, devices, label, args.ibr_threshold)
        g = gmetrics.get(b)
        items.append(triage_poi(pid, b, kv, r, basis, conds, thresholds, near_i, near_d,
                                info_for(info, pid[4:]), *(g if g else (None, None, None, None))))
    items.sort(key=lambda it: (it.level, it.lowest_scr))

    notes = [NERC_RULE, NERC_NOT_RULE_OUT, PRIORITY_NOTE,
             "Short-circuit data: classical flat-start Z-bus on 100 MVA (1.0 pu pre-fault voltage, no IEC "
             "c-factor; loads, shunts and line charging ignored); inverter-based resources (sgen, storage) are "
             "excluded from the short-circuit MVA, as NERC requires.",
             f"N-1: each of {n1.studied} line circuits, transformer units and generator units was removed in turn; "
             "the worst outage for each POI is shown" + (f" ({len(n1.skipped)} islanding outage(s) skipped)"
                                                         if n1.skipped else "") + ". The minimum-generation case, "
             "when given, is computed with the network intact.",
             f"Nearby: an existing IBR or device is 'nearby' when its interaction with the POI, max(IF_ij, IF_ji) "
             f"with IF_ij = |Z_ij ÷ Z_jj|, is at least {args.ibr_threshold:g} (--ibr-threshold; SCR-Screen's "
             "default judgment value, not an industry standard). If the model already contains the plant being "
             "screened as an sgen, it appears as a nearby IBR at its own bus; ignore that entry.",
             "Series compensation is found as lines with negative series reactance; FACTS as svc, ssc and tcsc "
             "elements; HVdc as vsc and dcline elements. Devices modeled another way (e.g. as an equivalent "
             "impedance) are not found: answer them in the POI information file."
             " A negative reactance can also be an equivalent branch of a reduced model; answering series_compensation = no in the POI information file tells the triage it is not a series capacitor."] + notes
    if min_note:
        notes.append(min_note.replace("for this scan (--gen-out)", "in the minimum-generation case only (--gen-out)"))
    if mva_note:
        notes.append(mva_note)
    if not args.poi_info:
        notes.append("No POI information file was given (--poi-info), so the situations a model cannot show "
                     "are listed as not checked for every POI.")
    source = f"network model ({path.name}), classical flat-start (1.0 pu)"
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _print_triage(items, basis)
    if args.report:
        out = write_triage_html(items, args.report, title=args.title, source=source, notes=notes,
                                thresholds={"very_weak_below": thresholds.very_weak_below,
                                            "weak_below": thresholds.weak_below}, run_utc=run_utc)
        print(f"Report written:  {out}")
        if args.open:
            import webbrowser

            webbrowser.open(Path(out).resolve().as_uri())
            print("Opened the report in your browser.")
    if args.out:
        out = Path(args.out)
        if out.suffix.lower() == ".csv":
            write_triage_csv(items, out)
        elif out.suffix.lower() == ".json":
            write_triage_json(items, out, {"source": source, "run_utc": run_utc, "basis": basis,
                                           "thresholds": {"very_weak_below": thresholds.very_weak_below,
                                                          "weak_below": thresholds.weak_below},
                                           "notes": notes})
        else:
            raise InputError("--out must end in .csv or .json")
        print(f"Results written: {out}")
    return 0


def _check_ibr_threshold(v) -> None:
    if not 0 < v <= 1:
        raise InputError(f"--ibr-threshold must be above 0 and at most 1, got {v:g}.")


def _ibrs(net):
    from .triage import existing_ibrs

    return existing_ibrs(net)


def _pick_buses(text, ids, at_least=1) -> list[int]:
    """Bus indices for a comma-separated list of bus labels (with or without 'Bus ')."""
    by_label = {pid[4:]: b for b, pid in ids.items()}
    wanted = [x.strip() for x in text.split(",") if x.strip()]
    wanted = [w[4:].strip() if w.lower().startswith("bus ") else w for w in wanted]
    unknown = [w for w in wanted if w not in by_label]
    if unknown:
        raise InputError(f"Bus(es) not found or isolated: {', '.join(unknown[:8])}. Use the bus labels "
                         "shown in scan reports.")
    if len(set(wanted)) != len(wanted):
        raise InputError("A bus is listed more than once in --buses.")
    if len(wanted) < at_least:
        raise InputError("List at least one bus with --buses, e.g. --buses 12,16.")
    return [by_label[w] for w in wanted]


def _print_triage(items, basis) -> None:
    print(f"SCR-Screen v{__version__} | EMT triage | basis {basis}")
    for it in items:
        print(f"\n{it.poi_id}  {it.kv:g} kV  plant {it.rating:,.1f} {basis}   {it.level_text}")
        print(f"  {'Condition':<20}{'SCMVA':>10}{'SCR':>8}{'X/R':>8}{'|Z| ohm':>10}  Outage or case")
        for c in it.conditions:
            xr = "inf" if c.x_over_r is None else f"{c.x_over_r:.2f}"
            print(f"  {c.condition:<20}{c.scmva:>10.1f}{c.scr:>8.3f}{xr:>8}{c.z_ohm:>10.2f}  {c.outage}")
        if it.group:
            print(f"  Group {it.group}: WSCR {it.wscr:.3f}, CSCR {it.cscr:.3f}, SCRIF {it.scrif:.3f} (intact)")
        for t in sorted(it.triggers, key=lambda t: t.level):
            print(f"  [P{t.level}] {t.situation}: {t.detail}")
        if not it.triggers:
            print("  No screening trigger found (a high system strength alone does not rule out EMT studies).")
        if it.unknown:
            print(f"  Not checked ({len(it.unknown)}): answer in --poi-info (yes / no / unknown).")
    counts = [sum(it.level == k for it in items) for k in (1, 2, 3)]
    print(f"\nPriority 1: {counts[0]}  Priority 2: {counts[1]}  Priority 3: {counts[2]}. "
          "Screening indicators only; not a substitute for studies.")


def _scan_groups(args, ids) -> dict[str, str]:
    """{plant_id: group} from --groups, checked against the scanned buses."""
    return {pid: g for pid, (g, _, _) in _scan_groups_full(args, ids).items()}


def _scan_groups_full(args, ids) -> dict[str, tuple]:
    """{plant_id: (group, mw or None, mva or None)} from --groups, checked against the scanned buses."""
    if not args.groups:
        return {}
    from .io import read_bus_groups_full

    by_label = {pid[4:]: pid for pid in ids.values()}
    raw = read_bus_groups_full(_existing(args.groups, "Groups file"))
    unknown = [b for b in raw if b not in by_label]
    if unknown:
        raise InputError(f"Groups file lists bus(es) not in the scan: {', '.join(unknown[:8])}. "
                         "Use the bus labels shown in the scan report.")
    return {by_label[b]: v for b, v in raw.items()}


def _existing(path, what: str) -> Path:
    """Return path if it exists; otherwise raise a clear error, with a hint when the
    file is in the example folder (a common slip after 'scr-screen example')."""
    p = Path(path)
    if p.exists():
        return p
    hint = ""
    alt = Path("scr-screen-example") / p
    if not p.is_absolute() and alt.exists():
        hint = (f"\nIt is in the scr-screen-example folder: run  cd scr-screen-example  first, "
                f"or use  {alt}")
    raise InputError(f"{what} not found: {p}{hint}")


def _cost_screening(args, result, thresholds):
    """Build cost screening if any cost option was given; else None."""
    wanted = any([args.cost, args.site_costs, args.condenser_cost_per_mva is not None,
                  args.gen_tie_cost_per_mile is not None, args.cost_out])
    if not wanted:
        return None
    from .cost import CostInputs, read_site_costs_csv, screen_costs

    sites = read_site_costs_csv(_existing(args.site_costs, "Site cost file")) if args.site_costs else {}
    known = {p.plant_id[4:] if p.plant_id.startswith("Bus ") else p.plant_id for p in result.plants}
    unknown = [b for b in sites if b not in known]
    if unknown:
        raise InputError(f"Site cost file lists bus(es) not in the scan: {', '.join(unknown[:8])}. "
                         "Use the bus labels shown in the scan (see 'scr-screen sites-template').")
    inputs = CostInputs(
        plant_mw=_scan_rating(args),
        target_scr=args.target_scr if args.target_scr is not None else thresholds.weak_below,
        condenser_xdss_pu=args.condenser_xdss, condenser_xt_pu=args.condenser_xt,
        condenser_cost_per_mva=args.condenser_cost_per_mva,
        gen_tie_cost_per_mile=args.gen_tie_cost_per_mile, sites=sites,
    )
    return {"rows": screen_costs(result.plants, inputs), "inputs": inputs,
            "target_follows_weak": args.target_scr is None}


def _scan_rating(args) -> float:
    """The plant size used in every ratio: MVA on the MVA basis, else MW."""
    return args.plant_mva if getattr(args, "basis", "MW").upper() == "MVA" else args.plant_mw


def _print_costs(rows, n=10, unit="MW"):
    def money(v):
        return "-" if v is None else f"${v / 1e6:,.1f}M"
    print(f"\nCost screening (cheapest first, top {min(n, len(rows))}):")
    print(f"{'#':>3} {'Bus':<12}{'SCR':>7}{'Target':>15}{'Cond. MVA':>11}{'Cond. cost':>12}{'Gen-tie':>10}{'POI':>9}{'Total':>11}")
    for i, r in enumerate(rows[:n], start=1):
        flag = "" if r.complete else "  (incomplete)"
        tc = "meets" if r.meets_target else f"max {r.max_at_target_mw:,.0f} {unit}"
        print(f"{i:>3} {r.bus_id[:11]:<12}{r.scr:>7.2f}{tc:>15}{r.condenser_mva:>11.1f}{money(r.condenser_cost):>12}"
              f"{money(r.gen_tie_cost):>10}{money(r.poi_cost):>9}{money(r.total_cost):>11}{flag}")
    below = [r for r in rows if not r.meets_target]
    if below:
        print(f"{len(below)} of {len(rows)} bus(es) below the target SCR: use a smaller plant (max shown) or add the condenser.")
    print("Screening-level only: excludes network upgrades. All costs are your inputs.")


def _cmd_check(args) -> int:
    from .check import check_network
    from .loaders import load_network

    path = _existing(args.network, "Network file")
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

    net = load_network(_existing(args.source, "Network file"))
    out = save_network(net, args.target)
    print(f"Converted {Path(args.source).name} -> {out}")
    print("Fill in any missing short-circuit columns (gen: xdss_pu, sn_mva, rdss_ohm, cos_phi, vn_kv; "
          "ext_grid: s_sc_max_mva, rx_max), then run: scr-screen check " + str(out))
    return 0


def _cmd_sites_template(args) -> int:
    from .cost import write_site_template
    from .loaders import load_network
    from .netmap import bus_label

    net = load_network(_existing(args.network, "Network file"))
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
                   interactive: dict | None = None, cost: dict | None = None,
                   triage: dict | None = None, dashboard: dict | None = None) -> None:
    if getattr(args, "dashboard", None):
        from .dashboard import write_dashboard
        from .report import render_html

        html = render_html(result, title=args.title, notes=notes, network_svg=network_svg,
                           network_note=network_note, interactive=interactive, cost=cost)
        path = write_dashboard(html, args.dashboard, dashboard)
        print(f"Dashboard written: {path}")
        if args.open and not args.report:
            import webbrowser

            webbrowser.open(Path(path).resolve().as_uri())
            print("Opened the dashboard in your browser.")
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
            write_results_json(result, out, triage=triage)
        elif out.suffix.lower() == ".csv":
            write_results_csv(result, out, triage=triage)
        else:
            raise InputError("--out must end in .csv or .json")
        print(f"Results written: {out}")


def _print_summary(result: ScreeningResult) -> None:
    print(f"SCR-Screen v{result.tool_version} | basis {result.basis} | source: {result.source}")
    print(f"{'Plant':<20}{'SCMVA':>11}{'Rating':>10}{'SCR':>9}  {'Flag':<10}{'Max, no flag':>13}")
    for p in sorted(result.plants, key=lambda p: p.scr, reverse=True):
        print(f"{p.plant_id[:19]:<20}{p.scmva:>11.1f}{p.rating:>10.1f}{p.scr:>9.3f}  "
              f"{p.flag:<10}{p.max_rating_no_flag:>13.1f}")
    by_id = {p.plant_id: p for p in result.plants}
    for g in result.groups:
        extra = f"; CSCR {g.cscr:.3f}" if g.cscr is not None else ""
        print(f"Group {g.group}: WSCR {g.wscr:.3f} ({g.flag}){extra}; plants {', '.join(g.plant_ids)}")
        scrifs = ([f"{pid} {v:.3f}" for pid, v in zip(g.plant_ids, g.member_scrif)]
                  if g.member_scrif is not None else [])
        if scrifs:
            print("  SCRIF (network-aware): " + ", ".join(scrifs))
    n1 = [p for p in result.plants if p.n1_scr is not None]
    if n1:
        print("N-1 worst case (lowest 5):")
        for p in sorted(n1, key=lambda p: p.n1_scr)[:5]:
            print(f"  {p.plant_id}: SCR {p.n1_scr:.3f} with {p.n1_outage} out (intact {p.scr:.3f})")
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
    r.add_argument("--power-factor", type=float, metavar="PF",
                   help="ESTIMATE the MVA of plants with no MVA rating as MW ÷ PF (e.g. 0.95 at the POI)")
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

    it = sub.add_parser("interactions", help="interaction factors between buses, and suggested groups for scan --groups")
    it.add_argument("network", help="network file (.json, .xlsx, .m, .mat)")
    it.add_argument("--buses", required=True, metavar="LIST", help="comma-separated bus labels, e.g. 11,12,13,16,17")
    it.add_argument("--threshold", type=float, default=0.5, metavar="X",
                    help="every pair of buses in a group must interact at least X (default 0.5)")
    it.add_argument("--out", metavar="CSV", help="write the suggested groups as a groups file (bus, group)")
    it.set_defaults(func=_cmd_interactions)

    st = sub.add_parser("sites-template", help="write a site cost CSV listing every bus of a network")
    st.add_argument("network", help="network file (.json, .xlsx, .m, .mat)")
    st.add_argument("path", help="where to save the template, e.g. sites.csv")
    st.set_defaults(func=_cmd_sites_template)

    s = sub.add_parser("scan", help="scan every bus of a network (network mode)")
    s.add_argument("network", help="network file: .json (pandapower), .xlsx (pandapower Excel), "
                   ".m or .mat (MATPOWER)")
    s.add_argument("--plant-mw", type=float, required=True, help="plant size to screen at each bus")
    s.add_argument("--plant-mva", type=float, metavar="MVA",
                   help="plant nameplate MVA rating (aggregate inverter MVA), for --basis MVA")
    s.add_argument("--inverters", type=float, metavar="N",
                   help="number of inverters; with --inverter-mva gives nameplate MVA = N × inverter MVA")
    s.add_argument("--inverter-mva", type=float, metavar="MVA", help="nameplate MVA of each inverter")
    s.add_argument("--power-factor", type=float, metavar="PF",
                   help="ESTIMATE the MVA as plant MW ÷ PF (e.g. 0.95 required at the POI) when the "
                        "nameplate is not known; nameplate MVA is usually higher (more conservative)")
    s.add_argument("--basis", choices=["MW", "MVA", "mw", "mva"], default="MW",
                   help="rating basis for every ratio (default MW; MVA gives NERC's WSCR-MVA and MVA-based CSCR)")
    s.add_argument("--gen-out", metavar="LIST",
                   help="take the generators at these buses out of service, e.g. 30,32 (minimum-generation case)")
    s.add_argument("--method", choices=["classical", "iec60909"], default="classical",
                   help="short-circuit method (default classical)")
    s.add_argument("--case", choices=["max", "min"], default="max",
                   help="IEC 60909 case (default max; ignored for classical)")
    s.add_argument("--no-compare", action="store_true",
                   help="skip the second method (the report's method comparison chart)")
    s.add_argument("--no-heatmap", action="store_true",
                   help="draw the network map without heat-map shading")
    s.add_argument("--n1", action="store_true",
                   help="also find each bus's worst single outage (N-1) SCR (classical method)")
    s.add_argument("--groups", metavar="CSV",
                   help="screen buses together with WSCR: CSV with columns bus, group, and optional "
                        "mw, mva for a member's own size (e.g. an existing plant, or a STATCOM with mw 0)")
    s.add_argument("--dashboard", metavar="HTML",
                   help="write the scan as a dashboard: the report's content in views behind a sidebar "
                        "(with the classical method this adds --n1 and --emt-triage)")
    s.add_argument("--emt-triage", action="store_true",
                   help="add an EMT study priority for every bus (NERC 2024 situations; implies --n1)")
    s.add_argument("--ibr-threshold", type=float, default=0.5, metavar="X",
                   help="with --emt-triage: an existing IBR or device is nearby when its interaction factor "
                        "with the bus is at least X (default 0.5)")
    s.add_argument("--poi-info", metavar="CSV",
                   help="with --emt-triage: answers (yes/no/unknown) for situations a model cannot show")
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

    tr = sub.add_parser("triage", help="EMT study triage: a system strength data sheet and priority for each POI")
    tr.add_argument("network", help="network file (.json, .xlsx, .m, .mat)")
    tr.add_argument("--buses", required=True, metavar="LIST", help="comma-separated POI bus labels, e.g. 12,16")
    tr.add_argument("--plant-mw", type=float, required=True, help="plant size at each POI")
    tr.add_argument("--plant-mva", type=float, metavar="MVA", help="plant nameplate MVA rating, for --basis MVA")
    tr.add_argument("--inverters", type=float, metavar="N", help="number of inverters (with --inverter-mva)")
    tr.add_argument("--inverter-mva", type=float, metavar="MVA", help="nameplate MVA of each inverter")
    tr.add_argument("--power-factor", type=float, metavar="PF", help="ESTIMATE the MVA as plant MW ÷ PF")
    tr.add_argument("--basis", choices=["MW", "MVA", "mw", "mva"], default="MW", help="rating basis (default MW)")
    tr.add_argument("--groups", metavar="CSV", help="groups of POIs screened together (bus, group, optional mw, mva)")
    tr.add_argument("--gen-out", metavar="LIST",
                    help="add a minimum-generation case with the generators at these buses out, e.g. 38,39")
    tr.add_argument("--ibr-threshold", type=float, default=0.5, metavar="X",
                    help="an existing IBR or device is nearby when its interaction factor with the POI is at "
                         "least X (default 0.5)")
    tr.add_argument("--poi-info", metavar="CSV",
                    help="answers (yes/no/unknown) for situations a model cannot show, and oem_min_scr")
    common(tr)
    tr.set_defaults(func=_cmd_triage, title="SCR-Screen EMT triage")
    return parser


if __name__ == "__main__":
    sys.exit(main())
