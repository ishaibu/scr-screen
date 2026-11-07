"""Printable EMT triage report: one system strength data sheet per POI, plus CSV and JSON output.

Self-contained HTML (no internet needed). Each POI starts on a new page when printed.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from html import escape
from pathlib import Path

from . import __version__
from .report import CSS, DISCLAIMER
from .triage import NERC_EMT_2024, NERC_NOT_RULE_OUT, NERC_RULE, PRIORITY_NOTE, PRIORITY_RULES, USER_FIELDS, PoiTriage

LEVEL_CLS = {1: "vw", 2: "wk", 3: "ok"}
EXTRA_CSS = """
.sheet{border-top:3px solid var(--accent);margin-top:34px;padding-top:6px}
.sheet h2{margin-top:10px}
.prio{display:inline-block;font-weight:700;border-radius:8px;padding:6px 12px;margin:4px 0 8px}
.prio.vw{color:var(--vw);background:var(--vwbg)}.prio.wk{color:var(--wk);background:var(--wkbg)}.prio.ok{color:var(--ok);background:var(--okbg)}
.facts{display:flex;flex-wrap:wrap;gap:4px 22px;font-size:14px;color:var(--muted)}.facts b{color:var(--fg)}
.trig li{margin:3px 0}.src{font-size:12px;color:var(--muted)}
h3{font-size:15px;margin:20px 0 8px}
@media print{.sheet{break-before:page;border-top:none;margin-top:0}}
"""


def _f(v, d=3, dash="—") -> str:
    return dash if v is None else f"{v:,.{d}f}"


def render_triage_html(items: list[PoiTriage], title: str, source: str, notes: list[str],
                       thresholds: dict, run_utc: str) -> str:
    vw, wk = thresholds["very_weak_below"], thresholds["weak_below"]
    basis = escape(items[0].basis) if items else "MW"
    counts = {k: sum(p.level == k for p in items) for k in (1, 2, 3)}
    p = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{escape(title)}</title><style>{CSS}{EXTRA_CSS}</style></head><body><div class='wrap'>",
         f"<header><div><h1>{escape(title)}</h1><div class='sub'>EMT study triage · {len(items)} POI(s) · "
         f"Rating basis: {basis} · Source: {escape(source)}</div></div>"
         f"<div class='meta'>SCR-Screen v{escape(__version__)}<br>{escape(run_utc)}</div></header>",
         "<div class='cards'>"]
    for k, word in ((1, "Priority 1"), (2, "Priority 2"), (3, "Priority 3")):
        p.append(f"<div class='card'><div class='k'>{word}</div><div class='v {LEVEL_CLS[k]}'>{counts[k]}</div></div>")
    p.append("</div><h2>Summary</h2><div class='tablewrap'><table><thead><tr><th>POI</th><th class='n'>kV</th>"
             f"<th class='n'>Rating ({basis})</th><th class='n'>Lowest SCR</th><th>Condition</th><th>Priority</th>"
             "<th class='n'>Triggers</th></tr></thead><tbody>")
    for it in items:
        low = min(it.conditions, key=lambda c: c.scr)
        p.append(f"<tr><td><a href='#poi-{escape(it.poi_id).replace(' ', '-')}'>{escape(it.poi_id)}</a></td>"
                 f"<td class='n'>{it.kv:g}</td><td class='n'>{it.rating:,.1f}</td><td class='n'>{low.scr:.3f}</td>"
                 f"<td>{escape(_cond(low))}</td><td><span class='pill {LEVEL_CLS[it.level]}'>Priority {it.level}</span></td>"
                 f"<td class='n'>{len(it.triggers)}</td></tr>")
    p.append("</tbody></table></div>")
    p.append(f"<div class='box' style='margin-top:14px'><ul><li>{escape(NERC_RULE)}</li>"
             f"<li>{escape(NERC_NOT_RULE_OUT)}</li><li>{escape(PRIORITY_NOTE)} {escape(PRIORITY_RULES)} "
             f"Thresholds in this report: very weak below {vw:g}, weak below {wk:g}.</li></ul></div>")
    for it in items:
        p.append(_sheet(it, vw, wk))
    p.append("<h2>Method and assumptions</h2><div class='box'><ul>")
    p += [f"<li>{escape(n)}</li>" for n in notes]
    p.append("</ul></div>")
    p.append(f"<div class='disc'><strong>Screening only.</strong> {DISCLAIMER} The EMT triage lists "
             "situations that call for an EMT study; it does not decide whether one is required. The "
             "transmission provider's requirements govern.</div>")
    p.append(f"<footer>Reference: {escape(NERC_EMT_2024)}.</footer></div></body></html>")
    return "".join(p)


def _cond(c) -> str:
    return c.condition + (f" ({c.outage})" if c.outage else "")


def _sheet(it: PoiTriage, vw, wk) -> str:
    cls = LEVEL_CLS[it.level]
    anchor = escape(it.poi_id).replace(" ", "-")
    has_escr = any(c.escr is not None for c in it.conditions)
    p = [f"<section class='sheet' id='poi-{anchor}'><h2>{escape(it.poi_id)}: system strength data sheet</h2>",
         f"<div class='prio {cls}'>{escape(it.level_text)}</div>",
         f"<div class='facts'><span>Nominal voltage <b>{it.kv:g} kV</b></span>"
         f"<span>Plant rating <b>{it.rating:,.1f} {escape(it.basis)}</b></span>"
         + (f"<span>Group <b>{escape(it.group)}</b></span>" if it.group else "")
         + (f"<span>OEM minimum SCR <b>{it.oem_min_scr:g}</b></span>" if it.oem_min_scr is not None else "")
         + "</div>",
         "<h3>System strength by condition</h3><div class='tablewrap'><table><thead><tr><th>Condition</th>"
         "<th>Outage or case</th><th class='n'>SCMVA</th><th class='n'>I<sub>sc</sub> (<span style='text-transform:none'>kA</span>)</th><th class='n'>SCR</th>"
         + ("<th class='n'>ESCR</th>" if has_escr else "") + "</tr></thead><tbody>"]
    for c in it.conditions:
        p.append(f"<tr><td>{escape(c.condition)}</td><td>{escape(c.outage or '')}</td><td class='n'>{c.scmva:,.1f}</td>"
                 f"<td class='n'>{c.isc_ka:.2f}</td><td class='n'>{c.scr:.3f}{_pill(c.scr, vw, wk)}</td>"
                 + (f"<td class='n'>{_f(c.escr)}</td>" if has_escr else "") + "</tr>")
    p.append("</tbody></table></div>")
    p.append("<h3>Thevenin impedance at the POI</h3><div class='tablewrap'><table><thead><tr><th>Condition</th>"
             "<th class='n'>R (pu)</th><th class='n'>X (pu)</th><th class='n'>|Z| (pu)</th><th class='n'>X/R</th>"
             "<th class='n'>R (Ω)</th><th class='n'>X (Ω)</th><th class='n'>|Z| (Ω)</th></tr></thead><tbody>")
    for c in it.conditions:
        xr = "∞ (R = 0)" if c.x_over_r is None else f"{c.x_over_r:.2f}"
        p.append(f"<tr><td>{escape(c.condition)}</td><td class='n'>{c.r_pu:.5f}</td><td class='n'>{c.x_pu:.5f}</td>"
                 f"<td class='n'>{c.z_pu:.5f}</td><td class='n'>{xr}</td><td class='n'>{c.r_ohm:.3f}</td>"
                 f"<td class='n'>{c.x_ohm:.3f}</td><td class='n'>{c.z_ohm:.3f}</td></tr>")
    p.append("</tbody></table></div><div class='note'>Per unit on 100 MVA; ohms = pu × kV² ÷ 100. Classical "
             "flat-start (1.0 pu pre-fault voltage), inverter-based resources excluded.</div>")
    if it.group:
        p.append(f"<h3>Group {escape(it.group)} (network intact)</h3><div class='facts'>"
                 f"<span>WSCR <b>{_f(it.wscr)}</b>{_pill(it.wscr, vw, wk)}</span>"
                 f"<span>CSCR <b>{_f(it.cscr)}</b>{_pill(it.cscr, vw, wk)}</span>"
                 f"<span>SCRIF <b>{_f(it.scrif)}</b>{_pill(it.scrif, vw, wk)}</span></div>")
    p.append("<h3>Why this priority</h3>")
    if it.triggers:
        p.append("<ul class='trig'>")
        for t in sorted(it.triggers, key=lambda t: t.level):
            p.append(f"<li><span class='pill {LEVEL_CLS[t.level]}'>P{t.level}</span> <b>{escape(t.situation)}</b>: "
                     f"{escape(t.detail)} <span class='src'>[{escape(t.source)}]</span></li>")
        p.append("</ul>")
    else:
        p.append(f"<p>No screening trigger was found. {escape(NERC_NOT_RULE_OUT)}</p>")
    unk = it.unknown
    if unk:
        p.append("<h3>Not checked: confirm with the transmission provider</h3><div class='note'>A network model "
                 "cannot show these. Answer them in a --poi-info file (yes / no / unknown):</div><ul>"
                 + "".join(f"<li>{escape(u)}</li>" for u in unk) + "</ul>")
    answered_no = [USER_FIELDS[k][0] for k, v in it.answers.items() if v == "no"]
    if answered_no:
        p.append("<div class='note'>Answered no: " + escape("; ".join(answered_no)) + ".</div>")
    p.append(_nearby_table("Existing IBRs and their interaction with this POI", it.nearby_ibrs, ibr=True))
    p.append(_nearby_table("Series compensation, FACTS and HVdc in the model", it.devices, ibr=False))
    p.append("</section>")
    return "".join(p)


def _nearby_table(title, rows, ibr) -> str:
    if not rows:
        return (f"<h3>{escape(title)}</h3><div class='note'>None in service in the model.</div>")
    head = ("<th>Name</th><th>Bus</th><th class='n'>MW</th><th class='n'>MVA</th>" if ibr
            else "<th>Kind</th><th>Device</th><th>Bus(es)</th>")
    out = [f"<h3>{escape(title)}</h3><div class='tablewrap'><table><thead><tr>{head}"
           "<th class='n'>Interaction</th><th>Nearby?</th></tr></thead><tbody>"]
    for n in rows[:30]:
        cells = (f"<td>{escape(n.name)}</td><td>{escape(n.where)}</td><td class='n'>{_f(n.p_mw, 1)}</td>"
                 f"<td class='n'>{_f(n.sn_mva, 1)}</td>" if ibr else
                 f"<td>{escape(n.kind)}</td><td>{escape(n.name)}</td><td>{escape(n.where)}</td>")
        out.append(f"<tr>{cells}<td class='n'>{_f(n.interaction, 2)}</td><td>{'yes' if n.near else 'no'}</td></tr>")
    out.append("</tbody></table></div>")
    if len(rows) > 30:
        out.append(f"<div class='note'>{len(rows) - 30} more not shown (weaker interaction).</div>")
    return "".join(out)


def _pill(v, vw, wk) -> str:
    if v is None:
        return ""
    c, t = ("vw", "Very weak") if v < vw else (("wk", "Weak") if v < wk else ("ok", "No flag"))
    return f"<span class='pill {c}'>{t}</span>"


def write_triage_html(items, path, **kw) -> Path:
    path = Path(path)
    path.write_text(render_triage_html(items, **kw), encoding="utf-8")
    return path


CSV_COLS = ["poi", "priority", "priority_text", "condition", "outage_or_case", "kv", "rating", "basis",
            "scmva", "isc_ka", "scr", "escr", "r_pu", "x_pu", "z_pu", "x_over_r", "r_ohm", "x_ohm", "z_ohm",
            "group", "wscr", "cscr", "scrif", "nearby_ibrs", "nearby_devices", "triggers", "not_checked",
            "tool_version"]


def write_triage_csv(items: list[PoiTriage], path) -> Path:
    """One row per POI and condition."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for it in items:
            for c in it.conditions:
                w.writerow([it.poi_id, it.level, it.level_text, c.condition, c.outage, f"{c.kv:g}",
                            f"{it.rating:.2f}", it.basis, f"{c.scmva:.2f}", f"{c.isc_ka:.3f}", f"{c.scr:.3f}",
                            _e(c.escr, 3), f"{c.r_pu:.6f}", f"{c.x_pu:.6f}", f"{c.z_pu:.6f}", _e(c.x_over_r, 3),
                            f"{c.r_ohm:.4f}", f"{c.x_ohm:.4f}", f"{c.z_ohm:.4f}", it.group or "",
                            _e(it.wscr, 3), _e(it.cscr, 3), _e(it.scrif, 3),
                            "; ".join(f"{n.name} ({n.interaction:.2f})" for n in it.nearby_ibrs if n.near),
                            "; ".join(f"{n.name} ({n.interaction:.2f})" for n in it.devices if n.near),
                            " | ".join(f"P{t.level} {t.situation}: {t.detail}" for t in it.triggers),
                            "; ".join(it.unknown), __version__])
    return path


def _e(v, d) -> str:
    return "" if v is None else f"{v:.{d}f}"


def write_triage_json(items: list[PoiTriage], path, meta: dict) -> Path:
    path = Path(path)
    data = {**meta, "tool_version": __version__, "reference": NERC_EMT_2024, "priority_note": PRIORITY_NOTE,
            "pois": [{**asdict(it), "priority_text": it.level_text, "not_checked": it.unknown} for it in items]}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
