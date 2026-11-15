"""Dashboard layout for a bus scan (v0.5.0; v0.6.0 layout): the scan report as a one-screen application.

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
@media (prefers-color-scheme:dark){:root{--page:#0b1220;--side:#06282a;--side-on:#0c4447}}
body.dash{background:var(--page)}
.app{display:grid;grid-template-columns:224px minmax(0,1fr);min-height:100vh}
.side{position:sticky;top:0;height:100vh;overflow:auto;background:var(--side);color:var(--side-fg);display:flex;flex-direction:column;padding:18px 0 0;z-index:6}
.brand{padding:0 18px 14px;font-weight:700;font-size:18px;color:#fff}
.brand small{display:block;font-weight:400;font-size:12px;color:#9cc9ca;margin-top:2px}
.navrow{position:relative}
.nav{display:flex;flex-direction:column}
.nav button{font:inherit;font-size:14px;text-align:left;display:flex;justify-content:space-between;align-items:center;gap:8px;
padding:9px 18px;border:0;border-left:3px solid transparent;background:none;color:var(--side-fg);cursor:pointer}
.nav button:hover{background:rgba(255,255,255,.06)}
.nav button[aria-current=page]{background:var(--side-on);border-left-color:#5fd0d2;color:#fff;font-weight:600}
.nav button:focus-visible,.dbtn:focus-visible,.weak tr:focus-visible,.allbtn:focus-visible,.sheet button:focus-visible,
.ctlsum:focus-visible,.zbtn:focus-visible{outline:2px solid #5fd0d2;outline-offset:-2px}
.badge{font-size:11px;font-weight:600;border-radius:999px;padding:1px 7px;background:#1c6f72;color:#dff3f3;font-variant-numeric:tabular-nums}
.badge.vw{background:var(--vw);color:#fff}.badge.wk{background:var(--wk);color:#fff}
.badge:empty{display:none}
.allbtn{display:none}
.side .sfoot{margin-top:auto;padding:14px 18px;font-size:11.5px;color:#9cc9ca;line-height:1.5}
.main{min-width:0;display:flex;flex-direction:column}
.dtop{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.dhead{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:10px 22px}
.dhead header{border:0;padding:0;display:block;min-width:0}
.dhead h1{font-size:18px}.dhead .meta{display:none}
.dbtns{display:flex;gap:8px;flex-wrap:wrap}
.dbtn,.dash .whatif button{font:inherit;font-size:13px;padding:6px 11px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer}
.dash .whatif button#mw-reset{background:var(--accent);border-color:var(--accent);color:#fff}
.ctlsum{display:none}
.dctl{padding:0 22px 8px}
.dctl .slider{margin:0;padding:8px 12px}.dctl .hint{display:none}
.dctl .whatif .wrow{margin:0;gap:8px 14px}.dctl .whatif .wh{width:auto;margin:0}
.dctl .slider{display:flex;gap:6px 26px}
.dctl .slider input[type=range]{min-width:160px;max-width:340px}
.kpis{padding:12px 22px 0}
.kpis .cards{margin:0;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.kpis .card{background:var(--bg);border:1px solid var(--line);padding:10px 14px}.kpis .card .v{font-size:22px}
body:not(.v-overview) .kpis .card{padding:6px 12px;animation:none}
body:not(.v-overview) .kpis .card .v{font-size:17px}
body:not(.v-overview) .kpis .card .k{font-size:10.5px}
body:not(.v-overview) .kpis .card .sub{display:none}
.costctl .slider{margin:0;padding:0;background:none}.costctl .wrow{margin:0}
.view td:first-child{white-space:nowrap}
.views{padding:14px 22px 26px;flex:1}
.view{display:none}.view.on{display:block}
.panel{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}
.panel>h2:first-child,.view>.panel h2{margin-top:0}
.panel h2{font-size:16px}
.panel+.panel{margin-top:14px}
.legacy{display:none!important}
.ov>.panel+.panel{margin-top:0}
/* overview and network map */
.ov{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:14px;align-items:start}
.ov.nomap{grid-template-columns:minmax(0,1fr)}
.v-map .ov{grid-template-columns:minmax(0,3fr) minmax(260px,1fr)}
.v-map .weakbox{display:none}
.dash .groups{grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),640px))}
.weakbox h2{margin-top:0}
.v-map .det{margin-top:0;border-top:0;padding-top:0}
.v-overview .mapp .legend span:nth-child(n+5){display:none}
.mapp .mapwrap{position:relative;border:0;padding:0;overflow:hidden;height:var(--maph,auto);border-radius:8px;background:var(--card)}
.dash .netmap{min-width:0;width:100%;height:100%;touch-action:pan-y;user-select:none;-webkit-user-select:none}
.v-map .dash .netmap,.v-map .netmap{touch-action:none}
.dash .netmap.grab{cursor:grabbing}
.dash .netmap .lbl{font-size:var(--lfs,12px);stroke-width:var(--lsw,3px)}
.netmap g.bus{cursor:pointer}
.netmap g.bus.sel .node{stroke:var(--fg);stroke-width:3}
.mapzoom{position:absolute;right:8px;top:8px;display:flex;flex-direction:column;gap:4px;z-index:2}
.zbtn{font:inherit;font-size:16px;line-height:1;width:32px;height:32px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.12)}
.zbtn.fit{font-size:11px;font-weight:600}
.zhint{position:absolute;left:10px;bottom:8px;font-size:11.5px;color:var(--muted);background:var(--bg);border-radius:5px;padding:1px 6px;opacity:.9}
#dash-weak{overflow-x:auto}
.weak{margin-top:2px}
.weak th,.weak td{padding:6px 8px;white-space:nowrap}
.weak tbody tr{cursor:pointer}
.weak tbody tr:hover td{background:var(--card)}
.weak tr.sel td{background:var(--card);font-weight:600}
.weak .pill{margin-left:4px}
.det{margin-top:12px;border-top:1px solid var(--line);padding-top:10px;font-size:14px}
.det h3{font-size:15px;margin:0 0 6px}
.det .empty{color:var(--muted);font-size:13px}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px 12px;margin:6px 0 8px}
.dgrid span{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.dgrid b{font-variant-numeric:tabular-nums;font-weight:600}
.dgrid b.vw{color:var(--vw)}.dgrid b.wk{color:var(--wk)}.dgrid b.ok{color:var(--ok)}
.det .why{font-size:13px;color:var(--muted)}.det .why b{color:var(--fg)}
.det code{font-size:12px;background:var(--card);border-radius:5px;padding:2px 6px;overflow-wrap:anywhere}
/* merged chart */
.mc-tools{display:flex;gap:8px 18px;flex-wrap:wrap;align-items:center;font-size:13px;margin:-2px 0 10px}
.mc-tools select{font:inherit;padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.mc-legend{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin:0 0 8px}
.mc-legend i{display:inline-block;vertical-align:-1px;margin-right:5px}
.mc-legend .lb{width:18px;height:9px;border-radius:3px;background:var(--ok)}
.mc-legend .ld{width:9px;height:9px;transform:rotate(45deg);border:2px solid var(--fg);background:var(--bg)}
.mc-legend .lt{width:0;height:12px;border-left:2px dashed var(--muted)}
.mchart{display:grid;grid-template-columns:minmax(64px,auto) minmax(120px,1fr) auto auto auto;gap:6px 10px;align-items:center;font-size:13.5px}
.mchart .hd{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.mchart .hd.n,.mchart .n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.mchart .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mtrack{position:relative;height:16px;background:var(--card);border-radius:5px}
.mbar{position:absolute;left:0;top:0;bottom:0;border-radius:5px;transition:width .4s ease}
.mbar.vw{background:var(--vw)}.mbar.wk{background:var(--wk)}.mbar.ok{background:var(--ok)}
.mdia{position:absolute;top:50%;width:10px;height:10px;margin:-5px 0 0 -5px;transform:rotate(45deg);border:2px solid var(--fg);background:var(--bg);transition:left .4s ease}
.mdia.vw{border-color:var(--vw)}.mdia.wk{border-color:var(--wk)}.mdia.ok{border-color:var(--ok)}
.mtick{position:absolute;top:-4px;bottom:-4px;border-left:2px dashed var(--muted);opacity:.85;z-index:1}
.mtick.vw{border-left-color:var(--vw)}.mtick.wk{border-left-color:var(--wk)}
.maxis{position:relative;height:38px}
.maxis .at{position:absolute;bottom:0;transform:translateX(-50%);font-size:12px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1;text-align:center;white-space:nowrap}
.maxis .at:after{content:'';display:block;margin:2px auto 0;width:0;height:5px;border-left:2px dashed currentColor}
.maxis .at.vw{color:var(--vw)}.maxis .at.wk{color:var(--wk)}
.maxis .cap{position:absolute;left:0;top:0;line-height:1.2;white-space:nowrap;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.mc-legend .lt.vw{border-left-color:var(--vw)}.mc-legend .lt.wk{border-left-color:var(--wk)}
.mchart .pill{margin-left:4px}
.mc-more{margin-top:10px}
/* rankings tools */
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
/* bottom sheet with every view (phones and tablets) */
.dim{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:20}
.sheet{position:fixed;left:0;right:0;bottom:0;z-index:21;background:var(--bg);color:var(--fg);border-radius:16px 16px 0 0;
box-shadow:0 -8px 28px rgba(0,0,0,.25);padding:8px 14px calc(14px + env(safe-area-inset-bottom));max-height:85vh;overflow:auto}
.sheet .grip{width:40px;height:4px;background:var(--line);border-radius:3px;margin:4px auto 8px}
.sheet h2{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:4px 4px 6px}
.sheet button{font:inherit;font-size:15px;width:100%;display:flex;justify-content:space-between;align-items:center;gap:10px;
padding:11px 6px;border:0;border-bottom:1px solid var(--line);background:none;color:var(--fg);cursor:pointer;text-align:left}
.sheet button[aria-current=page]{color:var(--accent);font-weight:700}
.sheet .acts{display:flex;gap:8px;margin-top:12px}
.sheet .acts button{justify-content:center;border:1px solid var(--line);border-radius:8px;font-size:14px;padding:9px}
.dim[hidden],.sheet[hidden]{display:none}
/* desktop: tables keep their headings in view */
@media (min-width:961px){
.view .tablewrap{max-height:calc(var(--avail,100vh) - 40px);overflow:auto}
.view .gbox .tablewrap{max-height:none}
.view .tablewrap thead th{position:sticky;top:0;z-index:1;background:var(--bg);box-shadow:inset 0 -1px 0 var(--line)}
}
/* tablets and phones: views in a row along the top, plus "All" */
@media (max-width:960px){
.app{display:block}
.side{position:sticky;top:0;height:auto;padding:8px 0 0;overflow:visible}
.brand{padding:0 14px 4px;font-size:16px}.side .sfoot{display:none}
.nav{flex-direction:row;overflow-x:auto;padding:0 112px 0 6px;scrollbar-width:none;scroll-behavior:smooth}
.nav::-webkit-scrollbar{display:none}
.nav button{border-left:0;border-bottom:3px solid transparent;white-space:nowrap;padding:8px 10px;flex:none}
.nav button[aria-current=page]{border-bottom-color:#5fd0d2;background:none}
.allbtn{display:flex;align-items:center;position:absolute;right:0;top:0;bottom:3px;padding:0 10px 0 40px;border:0;cursor:pointer;
background:linear-gradient(90deg,rgba(11,59,61,0),var(--side) 42%);font:inherit;color:#fff}
.allbtn span{border:1px solid #5fd0d2;border-radius:999px;padding:4px 11px;background:var(--side-on);font-size:13px;white-space:nowrap}
.dtop{position:static}.dhead,.dctl,.kpis,.views{padding-left:14px;padding-right:14px}
.ov,.v-map .ov{grid-template-columns:minmax(0,1fr)}
}
/* phones: compact top */
@media (max-width:640px){
.dhead{padding-top:10px;padding-bottom:6px}
.dhead h1{font-size:16px;line-height:1.3}
.dhead .sub{font-size:12px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.dbtns{display:none}
.ctlsum{display:flex;justify-content:space-between;align-items:center;gap:8px;width:calc(100% - 28px);margin:0 14px 10px;
font:inherit;font-size:14px;text-align:left;padding:9px 12px;border:0;border-radius:10px;background:var(--card);color:var(--fg);cursor:pointer}
.ctlsum b{font-weight:600}.ctlsum .ed{color:var(--accent);font-weight:600;white-space:nowrap}
.dctl{display:none}.dctl.open{display:block}
.dctl .slider{flex-direction:column;align-items:stretch}
.dctl .slider input[type=range]{max-width:none;min-width:0}
.dctl .whatif .wrow{flex-wrap:wrap}
.kpis{padding:10px 0 0 14px}
.kpis .cards{display:flex;gap:8px;overflow-x:auto;scroll-snap-type:x mandatory;padding:0 14px 4px 0;scrollbar-width:none}
.kpis .cards::-webkit-scrollbar{display:none}
.kpis .card,body:not(.v-overview) .kpis .card{flex:0 0 auto;min-width:118px;scroll-snap-align:start;padding:7px 10px}
.kpis .card .v,body:not(.v-overview) .kpis .card .v{font-size:19px}
.kpis .card .k{font-size:10px}.kpis .card .sub{font-size:11.5px}
.views{padding-top:10px}
.panel{padding:12px}
.mchart{grid-template-columns:minmax(52px,auto) minmax(70px,1fr) auto auto;gap:6px 8px;font-size:12.5px}
.mchart .mx{display:none}
.g-size{width:66px}
.mc-legend span:nth-child(5){display:none}
.mchart .pill{display:none}
.zhint{display:none}
}
@media print{
body.dash{background:#fff}.app{display:block}.side,.dbtns,.tools,.dctl,.ctlsum,.mapzoom,.zhint,.mc-tools,.mc-more,.sheet,.dim{display:none!important}
.dtop{position:static;border:0}.dhead .meta{display:block}
.view{display:block!important;break-before:auto}.panel{border:0;padding:0;margin-top:18px}
.ov{display:block}.sidep{display:none}.v-overview .mapp .legend span{display:inline}
.mapp .mapwrap{height:auto!important}.dash .netmap{height:auto}
.view .tablewrap{max-height:none!important;overflow:visible!important}
tr.res.flt-hide{display:table-row!important}
}
"""

DASH_SCRIPT = r"""
(function(){
var q=function(s,r){return (r||document).querySelector(s);};
var qa=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));};
var dataEl=q('#scr-dash'); if(!dataEl) return;
var D=JSON.parse(dataEl.textContent), cfg=JSON.parse(q('#scr-cfg').textContent), U=cfg.unit||'MW';
var body=document.body, root=document.documentElement, sel=null, view='overview';
var TC=['','vw','wk','ok'], NAME={vw:'Very weak',wk:'Weak',ok:'No flag'};
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function txt(e){return e?e.textContent.trim():'';}
function pillOf(cell){var p=cell?q('.pill',cell):null; return p?{t:txt(p),c:(p.className.match(/\b(vw|wk|ok)\b/)||['',''])[1]}:null;}
function fx(v,d){return v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});}
// the report's script writes its current inputs here (plant size and thresholds)
function st(){return {mw:+root.dataset.mw||cfg.mw, wk:+root.dataset.wk||cfg.wk, vw:+root.dataset.vw||cfg.vw};}
function flagOf(v,s){return v<s.vw?'vw':(v<s.wk?'wk':'ok');}

// ---- views -------------------------------------------------------------------
var navEl=q('.nav');
function show(v,keep){
  if(!q('.view[data-v~="'+v+'"]')) v='overview';
  view=v;
  qa('.view').forEach(function(e){e.classList.toggle('on',(' '+e.dataset.v+' ').indexOf(' '+v+' ')>=0);});
  qa('.nav button, .sheet button[data-view]').forEach(function(b){if(b.dataset.view===v) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current');});
  body.className=body.className.replace(/\bv-\w+\b/g,'').trim()+' v-'+v;
  try{history.replaceState(null,'','#'+v);}catch(e){}
  if(!keep) window.scrollTo(0,0);
  var cur=q('.nav button[aria-current]');
  if(cur&&navEl&&navEl.scrollWidth>navEl.clientWidth){  // keep the current view visible in the top row
    var left=cur.offsetLeft-(navEl.clientWidth-112-cur.offsetWidth)/2;
    navEl.scrollLeft=Math.max(0,left);}
  layout();
}
qa('.nav button').forEach(function(b){b.addEventListener('click',function(){show(b.dataset.view);});});

// ---- "All" sheet (phones and tablets) ------------------------------------------------
var sheet=q('#nav-sheet'), dim=q('#nav-dim'), allb=q('#nav-all'), lastFocus=null;
function openSheet(){if(!sheet) return; lastFocus=document.activeElement; sheet.hidden=false; dim.hidden=false;
  allb.setAttribute('aria-expanded','true'); var c=q('button[aria-current]',sheet)||q('button',sheet); if(c) c.focus();}
function closeSheet(){if(!sheet||sheet.hidden) return; sheet.hidden=true; dim.hidden=true; allb.setAttribute('aria-expanded','false');
  if(lastFocus&&lastFocus.focus) lastFocus.focus();}
if(allb) allb.addEventListener('click',openSheet);
if(dim) dim.addEventListener('click',closeSheet);
document.addEventListener('keydown',function(e){if(e.key==='Escape') closeSheet();});
qa('.sheet button[data-view]').forEach(function(b){b.addEventListener('click',function(){closeSheet();show(b.dataset.view);});});

// ---- compact inputs on phones -----------------------------------------------------------
var sum=q('#ctl-sum'), dctl=q('.dctl');
if(sum) sum.addEventListener('click',function(){var o=!dctl.classList.contains('open'); dctl.classList.toggle('open',o);
  sum.setAttribute('aria-expanded',o?'true':'false'); q('.ed',sum).textContent=o?'Done ▴':'Edit ▾';});
function summary(){if(!sum) return; var s=st();
  q('.sv',sum).innerHTML='<b>'+esc(fx(s.mw,s.mw%1?1:0))+' '+esc(U)+'</b> · weak &lt; '+esc(String(s.wk))+' · very weak &lt; '+esc(String(s.vw));}

// ---- rows: the values the report's own script has just written -------------------
function rows(){return qa('tr.res[data-pid]').map(function(t){
  var c=t.cells, scr=parseFloat(txt(q('.c-scr',t))), n1c=q('.c-n1',t), n1=n1c&&q('.val',n1c)?parseFloat(txt(q('.val',n1c))):null;
  var tri=q('.c-tri .pill',t);
  return {t:t,pid:t.dataset.pid,index:txt(c[1]),group:txt(c[2]),scmva:txt(c[3]),sc:+t.dataset.scmva,sn:t.dataset.n1?+t.dataset.n1:null,
    rating:txt(q('.c-rating',t)),scr:scr,scrT:txt(q('.c-scr',t)),flag:pillOf(c[6]),max:txt(q('.c-max',t)),
    scrif:q('.c-scrif .val',t)?txt(q('.c-scrif .val',t)):'',escr:txt(q('.c-escr',t)),
    n1:n1,n1T:n1c&&q('.val',n1c)?txt(q('.val',n1c)):'',n1flag:pillOf(n1c),outage:n1c?txt(n1c.nextElementSibling):'',
    tri:tri?+txt(tri).slice(-1):null,low:n1===null?scr:Math.min(scr,n1)};});}
function pill(p){return p?"<span class='pill "+p.c+"'>"+esc(p.t)+"</span>":'';}
function triPill(L){return L?"<span class='pill "+TC[L]+"'>P"+L+"</span>":'';}

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
  var r=R.filter(function(x){return x.pid===sel;})[0];
  if(!r){el.innerHTML="<div class='empty'>Click a bus on the map or in a table for its details.</div>";return;}
  var b=D.buses[r.pid]||{}, h="<h3>"+esc(r.pid)+(b.kv?" · "+b.kv+" kV":"")+(r.group?" · group "+esc(r.group):"")+"</h3><div class='dgrid'>";
  h+=fact('SCR (intact)',r.scrT,r.flag?r.flag.c:'');
  if(r.n1T) h+=fact('SCR (N-1)',r.n1T,r.n1flag?r.n1flag.c:'');
  h+=fact('Short-circuit MVA',r.scmva);
  if(b.ka!==undefined) h+=fact('Fault current',fx(b.ka,2)+' kA');
  h+=fact('Max size, no flag',r.max+' '+U);
  if(r.scrif) h+=fact('SCRIF',r.scrif);
  if(r.escr) h+=fact('ESCR',r.escr);
  if(r.tri) h+=fact('EMT priority',r.tri,TC[r.tri]);
  h+="</div>";
  if(b.z){h+="<div class='dgrid'>"+fact('Thévenin |Z|',fx(b.z[2],3)+' Ω')+fact('R + jX',fx(b.z[0],3)+' + j'+fx(b.z[1],3)+' Ω')+fact('X/R',b.xr===null?'∞':fx(b.xr,2));
    if(b.zn) h+=fact('|Z| (N-1)',fx(b.zn[2],3)+' Ω')+fact('X/R (N-1)',b.xrn===null?'∞':fx(b.xrn,2));
    h+="</div>";}
  if(r.outage) h+="<div class='why'><b>Worst single outage:</b> "+esc(r.outage)+"</div>";
  var w=q('tr.trirow[data-pid="'+r.pid.replace(/"/g,'\\"')+'"] .c-why');
  if(w) h+="<div class='why'><b>Why this EMT priority:</b> "+esc(txt(w))+"</div>";
  if(D.cmd) h+="<div class='why'><b>Full data sheet:</b> <code>"+esc(D.cmd.replace('{bus}',r.pid.replace(/^Bus /,'')).replace('{size}',String(st().mw)))+"</code></div>";
  el.innerHTML=h;
}
function select(pid,jump){
  sel=pid;
  qa('.netmap g.bus').forEach(function(g){g.classList.toggle('sel','Bus '+g.dataset.label===pid);});
  qa('tr.res').forEach(function(t){t.classList.toggle('sel',t.dataset.pid===pid);});
  var R=rows(); weakest(R); detail(R);
  if(jump&&view!=='overview'&&view!=='map') show('overview');
}
document.addEventListener('click',function(e){
  if(!e.target.closest) return;
  var g=e.target.closest('.netmap g.bus');
  if(g){select('Bus '+g.dataset.label,false);
    var det=q('#dash-detail'); if(det&&window.innerWidth<=960&&det.scrollIntoView) det.scrollIntoView({behavior:'smooth',block:'nearest'});
    return;}
  var w=e.target.closest('.weak tbody tr');
  if(w){select(w.dataset.pid,false);return;}
  var m=e.target.closest('.mchart .nm[data-pid]');
  if(m){select(m.dataset.pid,true);return;}
  var t=e.target.closest('tr.res[data-pid]');
  if(t&&!e.target.closest('a,input,button')){select(t.dataset.pid,true);}
});
document.addEventListener('keydown',function(e){if(e.key!=='Enter'||!e.target.closest) return;
  var w=e.target.closest('.weak tbody tr,.mchart .nm[data-pid]'); if(w) select(w.dataset.pid,!!w.closest('.mchart'));});

// ---- badges ---------------------------------------------------------------------
function badge(v,n,c){qa('[data-view="'+v+'"] .badge').forEach(function(b){b.textContent=n?String(n):''; b.className='badge'+(c?' '+c:'');});}
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

// ---- map colored by EMT study priority (priority 1 and 2 pulse) ---------------------
var SVGNS='http://www.w3.org/2000/svg', mm=q('#map-mode');
if(mm&&q('.c-tri')){var o=document.createElement('option');o.value='tri';o.textContent='EMT study priority';mm.appendChild(o);}
function triMap(R){
  if(!mm||mm.value!=='tri') return;
  var L={}; R.forEach(function(r){L[r.pid]=r;});
  var byBus={};
  qa('.netmap g.bus').forEach(function(g){var r=L['Bus '+g.dataset.label], c=r&&r.tri?TC[r.tri]:'na';
    byBus[g.dataset.bus]=c; var n=q('.node',g); n.setAttribute('class','node '+c);
    var h=q('.halo',g), x=+g.dataset.x, y=+g.dataset.y;
    if(c==='vw'||c==='wk'){if(!h){h=document.createElementNS(SVGNS,'circle');h.setAttribute('cx',x);h.setAttribute('cy',y);h.setAttribute('r',9);g.insertBefore(h,g.firstChild);}
      h.setAttribute('class','halo '+c);} else if(h) g.removeChild(h);
    q('title',g).textContent='Bus '+g.dataset.label+': EMT study priority '+(r&&r.tri?r.tri:'not rated');});
  qa('.netmap .heat circle').forEach(function(c){c.setAttribute('class','hz '+(byBus[c.dataset.bus]||'ok'));});
  var labels=q('.netmap .labels');
  if(labels){while(labels.firstChild) labels.removeChild(labels.firstChild);
    var p1=R.filter(function(r){return r.tri===1;}).sort(function(a,b){return a.low-b.low;}).slice(0,cfg.maxLabels||8).map(function(r){return r.pid;});
    qa('.netmap g.bus').forEach(function(g){if(p1.indexOf('Bus '+g.dataset.label)<0) return;
      var t=document.createElementNS(SVGNS,'text');t.setAttribute('x',(+g.dataset.x+12).toFixed(1));t.setAttribute('y',(+g.dataset.y-9).toFixed(1));
      t.setAttribute('class','lbl');t.textContent='Bus '+g.dataset.label+' · P1';labels.appendChild(t);});}
  var note=q('#map-mode-note'); if(note) note.textContent='Colors show each bus’s EMT study priority: 1 red, 2 amber, 3 green. Priorities 1 and 2 pulse.';
}

// ---- map: fit to the screen, zoom and pan ------------------------------------------------
var svg=q('.netmap'), wrap=svg?svg.closest('.mapwrap'):null, VB0=null, vb=null;
if(svg){VB0=svg.getAttribute('viewBox').split(/[\s,]+/).map(Number); vb=VB0.slice();}
function setVB(v){vb=v; svg.setAttribute('viewBox',v.map(function(x){return x.toFixed(2);}).join(' ')); labelSize();}
function scaleNow(){var r=svg.getBoundingClientRect(); return (r.width&&r.height)?Math.min(r.width/vb[2],r.height/vb[3]):1;}
function labelSize(){if(!svg) return; var k=scaleNow(); svg.style.setProperty('--lfs',(12/k).toFixed(2)+'px'); svg.style.setProperty('--lsw',(3/k).toFixed(2)+'px');}
function clampVB(v){var w=Math.min(Math.max(v[2],VB0[2]/12),VB0[2]*1.5), h=w*VB0[3]/VB0[2];
  var cx=v[0]+v[2]/2, cy=v[1]+v[3]/2;
  cx=Math.min(Math.max(cx,VB0[0]),VB0[0]+VB0[2]); cy=Math.min(Math.max(cy,VB0[1]),VB0[1]+VB0[3]);
  return [cx-w/2,cy-h/2,w,h];}
function zoomAt(f,px,py){  // f>1 zooms in, around the screen point (px,py)
  var r=svg.getBoundingClientRect(), k=scaleNow();
  var ox=(r.width-vb[2]*k)/2, oy=(r.height-vb[3]*k)/2;
  var ux=vb[0]+((px===undefined?r.width/2:px-r.left)-ox)/k, uy=vb[1]+((py===undefined?r.height/2:py-r.top)-oy)/k;
  var w=vb[2]/f, h=vb[3]/f;
  setVB(clampVB([ux-(ux-vb[0])/f, uy-(uy-vb[1])/f, w, h]));}
function fit(){if(svg) setVB(VB0.slice());}
if(svg&&wrap){
  var zc=document.createElement('div'); zc.className='mapzoom';
  zc.innerHTML="<button type='button' class='zbtn' data-z='in' aria-label='Zoom in'>+</button><button type='button' class='zbtn' data-z='out' aria-label='Zoom out'>−</button><button type='button' class='zbtn fit' data-z='fit' aria-label='Fit the whole network'>Fit</button>";
  wrap.appendChild(zc);
  var zh=document.createElement('div'); zh.className='zhint'; wrap.appendChild(zh);
  zc.addEventListener('click',function(e){var b=e.target.closest('button'); if(!b) return;
    if(b.dataset.z==='in') zoomAt(1.5); else if(b.dataset.z==='out') zoomAt(1/1.5); else fit();});
  svg.addEventListener('wheel',function(e){if(view!=='map'&&!e.ctrlKey&&!e.metaKey) return;
    e.preventDefault(); zoomAt(Math.exp(-e.deltaY*0.0015),e.clientX,e.clientY);},{passive:false});
  var pts={}, start=null, moved=false;
  svg.addEventListener('pointerdown',function(e){if(e.button!==0&&e.pointerType==='mouse') return;
    pts[e.pointerId]={x:e.clientX,y:e.clientY}; moved=false;
    start={vb:vb.slice(),pts:JSON.parse(JSON.stringify(pts))};});
  svg.addEventListener('pointermove',function(e){if(!pts[e.pointerId]||!start) return;
    pts[e.pointerId]={x:e.clientX,y:e.clientY};
    var ids=Object.keys(pts), k=scaleNow();
    if(ids.length===1){var p0=start.pts[ids[0]]; if(!p0) return; var dx=e.clientX-p0.x, dy=e.clientY-p0.y;
      if(!moved&&Math.abs(dx)+Math.abs(dy)<6) return;
      if(!moved){moved=true; try{svg.setPointerCapture(e.pointerId);}catch(_){} svg.classList.add('grab');}
      setVB(clampVB([start.vb[0]-dx/k,start.vb[1]-dy/k,start.vb[2],start.vb[3]]));}
    else if(ids.length===2&&start.pts[ids[0]]&&start.pts[ids[1]]){moved=true;
      var a0=start.pts[ids[0]],b0=start.pts[ids[1]],a1=pts[ids[0]],b1=pts[ids[1]];
      var d0=Math.hypot(a0.x-b0.x,a0.y-b0.y)||1, d1=Math.hypot(a1.x-b1.x,a1.y-b1.y)||1;
      vb=start.vb.slice(); setVB(vb); zoomAt(d1/d0,(a1.x+b1.x)/2,(a1.y+b1.y)/2);}});
  var up=function(e){delete pts[e.pointerId]; svg.classList.remove('grab'); start=Object.keys(pts).length?{vb:vb.slice(),pts:JSON.parse(JSON.stringify(pts))}:null;};
  svg.addEventListener('pointerup',up); svg.addEventListener('pointercancel',up);
  svg.addEventListener('click',function(e){if(moved){e.stopPropagation();e.preventDefault();moved=false;}},true);
}
function layout(){  // size the map to the screen, and give tables the room below the top bar
  var vs=q('.views'); if(vs){var t=vs.getBoundingClientRect().top+window.scrollY; root.style.setProperty('--avail',Math.max(320,window.innerHeight-Math.min(t,window.innerHeight*0.5))+'px');}
  if(!wrap) return;
  var w=wrap.clientWidth||wrap.parentNode.clientWidth, ar=VB0[3]/VB0[2], h;
  if(view==='map'){var top=wrap.getBoundingClientRect().top+window.scrollY, below=0, n=wrap.nextElementSibling;
    while(n){below+=n.offsetHeight; n=n.nextElementSibling;}
    h=Math.max(300,window.innerHeight-top-below-34);
    if(window.innerWidth<=640) h=Math.min(h,Math.max(260,w*ar*1.2));}
  else h=Math.max(240,Math.min(w*ar,window.innerHeight*0.66));
  wrap.style.setProperty('--maph',Math.round(h)+'px');
  var zh=q('.zhint',wrap); if(zh) zh.textContent=view==='map'?'Scroll or pinch to zoom · drag to move':'Ctrl + scroll or pinch to zoom · drag to move';
  labelSize();
}
window.addEventListener('resize',function(){layout();});

// ---- one chart: SCR intact (bar) and N-1 (diamond), with the largest size --------------------
var MC=q('#mchart'), mcSort=q('#mc-sort'), mcMore=q('#mc-more'), mcAll=false, MC_TOP=20;
function busNum(pid){var m=pid.match(/(\d+(?:\.\d+)?)/); return m?+m[1]:Infinity;}
function chart(R,all){
  if(!MC) return; var s=st(), hasN1=R.some(function(r){return r.sn!==null;});
  var d=R.map(function(r){var v=r.sc/s.mw, n=r.sn===null?null:r.sn/s.mw;
    return {pid:r.pid,v:v,n:n,low:n===null?v:Math.min(v,n),max:r.max};});
  var k=mcSort?mcSort.value:'weak';
  d.sort(function(a,b){
    if(k==='scr') return b.v-a.v; if(k==='n1') return (a.n===null?a.v:a.n)-(b.n===null?b.v:b.n);
    if(k==='max') return b.v-a.v; if(k==='bus') return busNum(a.pid)-busNum(b.pid)||(a.pid<b.pid?-1:1);
    return a.low-b.low;});
  var mx=Math.max.apply(null,d.map(function(x){return Math.max(x.v,x.n||0);}).concat([s.wk*1.5]));
  var show=(all||mcAll||d.length<=MC_TOP+5)?d:d.slice(0,MC_TOP);
  var pc=function(v){return (Math.max(v,0)/mx*100).toFixed(2)+'%';};
  var fmt=function(v){return String(+(+v).toPrecision(6));};
  var axis="<div class='maxis'><span class='cap'>SCR (bar: intact"+(hasN1?"; ◆ N-1":"")+")</span>"+
    "<span class='at vw' style='left:"+pc(s.vw)+"' title='Very weak below "+fmt(s.vw)+"'>"+fmt(s.vw)+"</span>"+
    "<span class='at wk' style='left:"+pc(s.wk)+"' title='Weak below "+fmt(s.wk)+"'>"+fmt(s.wk)+"</span></div>";
  var h="<div class='hd'>Bus</div>"+axis+"<div class='hd n'>SCR</div>"+(hasN1?"<div class='hd n'>N-1</div>":"")+"<div class='hd n mx'>Max, no flag</div>";
  show.forEach(function(x){var c=flagOf(x.v,s), cn=x.n===null?'':flagOf(x.n,s);
    h+="<div class='nm' tabindex='0' role='button' data-pid='"+esc(x.pid)+"' title='"+esc(x.pid)+": details'>"+esc(x.pid)+"</div>"+
      "<div class='mtrack'><div class='mbar "+c+"' style='width:"+pc(x.v)+"'></div>"+
      "<div class='mtick vw' style='left:"+pc(s.vw)+"'></div><div class='mtick wk' style='left:"+pc(s.wk)+"'></div>"+
      (x.n===null?"":"<div class='mdia "+cn+"' style='left:"+pc(x.n)+"' title='N-1 SCR "+x.n.toFixed(2)+"'></div>")+"</div>"+
      "<div class='n'>"+x.v.toFixed(2)+"<span class='pill "+c+"'>"+NAME[c]+"</span></div>"+
      (hasN1?"<div class='n'>"+(x.n===null?'':x.n.toFixed(2))+"</div>":"")+
      "<div class='n mx'>"+esc(x.max)+" "+esc(U)+"</div>";});
  if(!hasN1) MC.style.gridTemplateColumns='minmax(64px,auto) minmax(120px,1fr) auto auto';
  MC.innerHTML=h;
  if(mcMore){mcMore.hidden=d.length<=MC_TOP+5; mcMore.textContent=mcAll?'Show the first '+MC_TOP:'Show all '+d.length+' buses';}
  var ttl=q('#mc-title'); if(ttl) ttl.textContent=fx(s.mw,s.mw%1?1:0);
  qa('.mc-vw').forEach(function(e){e.textContent=fmt(s.vw);}); qa('.mc-wk').forEach(function(e){e.textContent=fmt(s.wk);});
}
if(mcSort) mcSort.addEventListener('change',function(){chart(rows());});
if(mcMore) mcMore.addEventListener('click',function(){mcAll=!mcAll; chart(rows());});
window.addEventListener('beforeprint',function(){chart(rows(),true);});
window.addEventListener('afterprint',function(){chart(rows());});

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

// ---- print and CSV ---------------------------------------------------------------------------
function doPrint(){closeSheet(); setTimeout(function(){window.print();},50);}
function csv(){
  if(!rt) return;
  var cell=function(c){var v=q('.val',c)?txt(q('.val',c)):(q('.pill',c)&&c.children.length===1&&!c.firstChild.nodeValue?txt(q('.pill',c)):txt(c));
    v=v.replace(/\s+/g,' '); if(/^[\d,]+(\.\d+)?$/.test(v)) v=v.replace(/,/g,''); return '"'+v.replace(/"/g,'""')+'"';};
  var head=qa('thead th',rt).map(function(th){return '"'+txt(th).replace(/"/g,'""')+'"';}).concat(['"weak_below"','"very_weak_below"','"tool_version"']);
  var s=st(), lines=[head.join(',')];
  qa('tr.res',rt).forEach(function(t){lines.push(qa('td',t).map(cell).concat([s.wk,s.vw,'"'+D.version+'"']).join(','));});
  var blob=new Blob(['﻿'+lines.join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'}), a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='scr-screen-results.csv'; document.body.appendChild(a); a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},500);}
qa('[data-act=print]').forEach(function(b){b.addEventListener('click',doPrint);});
qa('[data-act=csv]').forEach(function(b){b.addEventListener('click',function(){closeSheet();csv();});});

// ---- refresh after the report's script has recalculated -------------------------------------
function refresh(){var R=rows(); triMap(R); R=rows(); badges(R); weakest(R); detail(R); chart(R); summary();}
var pend=false; function later(){if(pend) return; pend=true; setTimeout(function(){pend=false;refresh();},0);}
['input','change','click'].forEach(function(ev){document.addEventListener(ev,function(e){
  if(e.target.closest&&e.target.closest('.dtop,.mapctl,#cost-body,.view[data-v~="cost"],.gbox')) later();});});
var R0=rows();
if(R0.length){sel=R0.slice().sort(function(a,b){return a.low-b.low;})[0].pid;}
var first=(location.hash||'').slice(1).replace(/[^a-z0-9]/g,'');
show(q('.nav button[data-view="'+first+'"]')?first:'overview',true);
select(sel,false); filter(); refresh(); layout();
if(window.ResizeObserver&&wrap) new ResizeObserver(function(){labelSize();}).observe(wrap);
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
    has_svg = "<svg class='netmap'" in "".join(views["map"])  # no drawing above the map's bus limit
    shown = [(key, label) for key, label, _ in VIEWS
             if key == "overview" or (views[key] and (key != "map" or has_svg))]
    out = [p["head"].replace("</style>", DASH_CSS + "</style>", 1).replace("<body>", "<body class='dash v-overview'>", 1)]
    out.append("<div class='app'><aside class='side'><div class='brand'>SCR-Screen<small>System strength dashboard</small></div>"
               "<div class='navrow'><nav class='nav' aria-label='Views'>")
    for key, label in shown:
        cur = " aria-current='page'" if key == "overview" else ""
        out.append(f"<button type='button' data-view='{key}'{cur}><span>{escape(label)}</span>"
                   "<span class='badge'></span></button>")
    out.append(f"</nav><button type='button' class='allbtn' id='nav-all' aria-haspopup='dialog' aria-expanded='false' "
               f"aria-controls='nav-sheet'><span>All {len(shown)} \u25be</span></button></div>"
               f"<div class='sfoot'>{p['version']}<br>Screening only. Not a substitute for "
               "interconnection studies.</div></aside><div class='main'>")
    out.append(f"<div class='dtop'><div class='dhead'>{p['header']}<div class='dbtns'>"
               "<button type='button' class='dbtn' data-act='print'>Print / PDF</button>"
               "<button type='button' class='dbtn' data-act='csv'>Download CSV</button></div></div>"
               "<button type='button' class='ctlsum' id='ctl-sum' aria-expanded='false' aria-controls='dctl'>"
               "<span class='sv'></span><span class='ed'>Edit \u25be</span></button>"
               f"<div class='dctl' id='dctl'>{p['whatif']}</div></div>")
    out.append(f"<div class='kpis'>{p['cards']}</div><div class='views'>")

    # Overview and the network map view share one map; the side panel shows the weakest
    # locations (Overview only) and the selected bus.
    side = ("<div class='panel sidep'><div class='weakbox'><h2>Weakest locations</h2>"
            "<div class='note' style='margin:-6px 0 6px'>Lowest SCR in any condition shown. Click a bus here"
            + (" or on the map" if has_svg else "") + " for its details.</div><div id='dash-weak'></div></div><div class='det' id='dash-detail'></div></div>")
    if has_map:
        out.append(f"<section class='view on' data-v='overview{' map' if has_svg else ''}'><div class='ov'><div class='panel mapp'>"
                   + "".join(views["map"]) + "</div>" + side + "</div></section>")
    else:
        out.append("<section class='view on' data-v='overview'><div class='ov nomap'>" + side + "</div></section>")
    tools = ("<div class='tools'><input type='search' id='dash-search' placeholder='Search bus or group' "
             "aria-label='Search bus or group'><label title='Buses with a weak or very weak flag on any SCR shown'>"
             "<input type='checkbox' id='dash-only'> Flagged only</label>"
             "<span class='count' id='dash-count'></span><span class='count'>Click a column heading to sort; "
             "click a row for the bus details.</span></div>")
    merged = ("<div class='panel'><h2>SCR by bus for a <span id='mc-title'></span> " + escape(p["unit"]) + " plant</h2>"
              "<div class='mc-tools'><label>Order <select id='mc-sort'>"
              "<option value='weak'>Weakest first</option><option value='scr'>SCR, highest first</option>"
              "<option value='n1'>N-1 SCR, lowest first</option><option value='max'>Largest size first</option>"
              "<option value='bus'>Bus number</option></select></label></div>"
              "<div class='mc-legend'><span><i class='lb'></i>SCR, network intact</span>"
              "<span><i class='ld'></i>SCR under the worst single outage (N-1)</span>"
              "<span><i class='lt vw'></i>Very weak below <b class='mc-vw'></b></span>"
              "<span><i class='lt wk'></i>Weak below <b class='mc-wk'></b></span>"
              "<span>Max, no flag: the largest plant before a weak flag (SCMVA \u00f7 weak threshold)</span></div>"
              "<div class='mchart' id='mchart'></div>"
              "<button type='button' class='dbtn mc-more' id='mc-more' hidden></button></div>")
    for key, _, _ in VIEWS:
        if key in ("overview", "map") or not views[key]:
            continue
        if key == "charts":  # one chart replaces the two report charts (kept, hidden, for the report's script)
            inner = merged + "".join(f"<div class='panel legacy' aria-hidden='true'>{h}</div>" for h in views[key])
        else:
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
    cur_attr = {key: (" aria-current='page'" if key == "overview" else "") for key, _ in shown}
    sheet = "".join(f"<button type='button' data-view='{key}'{cur_attr[key]}>"
                    f"<span>{escape(label)}</span><span class='badge'></span></button>" for key, label in shown)
    out.append("<div class='dim' id='nav-dim' hidden></div><div class='sheet' id='nav-sheet' role='dialog' aria-modal='true' "
               f"aria-label='All views' hidden><div class='grip'></div><h2>Views</h2>{sheet}"
               "<div class='acts'><button type='button' data-act='print'>Print / PDF</button>"
               "<button type='button' data-act='csv'>Download CSV</button></div></div>")
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
    um = re.search(r"aria-label='Plant size in ([^']+)'", whatif)
    return {"head": head, "header": header, "cards": cards, "whatif": whatif, "hint": hint, "costctl": costctl, "sections": sections,
            "disc": disc, "scripts": scripts, "version": escape(ver.group(0)) if ver else "SCR-Screen",
            "unit": um.group(1) if um else "MW"}
