"""Dashboard layout for a bus scan (v0.5.0): the scan report as a one-screen application.

The dashboard is the SAME content as the scan report, arranged in views behind a
sidebar instead of one long page. It is built from the report's own HTML and uses
the report's own script, so every number, flag and live recalculation is exactly
the one in the report: nothing is computed twice.

What the dashboard adds (layout and navigation only):
    * a sidebar with one view per topic, with count badges;
    * a control bar that stays in place (plant size, thresholds);
    * an Overview: the network map beside the weakest locations, and the details
      of the selected bus (including its Thevenin data when available);
    * search, a flagged-only filter and column sorting in the rankings;
    * an "EMT study priority" coloring of the map;
    * Print / PDF (all views, in report order) and Download CSV (the values shown).

Self-contained: one HTML file, no internet access, no libraries.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

# view key -> (sidebar label, section titles that belong to it (prefix match))
VIEWS = [
    ("overview", "Overview", ()),
    ("map", "Network map", ("Network map",)),
    ("rank", "Rankings", ("Results",)),
    ("charts", "Charts", ("SCR by ", "Largest plant")),
    ("groups", "Groups", ("Plants screened together",)),
    ("n1", "N-1 outages", ("Worst single outage",)),
    ("tri", "EMT study triage", ("EMT study triage",)),
    ("cost", "Cost screening", ("Interconnection cost",)),
    ("method", "Method comparison", ("Method comparison",)),
    ("notes", "Method & assumptions", ("Method and assumptions",)),
]

DASH_CSS = """
:root{--page:#eef1f4;--side:#0b3b3d;--side-on:#0f5356;--side-fg:#cfe6e6}
@media (prefers-color-scheme:dark){:root{--page:#0b1220}}
body.dash{background:var(--page)}
.app{display:grid;grid-template-columns:224px minmax(0,1fr);min-height:100vh}
.side{position:sticky;top:0;height:100vh;overflow:auto;background:var(--side);color:var(--side-fg);display:flex;flex-direction:column;padding:18px 0 0}
.brand{padding:0 18px 14px;font-weight:700;font-size:18px;color:#fff}
.brand small{display:block;font-weight:400;font-size:12px;color:#9cc9ca;margin-top:2px}
.nav{display:flex;flex-direction:column}
.nav button{font:inherit;font-size:14px;text-align:left;display:flex;justify-content:space-between;align-items:center;gap:8px;
padding:9px 18px;border:0;border-left:3px solid transparent;background:none;color:var(--side-fg);cursor:pointer}
.nav button:hover{background:rgba(255,255,255,.06)}
.nav button[aria-current=page]{background:var(--side-on);border-left-color:#5fd0d2;color:#fff;font-weight:600}
.nav button:focus-visible,.dbtn:focus-visible,.weak tr:focus-visible{outline:2px solid #5fd0d2;outline-offset:-2px}
.badge{font-size:11px;font-weight:600;border-radius:999px;padding:1px 7px;background:#1c6f72;color:#dff3f3;font-variant-numeric:tabular-nums}
.badge.vw{background:var(--vw);color:#fff}.badge.wk{background:var(--wk);color:#fff}
.badge:empty{display:none}
.side .sfoot{margin-top:auto;padding:14px 18px;font-size:11.5px;color:#9cc9ca;line-height:1.5}
.main{min-width:0;display:flex;flex-direction:column}
.dtop{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.dhead{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:10px 22px}
.dhead header{border:0;padding:0;display:block;min-width:0}
.dhead h1{font-size:18px}.dhead .meta{display:none}
.dbtns{display:flex;gap:8px;flex-wrap:wrap}
.dbtn,.dash .whatif button{font:inherit;font-size:13px;padding:6px 11px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer}
.dash .whatif button#mw-reset{background:var(--accent);border-color:var(--accent);color:#fff}
.dctl{padding:0 22px 8px}
.dctl .slider{margin:0;padding:8px 12px}.dctl .hint{display:none}
.dctl .whatif .wrow{margin:0;gap:8px 14px}.dctl .whatif .wh{width:auto;margin:0}
.dctl .slider{display:flex;gap:6px 26px}
.dctl .slider input[type=range]{min-width:160px;max-width:340px}
.kpis{padding:12px 22px 0}
.kpis .card{padding:10px 14px}.kpis .card .v{font-size:22px}
.costctl .slider{margin:0;padding:0;background:none}.costctl .wrow{margin:0}
.view td:first-child{white-space:nowrap}
.kpis .cards{margin:0;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.kpis .card{background:var(--bg);border:1px solid var(--line)}
.views{padding:14px 22px 26px;flex:1}
.view{display:none}.view.on{display:block}
.panel{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}
.panel>h2:first-child,.view>.panel h2{margin-top:0}
.panel h2{font-size:16px}
.panel+.panel{margin-top:14px}
.ov{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:14px;align-items:start}
.ov.nomap,.v-map .ov{grid-template-columns:minmax(0,1fr)}
.v-map .sidep{display:none}
.v-overview .mapp .legend span:nth-child(n+5){display:none}
.mapp .mapwrap{border:0;padding:0}
.netmap g.bus{cursor:pointer}
.netmap g.bus.sel .node{stroke:var(--fg);stroke-width:3}
#dash-weak{overflow-x:auto}
.weak{margin-top:2px}
.weak th,.weak td{padding:6px 8px;white-space:nowrap}
.weak tbody tr{cursor:pointer}
.weak tbody tr:hover td{background:var(--card)}
.weak tr.sel td{background:var(--card);font-weight:600}
.weak .pill{margin-left:4px}
.det{margin-top:12px;border-top:1px solid var(--line);padding-top:10px;font-size:14px}
.det h3{font-size:15px;margin:0 0 6px}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px 12px;margin:6px 0 8px}
.dgrid span{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.dgrid b{font-variant-numeric:tabular-nums;font-weight:600}
.dgrid b.vw{color:var(--vw)}.dgrid b.wk{color:var(--wk)}.dgrid b.ok{color:var(--ok)}
.det .why{font-size:13px;color:var(--muted)}.det .why b{color:var(--fg)}
.det code{font-size:12px;background:var(--card);border-radius:5px;padding:2px 6px;overflow-wrap:anywhere}
.tools{display:flex;gap:10px 16px;align-items:center;flex-wrap:wrap;margin:0 0 10px;font-size:13px}
.tools input[type=search]{font:inherit;padding:6px 9px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);min-width:200px}
.tools .count{color:var(--muted)}
.view table th.sortable{cursor:pointer;user-select:none}
.view table th.sortable:after{content:' \\2195';opacity:.45}
.view table th.sortable[aria-sort=ascending]:after{content:' \\2191';opacity:1}
.view table th.sortable[aria-sort=descending]:after{content:' \\2193';opacity:1}
tr.res{cursor:pointer}tr.res.sel td{background:var(--card)}
.dfoot{padding:8px 22px;font-size:12px;color:var(--muted);background:var(--bg);border-top:1px solid var(--line)}
.dash .disc{margin-top:16px}
@media (max-width:960px){
.app{display:block}
.side{position:static;height:auto;padding:10px 0 0}
.brand{padding:0 14px 8px}.side .sfoot{display:none}
.nav{flex-direction:row;overflow-x:auto;padding:0 6px}
.nav button{border-left:0;border-bottom:3px solid transparent;white-space:nowrap;padding:8px 10px}
.nav button[aria-current=page]{border-bottom-color:#5fd0d2}
.dtop{position:static}.dhead,.dctl,.kpis,.views{padding-left:14px;padding-right:14px}
.ov{grid-template-columns:minmax(0,1fr)}
.netmap{min-width:0}
}
@media print{
body.dash{background:#fff}.app{display:block}.side,.dbtns,.tools,.dctl{display:none}
.dtop{position:static;border:0}.dhead .meta{display:block}
.view{display:block!important;break-before:auto}.panel{border:0;padding:0;margin-top:18px}
.ov{display:block}.sidep{display:none}.v-overview .mapp .legend span{display:inline}
tr.res.flt-hide{display:table-row!important}
}
"""

DASH_SCRIPT = r"""
(function(){
var q=function(s,r){return (r||document).querySelector(s);};
var qa=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));};
var dataEl=q('#scr-dash'); if(!dataEl) return;
var D=JSON.parse(dataEl.textContent), cfg=JSON.parse(q('#scr-cfg').textContent), U=cfg.unit||'MW';
var body=document.body, sel=null, CLS={'Very weak':'vw','Weak':'wk','No flag':'ok'};
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function txt(e){return e?e.textContent.trim():'';}
function pillOf(cell){var p=cell?q('.pill',cell):null; return p?{t:txt(p),c:(p.className.match(/\b(vw|wk|ok)\b/)||['',''])[1]}:null;}
function fx(v,d){return v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});}

// ---- views -------------------------------------------------------------------
function show(v){
  if(!q('.view[data-v~="'+v+'"]')) v='overview';
  qa('.view').forEach(function(e){e.classList.toggle('on',(' '+e.dataset.v+' ').indexOf(' '+v+' ')>=0);});
  qa('.nav button').forEach(function(b){if(b.dataset.view===v) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current');});
  body.className=body.className.replace(/\bv-\w+\b/g,'').trim()+' v-'+v;
  try{history.replaceState(null,'','#'+v);}catch(e){}
  window.scrollTo(0,0);
}
qa('.nav button').forEach(function(b){b.addEventListener('click',function(){show(b.dataset.view);});});

// ---- rows: the values the report's own script has just written -------------------
function rows(){return qa('tr.res[data-pid]').map(function(t){
  var c=t.cells, scr=parseFloat(txt(q('.c-scr',t))), n1c=q('.c-n1',t), n1=n1c&&q('.val',n1c)?parseFloat(txt(q('.val',n1c))):null;
  var tri=q('.c-tri .pill',t);
  return {t:t,pid:t.dataset.pid,index:txt(c[1]),group:txt(c[2]),scmva:txt(c[3]),rating:txt(q('.c-rating',t)),
    scr:scr,scrT:txt(q('.c-scr',t)),flag:pillOf(c[6]),max:txt(q('.c-max',t)),
    scrif:q('.c-scrif .val',t)?txt(q('.c-scrif .val',t)):'',escr:txt(q('.c-escr',t)),
    n1:n1,n1T:n1c&&q('.val',n1c)?txt(q('.val',n1c)):'',n1flag:pillOf(n1c),outage:n1c?txt(n1c.nextElementSibling):'',
    tri:tri?+txt(tri).slice(-1):null,low:n1===null?scr:Math.min(scr,n1)};});}
function pill(p){return p?"<span class='pill "+p.c+"'>"+esc(p.t)+"</span>":'';}
function triPill(L){return L?"<span class='pill "+['','vw','wk','ok'][L]+"'>P"+L+"</span>":'';}

// ---- overview: weakest locations and bus details ---------------------------------
function weakest(R){
  var el=q('#dash-weak'); if(!el) return;
  var hasN1=R.some(function(r){return r.n1!==null;}), hasTri=R.some(function(r){return r.tri;});
  var top=R.slice().sort(function(a,b){return a.low-b.low;}).slice(0,6);
  if(sel&&!top.some(function(r){return r.pid===sel;})){var s=R.filter(function(r){return r.pid===sel;})[0]; if(s) top[top.length-1]=s;}
  var h="<table class='weak'><thead><tr><th>Bus</th><th class='n'>SCR</th>"+(hasN1?"<th class='n'>N-1 SCR</th>":"")+(hasTri?"<th>EMT</th>":"")+"</tr></thead><tbody>";
  top.forEach(function(r){h+="<tr tabindex='0' data-pid='"+esc(r.pid)+"'"+(r.pid===sel?" class='sel'":"")+"><td>"+esc(r.pid)+"</td><td class='n'>"+fx(r.scr,2)+pill(r.flag)+"</td>"+
    (hasN1?"<td class='n'>"+(r.n1===null?'':fx(r.n1,2)+pill(r.n1flag))+"</td>":"")+(hasTri?"<td>"+triPill(r.tri)+"</td>":"")+"</tr>";});
  el.innerHTML=h+"</tbody></table>";
}
function fact(k,v,c){return "<div><span>"+k+"</span><b"+(c?" class='"+c+"'":"")+">"+v+"</b></div>";}
function detail(R){
  var el=q('#dash-detail'); if(!el) return;
  var r=R.filter(function(x){return x.pid===sel;})[0]; if(!r){el.innerHTML='';return;}
  var b=D.buses[r.pid]||{}, h="<h3>"+esc(r.pid)+(b.kv?" · "+b.kv+" kV":"")+(r.group?" · group "+esc(r.group):"")+"</h3><div class='dgrid'>";
  h+=fact('SCR (intact)',r.scrT,r.flag?r.flag.c:'');
  if(r.n1T) h+=fact('SCR (N-1)',r.n1T,r.n1flag?r.n1flag.c:'');
  h+=fact('Short-circuit MVA',r.scmva);
  if(b.ka!==undefined) h+=fact('Fault current',fx(b.ka,2)+' kA');
  h+=fact('Max size, no flag',r.max+' '+U);
  if(r.scrif) h+=fact('SCRIF',r.scrif);
  if(r.escr) h+=fact('ESCR',r.escr);
  if(r.tri) h+=fact('EMT priority',r.tri,['','vw','wk','ok'][r.tri]);
  h+="</div>";
  if(b.z){h+="<div class='dgrid'>"+fact('Thévenin |Z|',fx(b.z[2],3)+' Ω')+fact('R + jX',fx(b.z[0],3)+' + j'+fx(b.z[1],3)+' Ω')+fact('X/R',b.xr===null?'∞':fx(b.xr,2));
    if(b.zn) h+=fact('|Z| (N-1)',fx(b.zn[2],3)+' Ω')+fact('X/R (N-1)',b.xrn===null?'∞':fx(b.xrn,2));
    h+="</div>";}
  if(r.outage) h+="<div class='why'><b>Worst single outage:</b> "+esc(r.outage)+"</div>";
  var w=q('tr.trirow[data-pid="'+r.pid.replace(/"/g,'\\"')+'"] .c-why');
  if(w) h+="<div class='why'><b>Why this EMT priority:</b> "+esc(txt(w))+"</div>";
  if(D.cmd) h+="<div class='why'><b>Full data sheet:</b> <code>"+esc(D.cmd.replace('{bus}',r.pid.replace(/^Bus /,'')).replace('{size}',String(+q('#mw-num').value||cfg.mw)))+"</code></div>";
  el.innerHTML=h;
}
function select(pid,jump){
  sel=pid;
  qa('.netmap g.bus').forEach(function(g){g.classList.toggle('sel','Bus '+g.dataset.label===pid);});
  qa('tr.res').forEach(function(t){t.classList.toggle('sel',t.dataset.pid===pid);});
  var R=rows(); weakest(R); detail(R);
  if(jump) show('overview');
}
document.addEventListener('click',function(e){
  var g=e.target.closest?e.target.closest('.netmap g.bus'):null;
  if(g){select('Bus '+g.dataset.label,true);return;}
  var w=e.target.closest?e.target.closest('.weak tbody tr'):null;
  if(w){select(w.dataset.pid,false);return;}
  var t=e.target.closest?e.target.closest('tr.res[data-pid]'):null;
  if(t&&!e.target.closest('a,input,button')){select(t.dataset.pid,true);}
});
document.addEventListener('keydown',function(e){if(e.key!=='Enter') return;
  var w=e.target.closest?e.target.closest('.weak tbody tr'):null; if(w) select(w.dataset.pid,false);});

// ---- badges ---------------------------------------------------------------------
function badge(view,n,c){var b=q('.nav button[data-view="'+view+'"] .badge'); if(!b) return; b.textContent=n?String(n):''; b.className='badge'+(c?' '+c:'');}
function badges(R){
  var f=R.filter(function(r){return r.flag&&r.flag.c!=='ok';});
  badge('rank',f.length,f.some(function(r){return r.flag.c==='vw';})?'vw':'wk');
  var gp=qa('.gbox .gline.total .pill'), gf=gp.filter(function(p){return !/\bok\b/.test(p.className);});
  badge('groups',gf.length,gf.some(function(p){return /\bvw\b/.test(p.className);})?'vw':'wk');
  var nv=R.filter(function(r){return r.n1flag&&r.n1flag.c==='vw';}).length, nw=R.filter(function(r){return r.n1flag&&r.n1flag.c==='wk';}).length;
  badge('n1',nv||nw,nv?'vw':'wk');
  var p1=R.filter(function(r){return r.tri===1;}).length, p2=R.filter(function(r){return r.tri===2;}).length;
  badge('tri',p1||p2,p1?'vw':'wk');
  badge('cost',qa('#cost-body .below').length,'wk');
  var cd=q('#cmp-diff'); badge('method',cd?+txt(cd):0,'wk');
}

// ---- map colored by EMT study priority ---------------------------------------------
var mm=q('#map-mode');
if(mm&&q('.c-tri')){var o=document.createElement('option');o.value='tri';o.textContent='EMT study priority';mm.appendChild(o);}
function triMap(R){
  if(!mm||mm.value!=='tri') return;
  var L={}; R.forEach(function(r){L[r.pid]=r;});
  var cls=['na','vw','wk','ok'], byBus={};
  qa('.netmap g.bus').forEach(function(g){var r=L['Bus '+g.dataset.label], c=r&&r.tri?cls[r.tri]:'na';
    byBus[g.dataset.bus]=c; var n=q('.node',g); n.setAttribute('class','node '+c);
    var h=q('.halo',g); if(h) g.removeChild(h);
    q('title',g).textContent='Bus '+g.dataset.label+': EMT study priority '+(r&&r.tri?r.tri:'not rated');});
  qa('.netmap .heat circle').forEach(function(c){c.setAttribute('class','hz '+(byBus[c.dataset.bus]||'ok'));});
  var labels=q('.netmap .labels');
  if(labels){while(labels.firstChild) labels.removeChild(labels.firstChild);
    var p1=R.filter(function(r){return r.tri===1;}).sort(function(a,b){return a.low-b.low;}).slice(0,cfg.maxLabels||8).map(function(r){return r.pid;});
    qa('.netmap g.bus').forEach(function(g){if(p1.indexOf('Bus '+g.dataset.label)<0) return;
      var t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x',(+g.dataset.x+12).toFixed(1));t.setAttribute('y',(+g.dataset.y-9).toFixed(1));
      t.setAttribute('class','lbl');t.textContent='Bus '+g.dataset.label+' · P1';labels.appendChild(t);});}
  var note=q('#map-mode-note'); if(note) note.textContent='Colors show each bus’s EMT study priority: 1 red, 2 amber, 3 green.';
}

// ---- rankings: search, flagged only, sorting ----------------------------------------
var search=q('#dash-search'), only=q('#dash-only'), count=q('#dash-count');
function filter(){
  if(!search) return;
  var s=search.value.trim().toLowerCase(), n=0, all=0;
  qa('tr.res[data-pid]').forEach(function(t){all++;
    var ok=(!s||t.dataset.pid.toLowerCase().indexOf(s)>=0||txt(t.cells[2]).toLowerCase().indexOf(s)>=0);
    if(ok&&only&&only.checked) ok=qa('.pill',t).some(function(p){return !p.closest('.c-tri')&&/\b(vw|wk)\b/.test(p.className);});
    t.style.display=ok?'':'none'; t.classList.toggle('flt-hide',!ok); if(ok) n++;});
  if(count) count.textContent=n===all?all+' buses':n+' of '+all+' buses';
}
if(search) search.addEventListener('input',filter);
if(only) only.addEventListener('change',filter);
var rt=q('tr.res[data-pid]'); rt=rt?rt.closest('table'):null;
if(rt){qa('thead th',rt).forEach(function(th,i){th.classList.add('sortable');th.tabIndex=0;
  var go=function(){var asc=th.getAttribute('aria-sort')!=='ascending';
    qa('thead th',rt).forEach(function(x){x.removeAttribute('aria-sort');});th.setAttribute('aria-sort',asc?'ascending':'descending');
    var tb=rt.tBodies[0], key=function(t){var c=t.cells[i], v=q('.val',c)?txt(q('.val',c)):txt(c).replace(/^(Bus|Priority)\s+/,''), n=parseFloat(v.replace(/,/g,''));
      return (v!==''&&!isNaN(n)&&/^[-\d.,\s]+/.test(v))?n:v.toLowerCase();};
    qa('tr.res',tb).map(function(t){return [key(t),t];}).sort(function(a,b){var x=a[0],y=b[0];
      if(typeof x!==typeof y){x=String(x);y=String(y);} return (x<y?-1:x>y?1:0)*(asc?1:-1);}).forEach(function(p){tb.appendChild(p[1]);});};
  th.addEventListener('click',go);th.addEventListener('keydown',function(e){if(e.key==='Enter') go();});});}

// ---- buttons ---------------------------------------------------------------------------
var pb=q('#dash-print'); if(pb) pb.addEventListener('click',function(){window.print();});
var cb=q('#dash-csv');
if(cb&&rt) cb.addEventListener('click',function(){
  var cell=function(c){var v=q('.val',c)?txt(q('.val',c)):(q('.pill',c)&&c.children.length===1&&!c.firstChild.nodeValue?txt(q('.pill',c)):txt(c));
    v=v.replace(/\s+/g,' '); if(/^[\d,]+(\.\d+)?$/.test(v)) v=v.replace(/,/g,''); return '"'+v.replace(/"/g,'""')+'"';};
  var head=qa('thead th',rt).map(function(th){return '"'+txt(th).replace(/"/g,'""')+'"';}).concat(['"weak_below"','"very_weak_below"','"tool_version"']);
  var wk=q('#in-wk')?q('#in-wk').value:cfg.wk, vw=q('#in-vw')?q('#in-vw').value:cfg.vw;
  var lines=[head.join(',')];
  qa('tr.res',rt).forEach(function(t){lines.push(qa('td',t).map(cell).concat([wk,vw,'"'+D.version+'"']).join(','));});
  var blob=new Blob(['﻿'+lines.join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'}), a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='scr-screen-results.csv'; document.body.appendChild(a); a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},500);});

// ---- refresh after the report's script has recalculated -------------------------------------
function refresh(){var R=rows(); triMap(R); R=rows(); badges(R); weakest(R); detail(R);}
var pend=false; function later(){if(pend) return; pend=true; setTimeout(function(){pend=false;refresh();},0);}
['input','change','click'].forEach(function(ev){document.addEventListener(ev,function(e){
  if(e.target.closest&&e.target.closest('.dtop,.mapctl,#cost-body,.view[data-v~="cost"]')) later();});});
var R0=rows();
if(R0.length){sel=R0.slice().sort(function(a,b){return a.low-b.low;})[0].pid;}
var first=(location.hash||'').slice(1);
show(q('.nav button[data-view="'+first.replace(/[^a-z0-9]/g,'')+'"]')?first:'overview');
select(sel,false); filter(); refresh();
})();
"""


def render_dashboard(report_html: str, data: dict | None = None) -> str:
    """Rearrange a live scan report (report.render_html output) into the dashboard.

    Args:
        report_html: the complete HTML of a bus-scan report with live inputs.
        data: optional {"buses": {plant_id: {...Thevenin data...}}, "cmd": str, "version": str}.
    """
    p = _split(report_html)
    views: dict[str, list[str]] = {k: [] for k, _, _ in VIEWS}
    for title, html in p["sections"]:
        key = next((k for k, _, starts in VIEWS if any(title.startswith(s) for s in starts)), "notes")
        views[key].append(html)

    has_map = bool(views["map"])
    if "<h1>SCR-Screen report</h1>" in p["header"]:  # the default title
        p["header"] = p["header"].replace("<h1>SCR-Screen report</h1>", "<h1>SCR-Screen dashboard</h1>", 1)
        p["head"] = p["head"].replace("<title>SCR-Screen report</title>", "<title>SCR-Screen dashboard</title>", 1)
    out = [p["head"].replace("</style>", DASH_CSS + "</style>", 1).replace("<body>", "<body class='dash v-overview'>", 1)]
    out.append("<div class='app'><aside class='side'><div class='brand'>SCR-Screen<small>System strength dashboard</small></div>"
               "<nav class='nav' aria-label='Views'>")
    for key, label, _ in VIEWS:
        if key == "overview" or views[key]:
            cur = " aria-current='page'" if key == "overview" else ""
            out.append(f"<button type='button' data-view='{key}'{cur}><span>{escape(label)}</span>"
                       "<span class='badge'></span></button>")
    out.append(f"</nav><div class='sfoot'>{p['version']}<br>Screening only. Not a substitute for "
               "interconnection studies.</div></aside><div class='main'>")
    out.append(f"<div class='dtop'><div class='dhead'>{p['header']}<div class='dbtns'>"
               "<button type='button' class='dbtn' id='dash-print'>Print / PDF</button>"
               "<button type='button' class='dbtn' id='dash-csv'>Download CSV</button></div></div>"
               f"<div class='dctl'>{p['whatif']}</div></div>")
    out.append(f"<div class='kpis'>{p['cards']}</div><div class='views'>")

    # Overview (and the full-width map view): the map lives once in the page.
    side = ("<div class='panel sidep'><h2>Weakest locations</h2>"
            "<div class='note' style='margin:-6px 0 6px'>Lowest SCR in any condition shown. Click a bus here or on "
            "the map for its details.</div><div id='dash-weak'></div><div class='det' id='dash-detail'></div></div>")
    if has_map:
        out.append("<section class='view on' data-v='overview map'><div class='ov'><div class='panel mapp'>"
                   + "".join(views["map"]) + "</div>" + side + "</div></section>")
    else:
        out.append("<section class='view on' data-v='overview'><div class='ov nomap'>" + side + "</div></section>")
    tools = ("<div class='tools'><input type='search' id='dash-search' placeholder='Search bus or group' "
             "aria-label='Search bus or group'><label title='Buses with a weak or very weak flag on any SCR shown'><input type='checkbox' id='dash-only'> Flagged only</label>"
             "<span class='count' id='dash-count'></span><span class='count'>Click a column heading to sort; "
             "click a row for the bus details.</span></div>")
    for key, _, _ in VIEWS:
        if key in ("overview", "map") or not views[key]:
            continue
        inner = "".join(f"<div class='panel'>{h}</div>" for h in views[key])
        if key == "rank":
            inner = inner.replace("</h2>", "</h2>" + tools, 1)
        if key == "cost" and p["costctl"]:
            inner = f"<div class='panel costctl'><div class='slider whatif'>{p['costctl']}</div></div>" + inner
        if key == "notes" and p["hint"]:
            inner += f"<div class='panel'><h2>About the live inputs</h2><div class='note'>{p['hint']}</div></div>"
        out.append(f"<section class='view' data-v='{key}'>{inner}</section>")
    out.append("</div>")
    out.append(f"<div class='dfoot'>{p['disc']}</div></div></div>")
    out.append(p["scripts"])
    out.append("<script type='application/json' id='scr-dash'>"
               + json.dumps(data or {"buses": {}}).replace("</", "<\\/") + "</script>")
    out.append(f"<script>{DASH_SCRIPT}</script></body></html>")
    return "".join(out)


def write_dashboard(report_html: str, path: str | Path, data: dict | None = None) -> Path:
    path = Path(path)
    path.write_text(render_dashboard(report_html, data), encoding="utf-8")
    return path


def thevenin_data(kv: float, z: complex, z_n1: complex | None = None) -> dict:
    """Thevenin data of one bus for the details panel (ohms at the bus voltage; classical method)."""
    base = kv ** 2 / 100.0

    def ohm(c):
        return [c.real * base, c.imag * base, abs(c) * base]

    out = {"kv": float(f"{kv:g}"), "z": ohm(z), "xr": (z.imag / z.real) if z.real > 0 else None,
           "ka": (100.0 / abs(z)) / (3 ** 0.5 * kv)}
    if z_n1 is not None:
        out["zn"] = ohm(z_n1)
        out["xrn"] = (z_n1.imag / z_n1.real) if z_n1.real > 0 else None
    return out


def _split(html: str) -> dict:
    """Cut a report into its head, header, cards, inputs, titled sections, disclaimer and scripts."""
    wrap = "<div class='wrap'>"
    cfg = "<script type='application/json' id='scr-cfg'>"
    if wrap not in html or cfg not in html or "<h2>" not in html:
        raise ValueError("The dashboard needs a bus-scan report with live inputs.")
    head, rest = html.split(wrap, 1)
    body, scripts = rest.rsplit(cfg, 1)
    scripts = cfg + scripts
    scripts = scripts[: scripts.rindex("</div></body></html>")]
    first = body.index("<h2>")
    prefix, sections_html = body[:first], body[first:]
    c0, w0 = prefix.index("<div class='cards'>"), prefix.find("<div class='slider whatif'>")
    header = prefix[:c0]
    cards = prefix[c0:w0] if w0 >= 0 else prefix[c0:]
    whatif = prefix[w0:] if w0 >= 0 else ""
    hint, costctl = "", ""
    m = re.search(r"<div class='wrow'><div class='wh'>Cost screening</div>.*?</label></div>", whatif, re.S)
    if m:  # the cost inputs go with the cost view; the report's script finds them by id
        costctl = m.group(0)
        whatif = whatif.replace(costctl, "", 1)
    m = re.search(r"<div class='hint'>(.*?)</div>", whatif, re.S)
    if m:
        hint = m.group(1)
    d0 = sections_html.rindex("<div class='disc'>")
    tail = sections_html[d0:]
    sections_html = sections_html[:d0]
    disc = re.search(r"<div class='disc'>(.*?)</div>", tail, re.S).group(1)
    footer = tail[tail.index("<footer>"):] if "<footer>" in tail else ""
    sections = []
    for chunk in sections_html.split("<h2>")[1:]:
        title = re.sub(r"<[^>]+>", "", chunk.split("</h2>", 1)[0]).strip()
        sections.append((title, "<h2>" + chunk))
    if sections and footer:
        sections[-1] = (sections[-1][0], sections[-1][1] + footer)
    ver = re.search(r"SCR-Screen v[^<]+", header)
    return {"head": head, "header": header, "cards": cards, "whatif": whatif, "hint": hint, "costctl": costctl, "sections": sections,
            "disc": disc, "scripts": scripts, "version": escape(ver.group(0)) if ver else "SCR-Screen"}
