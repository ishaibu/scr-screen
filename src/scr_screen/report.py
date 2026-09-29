"""Self-contained HTML screening report.

One HTML file, no internet needed: all styling and charts are built in, so the
report can be emailed, archived, or printed to PDF from any browser.
Every colored element also shows its number and flag text, so the report
reads correctly in black and white and for color-blind readers.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .screening import ScreeningResult

FLAG_STYLE = {
    "very weak": ("vw", "Very weak"),
    "weak": ("wk", "Weak"),
    "none": ("ok", "No flag"),
}

DISCLAIMER = (
    "SCR-Screen provides screening-level indicators of system strength. Results do "
    "not replace interconnection studies, detailed positive-sequence or EMT analysis, "
    "or the requirements of the applicable transmission provider. Thresholds are "
    "user-configurable and have no universal validity. SCR-based metrics assume "
    "grid-following inverters and do not replace the inverter manufacturer's "
    "minimum SCR rating."
)

CSS = """
:root{--bg:#fff;--fg:#1d2939;--muted:#667085;--line:#e4e7ec;--card:#f8f9fb;
--vw:#d92d20;--wk:#dc6803;--ok:#079455;--vwbg:#fef3f2;--wkbg:#fffaeb;--okbg:#ecfdf3;--accent:#0a9396}
@media (prefers-color-scheme:dark){:root{--bg:#101828;--fg:#f2f4f7;--muted:#98a2b3;--line:#344054;
--card:#1d2939;--vwbg:#3b1512;--wkbg:#3a2508;--okbg:#0b3321}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 24px 48px}
header{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;border-bottom:3px solid var(--accent);padding-bottom:14px}
h1{font-size:24px;margin:0}h2{font-size:17px;margin:32px 0 12px}
.sub,.meta{color:var(--muted);font-size:13px}.meta{text-align:right}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:20px}
.card{background:var(--card);border-radius:10px;padding:14px 16px}
.card .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:26px;font-weight:600}
.v.vw{color:var(--vw)}.v.wk{color:var(--wk)}.v.ok{color:var(--ok)}
.chart{position:relative;margin-top:6px}
.row{display:grid;grid-template-columns:150px 1fr 120px;gap:10px;align-items:center;margin:6px 0;font-size:14px}
.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.track{position:relative;height:22px;background:var(--card);border-radius:5px}
.bar{height:100%;border-radius:5px}
.bar.vw{background:var(--vw)}.bar.wk{background:var(--wk)}.bar.ok{background:var(--ok)}
.tick{position:absolute;top:-4px;bottom:-4px;border-left:2px dashed var(--muted)}
.tick span{position:absolute;top:-18px;left:-10px;font-size:11px;color:var(--muted)}
.val{font-variant-numeric:tabular-nums}
.pill{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:1px 9px;margin-left:6px}
.pill.vw{color:var(--vw);background:var(--vwbg)}.pill.wk{color:var(--wk);background:var(--wkbg)}.pill.ok{color:var(--ok);background:var(--okbg)}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-top:10px}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.gbox{border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.gbox h3{font-size:15px;margin:0 0 8px}
.gline{display:flex;justify-content:space-between;font-size:14px;padding:3px 0}
.gline.total{border-top:1px solid var(--line);margin-top:6px;padding-top:8px;font-weight:600}
.note{font-size:13px;color:var(--muted);margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.tablewrap{overflow-x:auto}
.box{background:var(--card);border-radius:10px;padding:14px 18px;font-size:14px}
.box ul{margin:6px 0 0;padding-left:20px}
.disc{border-left:4px solid var(--wk);background:var(--wkbg);padding:12px 16px;border-radius:6px;font-size:13px;margin-top:24px}
footer{margin-top:28px;color:var(--muted);font-size:12px}
@media print{body{font-size:12px}.wrap{padding:0}h2{break-after:avoid}.gbox,.card,.row,tr{break-inside:avoid}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
@media (max-width:640px){.row{grid-template-columns:90px 1fr 96px}}
"""


def render_html(result: ScreeningResult, title: str = "SCR-Screen report",
                notes: list[str] | None = None) -> str:
    """Return the full HTML report as a string."""
    t = result.thresholds
    vw, wk = t["very_weak_below"], t["weak_below"]
    plants = sorted(result.plants, key=lambda p: p.scr, reverse=True)
    flagged = sum(p.flag != "none" for p in result.plants) + sum(g.flag != "none" for g in result.groups)
    lowest = min(result.plants, key=lambda p: p.scr) if result.plants else None
    basis = escape(result.basis)

    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body><div class='wrap'>",
        "<header><div>",
        f"<h1>{escape(title)}</h1>",
        f"<div class='sub'>{len(result.plants)} plant(s) · {len(result.groups)} group(s) · "
        f"Rating basis: {basis} · Source: {escape(result.source)}</div>",
        "</div><div class='meta'>",
        f"SCR-Screen v{escape(result.tool_version)}<br>{escape(result.run_utc)}",
        "</div></header>",
    ]

    # --- Summary cards -------------------------------------------------------
    parts.append("<div class='cards'>")
    parts.append(_card("Plants screened", str(len(result.plants))))
    if lowest:
        parts.append(_card("Lowest SCR", f"{lowest.scr:.2f}", FLAG_STYLE[lowest.flag][0],
                           escape(lowest.plant_id)))
    if result.groups:
        g_low = min(result.groups, key=lambda g: g.wscr)
        parts.append(_card("Lowest group WSCR", f"{g_low.wscr:.2f}", FLAG_STYLE[g_low.flag][0],
                           escape(g_low.group)))
    total = len(result.plants) + len(result.groups)
    parts.append(_card("Flagged", f"{flagged} of {total}", "wk" if flagged else "ok"))
    parts.append("</div>")

    # --- SCR bar chart -------------------------------------------------------
    parts.append("<h2>SCR by plant</h2><div class='chart'>")
    scale = max([p.scr for p in plants] + [wk * 1.5])
    for i, p in enumerate(plants):
        cls, label = FLAG_STYLE[p.flag]
        width = max(p.scr / scale * 100, 0.8)
        ticks = ""
        if i == 0:
            ticks = (f"<div class='tick' style='left:{vw / scale * 100:.2f}%'><span>{vw:g}</span></div>"
                     f"<div class='tick' style='left:{wk / scale * 100:.2f}%'><span>{wk:g}</span></div>")
        else:
            ticks = (f"<div class='tick' style='left:{vw / scale * 100:.2f}%'></div>"
                     f"<div class='tick' style='left:{wk / scale * 100:.2f}%'></div>")
        parts.append(
            f"<div class='row'><div class='name' title='{escape(p.plant_id)}'>{escape(p.plant_id)}</div>"
            f"<div class='track'><div class='bar {cls}' style='width:{width:.2f}%'></div>{ticks}</div>"
            f"<div><span class='val'>{p.scr:.2f}</span><span class='pill {cls}'>{label}</span></div></div>"
        )
    parts.append("</div>")
    parts.append(
        "<div class='legend'>"
        f"<span><span class='sw' style='background:var(--vw)'></span>Very weak: below {vw:g}</span>"
        f"<span><span class='sw' style='background:var(--wk)'></span>Weak: {vw:g} to below {wk:g}</span>"
        f"<span><span class='sw' style='background:var(--ok)'></span>No flag: {wk:g} or above</span>"
        "<span>Dashed lines mark the thresholds</span></div>"
    )

    # --- Groups: individual SCR vs WSCR -------------------------------------
    if result.groups:
        by_id = {p.plant_id: p for p in result.plants}
        parts.append("<h2>Plants screened together (WSCR)</h2><div class='groups'>")
        for g in result.groups:
            cls, label = FLAG_STYLE[g.flag]
            parts.append(f"<div class='gbox'><h3>Group {escape(g.group)}</h3>")
            for pid in g.plant_ids:
                p = by_id[pid]
                pc, pl = FLAG_STYLE[p.flag]
                parts.append(f"<div class='gline'><span>{escape(pid)} alone</span>"
                             f"<span><span class='val'>{p.scr:.2f}</span>"
                             f"<span class='pill {pc}'>{pl}</span></span></div>")
            parts.append(f"<div class='gline total'><span>Together (WSCR)</span>"
                         f"<span><span class='val'>{g.wscr:.2f}</span>"
                         f"<span class='pill {cls}'>{label}</span></span></div>")
            if g.wscr < g.min_individual_scr:
                drop = 100 * (1 - g.wscr / g.min_individual_scr)
                parts.append(f"<div class='note'>Screened together, strength is {drop:.0f}% lower "
                             "than the weakest plant alone.</div>")
            parts.append("</div>")
        parts.append("</div>")

    # --- Results tables -----------------------------------------------------
    parts.append("<h2>Results</h2><div class='tablewrap'><table><thead><tr>"
                 f"<th>Plant</th><th>POI</th><th>Group</th><th>SCMVA</th><th>Rating ({basis})</th>"
                 "<th>SCR</th><th>Flag</th></tr></thead><tbody>")
    for p in plants:
        cls, label = FLAG_STYLE[p.flag]
        parts.append(f"<tr><td>{escape(p.plant_id)}</td><td>{escape(p.poi_name)}</td>"
                     f"<td>{escape(p.group or '')}</td><td class='n'>{p.scmva:,.1f}</td>"
                     f"<td class='n'>{p.rating:,.1f}</td><td class='n'>{p.scr:.3f}</td>"
                     f"<td><span class='pill {cls}'>{label}</span></td></tr>")
    parts.append("</tbody></table></div>")
    if result.groups:
        parts.append("<div class='tablewrap' style='margin-top:14px'><table><thead><tr>"
                     f"<th>Group</th><th>Plants</th><th>Total rating ({basis})</th><th>WSCR</th>"
                     "<th>Flag</th></tr></thead><tbody>")
        for g in result.groups:
            cls, label = FLAG_STYLE[g.flag]
            parts.append(f"<tr><td>{escape(g.group)}</td><td>{escape(', '.join(g.plant_ids))}</td>"
                         f"<td class='n'>{g.total_rating:,.1f}</td><td class='n'>{g.wscr:.3f}</td>"
                         f"<td><span class='pill {cls}'>{label}</span></td></tr>")
        parts.append("</tbody></table></div>")

    # --- Method and assumptions ---------------------------------------------
    items = [
        f"Short-circuit MVA source: {escape(result.source)}. SCMVA excludes the "
        "contribution of inverter-based resources, per NERC.",
        f"SCR = SCMVA ÷ plant rating ({basis}). WSCR = Σ(SCMVAᵢ × Pᵢ) ÷ (ΣPᵢ)², assuming the "
        "plants in a group are fully interacting.",
        f"Flag bands: below {vw:g} very weak; {vw:g} to below {wk:g} weak; {wk:g} or above no "
        "flag. Default bands follow HVDC planning practice (IEEE Std 1204-1997); user-configurable.",
    ] + [escape(n) for n in (notes or [])]
    parts.append("<h2>Method and assumptions</h2><div class='box'><ul>")
    parts.extend(f"<li>{i}</li>" for i in items)
    parts.append("</ul></div>")
    parts.append(f"<div class='disc'><strong>Screening only.</strong> {DISCLAIMER}</div>")
    parts.append("<footer>References: NERC Reliability Guideline, Integrating Inverter-Based "
                 "Resources into Low Short Circuit Strength Systems (2017); NERC White Paper, "
                 "Short-Circuit Modeling and System Strength (2018).</footer>")
    parts.append("</div></body></html>")
    return "".join(parts)


def write_html_report(result: ScreeningResult, path: str | Path,
                      title: str = "SCR-Screen report", notes: list[str] | None = None) -> Path:
    """Write the HTML report to a file and return its path."""
    path = Path(path)
    path.write_text(render_html(result, title=title, notes=notes), encoding="utf-8")
    return path


def _card(key: str, value: str, cls: str = "", sub: str = "") -> str:
    sub_html = f"<div class='sub'>{sub}</div>" if sub else ""
    return f"<div class='card'><div class='k'>{key}</div><div class='v {cls}'>{value}</div>{sub_html}</div>"
