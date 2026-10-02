"""Network map: an SVG drawing of the grid with every bus colored by its SCR flag.

Bus positions come from the network's own coordinates (pandapower ``bus.geo``)
when every in-service bus has them; otherwise an automatic layout is computed
from the network topology. The SVG uses the report's color variables, so it
follows light and dark mode, and every bus has a hover tooltip.
"""

from __future__ import annotations

import json
import math
from html import escape

MAX_MAP_BUSES = 400  # above this, a full map becomes unreadable in v0.1
MAX_LABELS = 8  # label and pulse only the weakest flagged buses, to keep the map readable

FLAG_CLASS = {"very weak": "vw", "weak": "wk", "none": "ok"}


def bus_label(net, bus: int) -> str:
    """Display label for a bus: its name if it has one, else its index."""
    name = net.bus.at[bus, "name"] if "name" in net.bus.columns else None
    if name is None or (isinstance(name, float) and math.isnan(name)) or str(name).strip() == "":
        return str(bus)
    return str(name)


def render_network_svg(net, results: dict[int, tuple[float, str]],
                       width: int = 900, height: int = 620,
                       scmva: dict[int, float] | None = None) -> tuple[str | None, str]:
    """Draw the network.

    Args:
        net: pandapower network.
        results: {bus index: (SCR, flag)} for the buses that were screened.
        scmva: optional {bus index: SCMVA}. When given, each bus carries its SCMVA
            so the report's plant-size slider can recolor the map in the browser.

    Returns:
        (svg or None, note). svg is None when the network is too large to map;
        the note explains how positions were obtained (or why there is no map).
    """
    buses = [int(b) for b in net.bus.index[net.bus["in_service"]]]
    if len(buses) > MAX_MAP_BUSES:
        return None, (f"Network map omitted: {len(buses)} buses exceeds the v0.1 map limit "
                      f"of {MAX_MAP_BUSES}. See the results table.")

    edges = _edges(net, set(buses))
    pos, note = _positions(net, buses, edges)

    # Scale positions into the drawing area (higher y is drawn higher up).
    pad_x, pad_top, pad_bottom = 40, 30, 30
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    span_x = (max(xs) - min(xs)) or 1.0
    span_y = (max(ys) - min(ys)) or 1.0
    scale = min((width - 2 * pad_x - 120) / span_x, (height - pad_top - pad_bottom) / span_y)
    off_x = (width - scale * span_x) / 2 - 40
    px = {b: (off_x + (x - min(xs)) * scale,
              pad_top + (max(ys) - y) * scale) for b, (x, y) in pos.items()}

    sources = _source_buses(net)
    scmva = scmva or {}
    out = [f"<svg class='netmap' viewBox='0 0 {width} {height}' role='img' "
           "xmlns='http://www.w3.org/2000/svg'>"
           "<title>Network map: buses colored by SCR flag</title><g class='edges'>"]

    # Staggered entrance animation: about one second in total, whatever the size.
    step_edge = min(18.0, 700.0 / max(len(edges), 1))
    for i, (a, b, kind) in enumerate(edges):
        (x1, y1), (x2, y2) = px[a], px[b]
        dash = " stroke-dasharray='5 4'" if kind == "trafo" else ""
        out.append(f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                   f"class='edge'{dash} style='animation-delay:{i * step_edge:.0f}ms'/>")
    out.append("</g><g class='buses'>")

    flagged = sorted((results[b][0], b) for b in buses
                     if b in results and results[b][1] in ("weak", "very weak"))
    highlight = {b for _, b in flagged[:MAX_LABELS]}
    labels = []
    step_bus = min(25.0, 900.0 / max(len(buses), 1))
    for i, b in enumerate(buses):
        x, y = px[b]
        label = escape(bus_label(net, b))
        src = b in sources
        if b in results:
            value, flag = results[b]
            cls = FLAG_CLASS[flag]
            tip = f"Bus {label}: SCR {value:.2f} ({flag})"
        else:
            value, flag, cls = None, None, "na"
            tip = f"Bus {label}: not screened"
        big = flag in ("weak", "very weak")
        delay = f"animation-delay:{300 + i * step_bus:.0f}ms"
        data = (f" data-bus='{b}' data-x='{x:.1f}' data-y='{y:.1f}' data-label='{label}'"
                f" data-src='{1 if src else 0}'")
        if b in scmva:
            data += f" data-scmva='{scmva[b]:.6g}'"
        halo = (f"<circle cx='{x:.1f}' cy='{y:.1f}' r='9' class='halo {cls}'/>" if b in highlight else "")
        if src:
            s_ = 15 if big else 12
            shape = (f"<rect x='{x - s_ / 2:.1f}' y='{y - s_ / 2:.1f}' width='{s_}' height='{s_}' "
                     f"rx='2' class='node {cls}' style='{delay}'/>")
        else:
            shape = (f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{9 if big else 6}' "
                     f"class='node {cls}' style='{delay}'/>")
        suffix = " · generator/source bus" if src else ""
        out.append(f"<g class='bus'{data}>{halo}{shape}<title>{tip}{suffix}</title></g>")
        if b in highlight:
            labels.append(f"<text x='{x + 12:.1f}' y='{y - 9:.1f}' class='lbl'>Bus {label} · {value:.2f}</text>")

    out.append("</g><g class='labels'>")
    out.extend(labels)  # labels on top of all shapes
    out.append("</g></svg>")
    return "".join(out), note


# ---------------------------------------------------------------------------

def _edges(net, live: set[int]) -> list[tuple[int, int, str]]:
    edges = []
    for _, ln in net.line.iterrows():
        if ln["in_service"] and int(ln["from_bus"]) in live and int(ln["to_bus"]) in live:
            edges.append((int(ln["from_bus"]), int(ln["to_bus"]), "line"))
    for _, tr in net.trafo.iterrows():
        if tr["in_service"] and int(tr["hv_bus"]) in live and int(tr["lv_bus"]) in live:
            edges.append((int(tr["hv_bus"]), int(tr["lv_bus"]), "trafo"))
    return edges


def _source_buses(net) -> set[int]:
    src = set()
    for table in ("gen", "ext_grid"):
        if table in net and len(net[table]) > 0:
            df = net[table]
            src |= {int(b) for b in df.loc[df["in_service"], "bus"]}
    return src


def _positions(net, buses, edges):
    """Use the network's coordinates if every bus has them; else auto-layout."""
    coords = {}
    if "geo" in net.bus.columns:
        for b in buses:
            xy = _parse_geo(net.bus.at[b, "geo"])
            if xy is None:
                coords = {}
                break
            coords[b] = xy
    if coords and len({c for c in coords.values()}) > 1:
        return coords, "Bus positions from the network's own coordinates."

    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(buses)
    g.add_edges_from((a, b) for a, b, _ in edges)
    if len(buses) <= 150:
        layout = nx.kamada_kawai_layout(g)
    else:
        layout = nx.spring_layout(g, seed=1)
    return ({b: (float(p[0]), float(p[1])) for b, p in layout.items()},
            "Bus positions computed automatically from the network topology "
            "(the network has no coordinates); distances are not geographic.")


def _parse_geo(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        data = json.loads(value) if isinstance(value, str) else value
        x, y = data["coordinates"][:2]
        return float(x), float(y)
    except (ValueError, KeyError, TypeError, IndexError):
        return None
