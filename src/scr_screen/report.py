"""Self-contained HTML screening report.

One HTML file, no internet needed: all styling, charts, animation and the
interactive slider are built in, so the report can be emailed, archived, or
printed to PDF from any browser. Every colored element also shows its number
and flag text, so the report reads correctly in black and white and for
color-blind readers. Animations respect the reader's "reduce motion" setting
and are switched off when printing.

Bus-scan reports are interactive: a plant-size slider recalculates every SCR
in the browser (SCR = SCMVA / plant MW), so no re-run is needed to try sizes.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .screening import ScreeningResult

MAX_CHART_ROWS = 60  # charts show at most this many rows (the weakest); tables show all

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
--vw:#d92d20;--wk:#dc6803;--ok:#079455;--vwbg:#fef3f2;--wkbg:#fffaeb;--okbg:#ecfdf3;--accent:#0a9396;--hl:#fff7e6}
@media (prefers-color-scheme:dark){:root{--bg:#101828;--fg:#f2f4f7;--muted:#98a2b3;--line:#344054;
--card:#1d2939;--vwbg:#3b1512;--wkbg:#3a2508;--okbg:#0b3321;--hl:#2a2010}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 24px 48px}
header{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;border-bottom:3px solid var(--accent);padding-bottom:14px}
h1{font-size:24px;margin:0}h2{font-size:17px;margin:32px 0 12px}
.sub,.meta{color:var(--muted);font-size:13px}.meta{text-align:right}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:20px}
.card{background:var(--card);border-radius:10px;padding:14px 16px;animation:rise .5s ease both}
.card:nth-child(2){animation-delay:.08s}.card:nth-child(3){animation-delay:.16s}.card:nth-child(4){animation-delay:.24s}
.card .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:26px;font-weight:600;transition:color .3s}
.v.vw{color:var(--vw)}.v.wk{color:var(--wk)}.v.ok{color:var(--ok)}
.slider{display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:var(--card);border-radius:10px;padding:14px 18px;margin-top:16px}
.slider label{font-weight:600}
.slider input[type=range]{flex:1;min-width:200px;accent-color:var(--accent)}
.slider input[type=number]{width:110px;padding:6px 8px;font:inherit;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.slider .hint{width:100%;font-size:12px;color:var(--muted)}
.slider input.bad{border-color:var(--vw);outline:2px solid var(--vw)}
.slider .msg{color:var(--vw);font-size:13px;font-weight:600}
.whatif{display:block}
.whatif .wrow{display:flex;align-items:center;gap:10px 18px;flex-wrap:wrap;margin:4px 0}
.whatif .wh{width:100%;font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-top:10px}
.whatif .fld{display:flex;align-items:center;gap:6px;font-size:13px}
.whatif .fld input{width:104px}
.whatif button{font:inherit;padding:5px 10px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer}
.cost input{width:96px;padding:3px 6px;font:inherit;font-size:13px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--fg);text-align:right}
.cost input.bad{border-color:var(--vw);outline:2px solid var(--vw)}
.chart{position:relative;margin-top:6px}
.row{display:grid;grid-template-columns:150px 1fr 120px;gap:10px;align-items:center;margin:6px 0;font-size:14px}
.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.track{position:relative;height:22px;background:var(--card);border-radius:5px}
.bar{height:100%;border-radius:5px;animation:grow .8s cubic-bezier(.2,.8,.2,1) both;transition:width .45s ease,background-color .3s}
.bar.vw{background:var(--vw)}.bar.wk{background:var(--wk)}.bar.ok{background:var(--ok)}.bar.cap{background:var(--accent)}
.tick{position:absolute;top:-4px;bottom:-4px;border-left:2px dashed var(--muted);transition:left .45s ease}
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
th.n,td.n{text-align:right;font-variant-numeric:tabular-nums}
.tablewrap{overflow-x:auto}
.box{background:var(--card);border-radius:10px;padding:14px 18px;font-size:14px}
.box ul{margin:6px 0 0;padding-left:20px}
.disc{border-left:4px solid var(--wk);background:var(--wkbg);padding:12px 16px;border-radius:6px;font-size:13px;margin-top:24px}
footer{margin-top:28px;color:var(--muted);font-size:12px}
.mapwrap{border:1px solid var(--line);border-radius:10px;padding:8px;overflow-x:auto}
.netmap{width:100%;min-width:560px;height:auto;display:block}
.netmap .edge{stroke:var(--muted);stroke-opacity:.55;stroke-width:1.6;animation:fade .6s ease both}
.netmap .node{stroke:var(--bg);stroke-width:1.5;transform-box:fill-box;transform-origin:center;
animation:pop .45s ease-out both;transition:fill .3s}
.netmap .node.vw{fill:var(--vw)}.netmap .node.wk{fill:var(--wk)}.netmap .node.ok{fill:var(--ok)}.netmap .node.na{fill:var(--muted)}
.netmap .halo{fill:none;stroke-width:2;transform-box:fill-box;transform-origin:center;animation:pulse 1.8s ease-out 1.2s infinite both;pointer-events:none}
.netmap .halo.vw{stroke:var(--vw)}.netmap .halo.wk{stroke:var(--wk)}
.netmap .lbl{font-size:12px;font-weight:600;fill:var(--fg);paint-order:stroke;stroke:var(--bg);stroke-width:3px;animation:fade .5s ease 1s both}
.cmp .track{background:transparent;border-bottom:1px solid var(--line);border-radius:0}
.cmp .seg{position:absolute;top:10px;height:2px;background:var(--muted);transition:left .45s,width .45s}
.cmp .dot{position:absolute;top:4px;width:14px;height:14px;margin-left:-7px;border-radius:50%;transition:left .45s,background-color .3s,border-color .3s;animation:fade .6s ease both}
.cmp .dot.a.vw{background:var(--vw)}.cmp .dot.a.wk{background:var(--wk)}.cmp .dot.a.ok{background:var(--ok)}
.cmp .dot.b{background:var(--bg);border:3px solid var(--ok)}.cmp .dot.b.vw{border-color:var(--vw)}.cmp .dot.b.wk{border-color:var(--wk)}
.cmp .row.diff{background:var(--hl);border-radius:6px}
.cmp .row.diff .name{font-weight:700}
.cost td,.cost th{padding:7px 8px}
.cost .mini{display:flex;height:12px;min-width:120px;border-radius:3px;overflow:hidden;background:var(--card)}
.cost .mini span{height:100%;transition:width .45s ease}
.seg-c{background:var(--wk)}.seg-g{background:var(--accent)}.seg-p{background:var(--muted)}
.cost .inc{color:var(--muted);font-size:12px}
.cost .k-tc{font-size:13px;line-height:1.4;min-width:150px}.cost .meet{color:var(--ok);font-weight:600}.cost .below{color:var(--wk);font-weight:600}
.calert{margin:4px 0 10px;padding:10px 14px;border-radius:8px;border-left:4px solid var(--wk);background:var(--wkbg);font-size:14px}
.calert.good{border-left-color:var(--ok);background:var(--okbg)}
.cost td:nth-child(2){white-space:nowrap}
.inputs{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--muted);margin-bottom:10px}
.inputs b{color:var(--fg);font-weight:600}
@keyframes fade{from{opacity:0}}
@keyframes rise{from{opacity:0;transform:translateY(8px)}}
@keyframes grow{from{width:0}}
@keyframes pop{0%{transform:scale(0)}70%{transform:scale(1.3)}100%{transform:scale(1)}}
@keyframes pulse{0%{transform:scale(1);opacity:.7}100%{transform:scale(2.6);opacity:0}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
@media print{body{font-size:12px}.wrap{padding:0}h2{break-after:avoid}.gbox,.card,.row,tr{break-inside:avoid}
.slider{display:none}*{animation:none!important;transition:none!important}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
@media (max-width:640px){.row{grid-template-columns:90px 1fr 96px}}
"""

# Recalculates every SCR in the browser when the plant size changes.
# Plain JavaScript, no libraries, no network access.
SCRIPT = r"""
(function(){
var cfgEl=document.getElementById('scr-cfg'); if(!cfgEl) return;
var cfg=JSON.parse(cfgEl.textContent), C0=cfg.cost||null;
var S={};
function init(){S.mw=cfg.mw;S.vw=cfg.vw;S.wk=cfg.wk;
  if(C0){S.target=C0.target;S.xd=C0.xd;S.xt=C0.xt;S.cpm=C0.cpm;S.gtc=C0.gtc;S.follow=C0.follow;}}
init();
var NAME={vw:'Very weak',wk:'Weak',ok:'No flag'}, WORD={vw:'very weak',wk:'weak',ok:'none'};
var SVG='http://www.w3.org/2000/svg';
function flag(v){return v<S.vw?'vw':(v<S.wk?'wk':'ok');}
function q(s,r){return (r||document).querySelector(s);}
function qa(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));}
function f(v,d){return v.toFixed(d);}
function num(v){return v.toLocaleString('en-US',{maximumFractionDigits:1});}
function g(v){return String(+(+v).toPrecision(6));}
function pill(el,c){if(el){el.className='pill '+c;el.textContent=NAME[c];}}
function money(v){if(v===null) return '\u2014';var a=Math.abs(v);
  if(a>=1e9) return '$'+(v/1e9).toFixed(2)+'B'; if(a>=1e6) return '$'+(v/1e6).toFixed(1)+'M';
  if(a>=1e3) return '$'+(v/1e3).toFixed(0)+'k'; return '$'+v.toFixed(0);}

function update(){
  var mw=S.mw;
  qa('[data-mw-text]').forEach(function(e){e.textContent=num(mw);});
  qa('.th-vw').forEach(function(e){e.textContent=g(S.vw);});
  qa('.th-wk').forEach(function(e){e.textContent=g(S.wk);});
  qa('.tick[data-kind]').forEach(function(t){t.dataset.th=t.dataset.kind==='vw'?S.vw:S.wk;
    var sp=q('span',t); if(sp) sp.textContent=g(t.dataset.th);});
  var all=qa('tr.res[data-scmva]').map(function(t){return +t.dataset.scmva;});
  var low=Math.min.apply(null,all)/mw, flagged=0;
  all.forEach(function(s){if(flag(s/mw)!=='ok') flagged++;});
  var lv=q('#card-low'); if(lv){lv.textContent=f(low,2);lv.className='v '+flag(low);}
  var fv=q('#card-flag'); if(fv){fv.textContent=flagged+' of '+all.length;fv.className='v '+(flagged?'wk':'ok');}
  var rows=qa('.scr-chart .row');
  var mx=Math.max.apply(null,rows.map(function(r){return +r.dataset.scmva/mw;}).concat([S.wk*1.5]));
  rows.forEach(function(r){var v=+r.dataset.scmva/mw,c=flag(v),b=q('.bar',r);
    b.className='bar '+c;b.style.width=Math.max(v/mx*100,0.8)+'%';q('.val',r).textContent=f(v,2);pill(q('.pill',r),c);});
  qa('.scr-chart .tick').forEach(function(t){t.style.left=(+t.dataset.th/mx*100)+'%';});
  qa('tr.res[data-scmva]').forEach(function(t){var v=+t.dataset.scmva/mw,c=flag(v);
    q('.c-rating',t).textContent=mw.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1});
    q('.c-scr',t).textContent=f(v,3);pill(q('.pill',t),c);
    var cm=q('.c-max',t); if(cm) cm.textContent=(+t.dataset.scmva/S.wk).toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1});});
  var caps=qa('.cap-row'), cmax=Math.max.apply(null,caps.map(function(r){return +r.dataset.scmva;}).concat([1]));
  caps.forEach(function(r){var v=+r.dataset.scmva/S.wk;q('.bar',r).style.width=Math.max(+r.dataset.scmva/cmax*100,0.8)+'%';
    q('.val',r).textContent=Math.round(v).toLocaleString('en-US')+' MW';});
  var labels=q('.netmap .labels');
  if(labels){while(labels.firstChild) labels.removeChild(labels.firstChild);}
  var gs=qa('.netmap g.bus[data-scmva]');
  var hi=gs.filter(function(g){return flag(+g.dataset.scmva/mw)!=='ok';})
    .sort(function(a,b){return a.dataset.scmva-b.dataset.scmva;}).slice(0,cfg.maxLabels||8);
  gs.forEach(function(g){
    var v=+g.dataset.scmva/mw,c=flag(v),big=c!=='ok',x=+g.dataset.x,y=+g.dataset.y,top=hi.indexOf(g)>=0;
    var sh=q('.node',g); sh.setAttribute('class','node '+c);
    if(g.dataset.src==='1'){var s=big?15:12;sh.setAttribute('x',f(x-s/2,1));sh.setAttribute('y',f(y-s/2,1));
      sh.setAttribute('width',s);sh.setAttribute('height',s);} else {sh.setAttribute('r',big?9:6);}
    var h=q('.halo',g);
    if(top){if(!h){h=document.createElementNS(SVG,'circle');h.setAttribute('cx',x);h.setAttribute('cy',y);
      h.setAttribute('r',9);g.insertBefore(h,g.firstChild);} h.setAttribute('class','halo '+c);}
    else if(h){g.removeChild(h);}
    q('title',g).textContent='Bus '+g.dataset.label+': SCR '+f(v,2)+' ('+WORD[c]+')'+(g.dataset.src==='1'?' \u00b7 generator/source bus':'');
    if(top&&labels){var t=document.createElementNS(SVG,'text');t.setAttribute('x',f(x+12,1));t.setAttribute('y',f(y-9,1));
      t.setAttribute('class','lbl');t.textContent='Bus '+g.dataset.label+' \u00b7 '+f(v,2);labels.appendChild(t);}
  });
  var crow=qa('.cmp .row'), cmx=S.wk*1.5, diff=0;
  crow.forEach(function(r){cmx=Math.max(cmx,+r.dataset.scmva/mw,+r.dataset.scmva2/mw);});
  crow.forEach(function(r){var a=+r.dataset.scmva/mw,b=+r.dataset.scmva2/mw,ca=flag(a),cb=flag(b);
    var pa=a/cmx*100,pb=b/cmx*100,da=q('.dot.a',r),db=q('.dot.b',r),sg=q('.seg',r);
    da.className='dot a '+ca;da.style.left=pa+'%';db.className='dot b '+cb;db.style.left=pb+'%';
    sg.style.left=Math.min(pa,pb)+'%';sg.style.width=Math.abs(pb-pa)+'%';
    q('.val',r).textContent=f(a,2)+' / '+f(b,2);
    if(ca!==cb){r.classList.add('diff');diff++;} else r.classList.remove('diff');});
  qa('.cmp-tick').forEach(function(t){t.style.left=(+t.dataset.th/cmx*100)+'%';});
  var dc=q('#cmp-diff'); if(dc) dc.textContent=diff;
  if(C0) costUpdate(true);
}

function costUpdate(resort){
  var body=q('#cost-body'); if(!body) return;
  var set=function(id,t){var e=q('#'+id); if(e) e.textContent=t;};
  set('ci-target',g(S.target)); set('ci-x',g(S.xd)+' + '+g(S.xt)+' pu');
  set('ci-cpm',S.cpm===null?'not entered':money(S.cpm)+'/MVA');
  set('ci-gtc',S.gtc===null?'not entered':money(S.gtc)+'/mile');
  var x=S.xd+S.xt, data=[], mx=0;
  qa('tr',body).forEach(function(t){
    var sc=+t.dataset.scmva, need=Math.max(0,S.mw*S.target-sc), cm=need*x, ok=true;
    var cc=cm===0?0:(S.cpm===null?null:cm*S.cpm); if(cc===null) ok=false;
    var dist=t.dataset.dist===''?null:+t.dataset.dist;
    var gc=dist===null?null:(S.gtc===null?null:dist*S.gtc); if(dist!==null&&gc===null) ok=false;
    var pc=t.dataset.poi===''?null:+t.dataset.poi;
    var parts=[cc,gc,pc].filter(function(v){return v!==null;});
    var tot=parts.length?parts.reduce(function(a,b){return a+b;},0):null;
    if(tot!==null) mx=Math.max(mx,tot);
    data.push({t:t,need:need,cm:cm,cc:cc,gc:gc,pc:pc,tot:tot,ok:ok,scr:sc/S.mw,meets:sc/S.mw>=S.target,maxT:sc/S.target,
      bus:q('td:nth-child(2)',t).textContent});});
  var below=data.filter(function(d){return !d.meets;}), al=q('#cost-alert');
  if(al){al.className='calert'+(below.length?'':' good');
    al.innerHTML=below.length?'<b>'+below.length+' of '+data.length+' bus(es) are below your target SCR of '+g(S.target)+':</b> '+
      below.slice(0,8).map(function(d){return d.bus;}).join(', ')+(below.length>8?' \u2026':'')+'. For each, use a plant no larger than its \u201cmax at target\u201d size, or add the condenser shown.'
      :'<b>All costed buses meet your target SCR of '+g(S.target)+'.</b> No condenser needed.';}
  data.forEach(function(d){var t=d.t;
    q('.k-scr',t).textContent=f(d.scr,2); q('.k-need',t).textContent=num(d.need); q('.k-cmva',t).textContent=num(d.cm);
    q('.k-after',t).textContent=f(d.cm>0?S.target:d.scr,2);
    q('.k-tc',t).innerHTML=d.meets?"<span class='meet'>\u2713 Meets</span>":"<span class='below'>Below target</span><br>Max at target: <b>"+
      Math.round(d.maxT).toLocaleString('en-US')+" MW</b><br>or condenser: <b>"+num(d.cm)+" MVA</b>";
    q('.k-cc',t).textContent=money(d.cc); var gcell=q('.k-gc',t); if(gcell) gcell.textContent=money(d.gc);
    q('.k-tot',t).innerHTML=money(d.tot)+(d.ok?'':' <span class="inc">(incomplete)</span>');
    var w=function(v){return (v&&mx?v/mx*100:0)+'%';};
    q('.seg-c',t).style.width=w(d.cc); q('.seg-g',t).style.width=w(d.gc); q('.seg-p',t).style.width=w(d.pc);});
  if(!resort) return;
  data.sort(function(a,b){if((a.tot===null)!==(b.tot===null)) return a.tot===null?1:-1;
    return (a.tot||0)-(b.tot||0)||a.cm-b.cm||b.scr-a.scr;});
  data.forEach(function(d,i){q('.k-rank',d.t).textContent=i+1; body.appendChild(d.t);});
}

// ---- inputs ----------------------------------------------------------------
var msg=q('#mw-msg'), bad={};
function showMsg(){var keys=Object.keys(bad); if(msg) msg.textContent=keys.length?bad[keys[keys.length-1]]:'';}
function mark(el,key,text){if(text){el.classList.add('bad');bad[key]=text;}else{el.classList.remove('bad');delete bad[key];} showMsg();}
function parse(el,allowEmpty,allowZero){var t=el.value.trim(); if(t===''&&allowEmpty) return {ok:true,v:null};
  var v=+t; return {ok:t!==''&&isFinite(v)&&(allowZero?v>=0:v>0), v:v};}

var range=q('#mw-range'), box=q('#mw-num');
if(range) range.addEventListener('input',function(){box.value=range.value;S.mw=+range.value;mark(box,'mw','');update();});
if(box) box.addEventListener('input',function(){var r=parse(box,false,false);
  if(!r.ok){mark(box,'mw','Enter a plant size above 0 MW \u2014 still showing '+num(S.mw)+' MW.');return;}
  mark(box,'mw','');S.mw=r.v;if(r.v<=+range.max) range.value=r.v;update();});

function bind(id,key,opts){var el=q('#'+id); if(!el) return;
  el.addEventListener('input',function(){var r=parse(el,opts.empty,opts.zero), m='';
    if(!r.ok) m=opts.msg; else if(opts.check) m=opts.check(r.v);
    if(m){mark(el,key,m);return;}
    mark(el,key,''); S[key]=r.v;
    if(key==='target') S.follow=false;
    if(key==='wk'&&C0&&S.follow){S.target=r.v;var te=q('#in-target'); if(te) te.value=r.v;}
    update();});}
bind('in-wk','wk',{msg:'Weak threshold must be a number above 0.',
  check:function(v){return v>S.vw?'':'Weak threshold must be above the very-weak threshold ('+g(S.vw)+').';}});
bind('in-vw','vw',{msg:'Very-weak threshold must be a number above 0.',
  check:function(v){return v<S.wk?'':'Very-weak threshold must be below the weak threshold ('+g(S.wk)+').';}});
bind('in-target','target',{msg:'Target SCR must be a number above 0.'});
bind('in-xd','xd',{msg:'Condenser X\u2033d must be a number above 0.'});
bind('in-xt','xt',{zero:true,msg:'Transformer Xt must be 0 or more.'});
bind('in-cpm','cpm',{zero:true,empty:true,msg:'Condenser cost must be 0 or more (or blank).'});
bind('in-gtc','gtc',{zero:true,empty:true,msg:'Gen-tie cost must be 0 or more (or blank).'});

var body=q('#cost-body');
if(body){
  body.addEventListener('input',function(e){var el=e.target, t=el.closest('tr');
    if(!el.classList||!(el.classList.contains('e-dist')||el.classList.contains('e-poi'))) return;
    var key=(el.classList.contains('e-dist')?'dist':'poi')+'|'+q('td:nth-child(2)',t).textContent;
    var r=parse(el,true,true);
    if(!r.ok){mark(el,key,'Distances and POI costs must be 0 or more (or blank).');return;}
    mark(el,key,''); t.dataset[el.classList.contains('e-dist')?'dist':'poi']=r.v===null?'':String(r.v);
    costUpdate(false);});
  body.addEventListener('change',function(e){if(e.target.classList&&(e.target.classList.contains('e-dist')||e.target.classList.contains('e-poi'))) costUpdate(true);});
}

var reset=q('#mw-reset');
if(reset) reset.addEventListener('click',function(){init();
  range.value=S.mw; box.value=S.mw;
  var setv=function(id,v){var e=q('#'+id); if(e){e.value=v===null||v===undefined?'':v;e.classList.remove('bad');}};
  setv('in-wk',S.wk); setv('in-vw',S.vw);
  if(C0){setv('in-target',S.target);setv('in-xd',S.xd);setv('in-xt',S.xt);setv('in-cpm',S.cpm);setv('in-gtc',S.gtc);}
  qa('#cost-body tr').forEach(function(t){t.dataset.dist=t.dataset.dist0;t.dataset.poi=t.dataset.poi0;
    var d=q('.e-dist',t),p=q('.e-poi',t); if(d){d.value=t.dataset.dist0;d.classList.remove('bad');}
    if(p){p.value=t.dataset.poi0;p.classList.remove('bad');}});
  box.classList.remove('bad'); bad={}; showMsg(); update();});
})();
"""


def render_html(result: ScreeningResult, title: str = "SCR-Screen report",
                notes: list[str] | None = None, network_svg: str | None = None,
                network_note: str | None = None, interactive: dict | None = None,
                cost: dict | None = None) -> str:
    """Return the full HTML report as a string.

    Args:
        network_svg / network_note: optional network map (netmap.render_network_svg).
        interactive: for bus scans, where every plant has the same rating:
            {"plant_mw": float, "compare": {plant_id: SCMVA by the other method} or None,
             "primary_label": str, "compare_label": str}.
            Adds the plant-size slider (V3) and, if "compare" is given, the
            method comparison chart (V4).
        cost: optional {"rows": list[CostRow], "inputs": CostInputs} from cost.screen_costs,
            shown as the interconnection cost screening section.
    """
    t = result.thresholds
    vw, wk = t["very_weak_below"], t["weak_below"]
    plants = sorted(result.plants, key=lambda p: p.scr, reverse=True)
    flagged = sum(p.flag != "none" for p in result.plants) + sum(g.flag != "none" for g in result.groups)
    lowest = min(result.plants, key=lambda p: p.scr) if result.plants else None
    basis = escape(result.basis)
    live = interactive is not None
    mw0 = float(interactive["plant_mw"]) if live else None
    TV = f"<span class='th-vw'>{vw:g}</span>" if live else f"{vw:g}"  # thresholds that update live
    TW = f"<span class='th-wk'>{wk:g}</span>" if live else f"{wk:g}"
    dscm = (lambda p: f" data-scmva='{p.scmva:.10g}'") if live else (lambda p: "")

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
    parts.append(_card("Plants screened" if not live else "Buses screened", str(len(result.plants))))
    if lowest:
        parts.append(_card("Lowest SCR", f"{lowest.scr:.2f}", FLAG_STYLE[lowest.flag][0],
                           escape(lowest.plant_id), vid="card-low"))
    if result.groups:
        g_low = min(result.groups, key=lambda g: g.wscr)
        parts.append(_card("Lowest group WSCR", f"{g_low.wscr:.2f}", FLAG_STYLE[g_low.flag][0],
                           escape(g_low.group)))
    total = len(result.plants) + len(result.groups)
    parts.append(_card("Flagged", f"{flagged} of {total}", "wk" if flagged else "ok", vid="card-flag"))
    parts.append("</div>")

    # --- What-if inputs: plant size slider (V3), thresholds, cost rates --------
    if live:
        top = max(100.0, _nice_ceiling(3 * mw0))
        step = 10 if top <= 5000 else 50
        ci = cost["inputs"] if cost else None

        def fld(fid, label, value, unit, mn="0", note=""):
            v = _plain(value)
            return (f"<label class='fld' for='{fid}'>{label}<input id='{fid}' type='number' min='{mn}' "
                    f"step='any' value='{v}'{note}>{unit}</label>")

        panel = [
            "<div class='slider whatif'><div class='wrow'><label for='mw-range'>Plant size</label>",
            f"<input id='mw-range' type='range' min='{step}' max='{_plain(top)}' step='{step}' value='{_plain(mw0)}'>",
            f"<input id='mw-num' type='number' min='1' step='any' value='{_plain(mw0)}' aria-label='Plant size in MW'> MW",
            "<button id='mw-reset' type='button'>Reset all</button>",
            "<span id='mw-msg' class='msg' role='status' aria-live='polite'></span></div>",
            "<div class='wrow'><div class='wh'>Flag thresholds (SCR)</div>",
            fld("in-wk", "Weak below", wk, ""),
            fld("in-vw", "Very weak below", vw, ""),
            "</div>",
        ]
        if ci:
            panel += [
                "<div class='wrow'><div class='wh'>Cost screening</div>",
                fld("in-target", "Target SCR", ci.target_scr, ""),
                fld("in-xd", "Condenser X″d", ci.condenser_xdss_pu, " pu"),
                fld("in-xt", "Transformer Xt", ci.condenser_xt_pu, " pu"),
                fld("in-cpm", "Condenser", ci.condenser_cost_per_mva, " $/MVA"),
                fld("in-gtc", "Gen-tie", ci.gen_tie_cost_per_mile, " $/mile"),
                "</div>",
            ]
        panel.append(
            "<div class='hint'>Change any value to recalculate instantly in your browser"
            + (" (per-bus distances and POI costs are editable in the cost table)" if ci else "")
            + ". SCR = SCMVA ÷ plant MW; short-circuit MVA does not change with these inputs. "
            f"Files exported with --out keep the values the report was created with ({mw0:g} MW).</div></div>")
        parts.append("".join(panel))

    # --- Network map (V1) ----------------------------------------------------
    if network_svg or network_note:
        parts.append("<h2>Network map</h2>")
        if network_svg:
            parts.append(f"<div class='mapwrap'>{network_svg}</div>")
            parts.append(
                "<div class='legend'>"
                f"<span><span class='sw' style='background:var(--vw)'></span>Very weak: below {TV}</span>"
                f"<span><span class='sw' style='background:var(--wk)'></span>Weak: {TV} to below {TW}</span>"
                f"<span><span class='sw' style='background:var(--ok)'></span>No flag: {TW} or above</span>"
                "<span><span class='sw' style='background:var(--muted);border-radius:2px'></span>"
                "Square = generator or grid source bus</span>"
                "<span>Dashed line = transformer</span><span>Pulsing ring and label = weakest flagged buses (up to 8)</span>"
                "<span>Hover over a bus for details</span></div>"
            )
        if network_note:
            parts.append(f"<div class='note'>{escape(network_note)}</div>")

    # --- SCR bar chart -------------------------------------------------------
    shown, cap_note = _limit(plants)
    heading = "SCR by bus" if live else "SCR by plant"
    if live:
        heading += " for a <span data-mw-text>" + f"{mw0:,.1f}".rstrip("0").rstrip(".") + "</span> MW plant"
    parts.append(f"<h2>{heading}</h2><div class='chart scr-chart'>")
    scale = max([p.scr for p in shown] + [wk * 1.5])
    for i, p in enumerate(shown):
        cls, label = FLAG_STYLE[p.flag]
        width = max(p.scr / scale * 100, 0.8)
        tick_label = (i == 0)
        ticks = "".join(
            f"<div class='tick' data-kind='{kind}' data-th='{th:g}' style='left:{th / scale * 100:.2f}%'>"
            f"{f'<span>{th:g}</span>' if tick_label else ''}</div>" for kind, th in (("vw", vw), ("wk", wk)))
        parts.append(
            f"<div class='row'{dscm(p)}><div class='name' title='{escape(p.plant_id)}'>{escape(p.plant_id)}</div>"
            f"<div class='track'><div class='bar {cls}' style='width:{width:.2f}%;animation-delay:{min(i * 20, 600)}ms'>"
            f"</div>{ticks}</div>"
            f"<div><span class='val'>{p.scr:.2f}</span><span class='pill {cls}'>{label}</span></div></div>"
        )
    parts.append("</div>")
    if cap_note:
        parts.append(f"<div class='note'>{cap_note}</div>")
    parts.append(
        "<div class='legend'>"
        f"<span><span class='sw' style='background:var(--vw)'></span>Very weak: below {TV}</span>"
        f"<span><span class='sw' style='background:var(--wk)'></span>Weak: {TV} to below {TW}</span>"
        f"<span><span class='sw' style='background:var(--ok)'></span>No flag: {TW} or above</span>"
        "<span>Dashed lines mark the thresholds</span></div>"
    )

    # --- Method comparison (V4) ----------------------------------------------
    compare = (interactive or {}).get("compare")
    if live and compare:
        parts.append(_comparison(shown, compare, interactive, vw, wk, mw0))

    # --- Largest plant before a weak flag (V2) -------------------------------
    cap_rows = sorted(result.plants, key=lambda p: p.max_rating_no_flag, reverse=True)
    cap_shown, cap_rows_note = _limit(cap_rows)
    cap_scale = max(p.max_rating_no_flag for p in cap_shown) if cap_shown else 1.0
    parts.append(f"<h2>Largest plant before a weak flag</h2>"
                 f"<div class='note' style='margin-top:-4px;margin-bottom:8px'>Largest plant rating "
                 f"({basis}) each location could host while keeping SCR at or above {TW}: "
                 f"SCMVA ÷ {TW}. Single-plant screening only; nearby plants share this strength."
                 "</div><div class='chart'>")
    for i, p in enumerate(cap_shown):
        width = max(p.max_rating_no_flag / cap_scale * 100, 0.8)
        parts.append(
            f"<div class='row cap-row'{dscm(p)}><div class='name' title='{escape(p.plant_id)}'>{escape(p.plant_id)}</div>"
            f"<div class='track'><div class='bar cap' style='width:{width:.2f}%;animation-delay:{min(i * 20, 600)}ms'>"
            f"</div></div><div><span class='val'>{p.max_rating_no_flag:,.0f} {basis}</span></div></div>"
        )
    parts.append("</div>")
    if cap_rows_note:
        parts.append(f"<div class='note'>{cap_rows_note}</div>")

    # --- Interconnection cost screening ----------------------------------------
    if cost:
        parts.append(_cost_section(cost, live))

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
                 f"<th>{'Bus' if live else 'Plant'}</th><th>POI</th><th>Group</th><th class='n'>SCMVA</th>"
                 f"<th class='n'>Rating ({basis})</th><th class='n'>SCR</th><th>Flag</th>"
                 "<th class='n'>Max size, no flag</th></tr></thead><tbody>")
    for p in plants:
        cls, label = FLAG_STYLE[p.flag]
        parts.append(f"<tr class='res'{dscm(p)}><td>{escape(p.plant_id)}</td><td>{escape(p.poi_name)}</td>"
                     f"<td>{escape(p.group or '')}</td><td class='n'>{p.scmva:,.1f}</td>"
                     f"<td class='n c-rating'>{p.rating:,.1f}</td><td class='n c-scr'>{p.scr:.3f}</td>"
                     f"<td><span class='pill {cls}'>{label}</span></td>"
                     f"<td class='n c-max'>{p.max_rating_no_flag:,.1f}</td></tr>")
    parts.append("</tbody></table></div>")
    if result.groups:
        parts.append("<div class='tablewrap' style='margin-top:14px'><table><thead><tr>"
                     f"<th>Group</th><th>Plants</th><th class='n'>Total rating ({basis})</th><th class='n'>WSCR</th>"
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
        f"Flag bands: below {TV} very weak; {TV} to below {TW} weak; {TW} or above no "
        "flag. Default bands follow HVDC planning practice (IEEE Std 1204-1997); user-configurable.",
    ] + [escape(n) for n in (notes or [])]
    parts.append("<h2>Method and assumptions</h2><div class='box'><ul>")
    parts.extend(f"<li>{i}</li>" for i in items)
    parts.append("</ul></div>")
    parts.append(f"<div class='disc'><strong>Screening only.</strong> {DISCLAIMER}</div>")
    parts.append("<footer>References: NERC Reliability Guideline, Integrating Inverter-Based "
                 "Resources into Low Short Circuit Strength Systems (2017); NERC White Paper, "
                 "Short-Circuit Modeling and System Strength (2018).</footer>")
    if live:
        cfg = {"vw": vw, "wk": wk, "mw": mw0, "maxLabels": 8}
        if cost:
            ci = cost["inputs"]
            cfg["cost"] = {"target": ci.target_scr, "xd": ci.condenser_xdss_pu, "xt": ci.condenser_xt_pu,
                           "cpm": ci.condenser_cost_per_mva, "gtc": ci.gen_tie_cost_per_mile,
                           "follow": cost.get("target_follows_weak", False)}
        parts.append(f"<script type='application/json' id='scr-cfg'>{json.dumps(cfg)}</script>")
        parts.append(f"<script>{SCRIPT}</script>")
    parts.append("</div></body></html>")
    return "".join(parts)


def write_html_report(result: ScreeningResult, path: str | Path,
                      title: str = "SCR-Screen report", notes: list[str] | None = None,
                      network_svg: str | None = None, network_note: str | None = None,
                      interactive: dict | None = None, cost: dict | None = None) -> Path:
    """Write the HTML report to a file and return its path."""
    path = Path(path)
    path.write_text(render_html(result, title=title, notes=notes, network_svg=network_svg,
                                network_note=network_note, interactive=interactive, cost=cost),
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------------------

def _comparison(shown, compare, interactive, vw, wk, mw0) -> str:
    """V4: both short-circuit methods per bus; rows where the flag differs are highlighted."""
    a_lab = escape(interactive.get("primary_label", "Primary method"))
    b_lab = escape(interactive.get("compare_label", "Other method"))
    rows = [p for p in shown if p.plant_id in compare]
    scale = max([wk * 1.5] + [p.scmva / mw0 for p in rows] + [compare[p.plant_id] / mw0 for p in rows])
    out, diff = [], 0
    for i, p in enumerate(rows):
        a, b = p.scmva / mw0, compare[p.plant_id] / mw0
        ca, cb = _cls(a, vw, wk), _cls(b, vw, wk)
        diff += ca != cb
        pa, pb = a / scale * 100, b / scale * 100
        ticks = "".join(f"<div class='tick cmp-tick' data-kind='{kind}' data-th='{th:g}' "
                        f"style='left:{th / scale * 100:.2f}%'>"
                        f"{f'<span>{th:g}</span>' if i == 0 else ''}</div>" for kind, th in (("vw", vw), ("wk", wk)))
        out.append(
            f"<div class='row{' diff' if ca != cb else ''}' data-scmva='{p.scmva:.10g}' "
            f"data-scmva2='{compare[p.plant_id]:.10g}'>"
            f"<div class='name' title='{escape(p.plant_id)}'>{escape(p.plant_id)}</div>"
            f"<div class='track'>{ticks}<div class='seg' style='left:{min(pa, pb):.2f}%;width:{abs(pb - pa):.2f}%'></div>"
            f"<div class='dot a {ca}' style='left:{pa:.2f}%' title='{a_lab}'></div>"
            f"<div class='dot b {cb}' style='left:{pb:.2f}%' title='{b_lab}'></div></div>"
            f"<div><span class='val'>{a:.2f} / {b:.2f}</span></div></div>"
        )
    head = (f"<h2>Method comparison: {a_lab} vs {b_lab}</h2>"
            f"<div class='note' style='margin-top:-4px;margin-bottom:8px'>Filled dot = {a_lab}; "
            f"ring = {b_lab}. Highlighted rows: the two methods give a different flag "
            f"(<strong id='cmp-diff'>{diff}</strong> bus(es) at this plant size). Values shown as "
            f"{a_lab} / {b_lab}.</div><div class='chart cmp'>")
    return head + "".join(out) + "</div>"


def _plain(v) -> str:
    """Number as plain digits for input boxes and data attributes (never 2e+06)."""
    if v is None:
        return ""
    v = float(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.10f}".rstrip("0").rstrip(".")


def _money(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.1f}M"
    if a >= 1e3:
        return f"${v / 1e3:.0f}k"
    return f"${v:.0f}"


def _target_check(r) -> str:
    if r.meets_target:
        return "<span class='meet'>✓ Meets</span>"
    return (f"<span class='below'>Below target</span><br>Max at target: <b>{r.max_at_target_mw:,.0f} MW</b>"
            f"<br>or condenser: <b>{r.condenser_mva:,.1f} MVA</b>")


def _cost_section(cost, live) -> str:
    from .cost import LIMITATIONS

    rows, ci = cost["rows"], cost["inputs"]
    mx = max([r.total_cost for r in rows if r.total_cost is not None] + [0.0])
    mw_txt = f"{ci.plant_mw:,.1f}".rstrip("0").rstrip(".")
    mw_html = f"<span data-mw-text>{mw_txt}</span>" if live else mw_txt
    priced = ci.condenser_cost_per_mva is not None or ci.gen_tie_cost_per_mile is not None or any(
        s.poi_cost is not None for s in ci.sites.values())
    out = [
        "<h2>Interconnection cost screening</h2>",
        "<div class='inputs'>",
        f"<span>Plant: <b>{mw_html} MW</b></span>",
        f"<span>Target SCR: <b id='ci-target'>{ci.target_scr:g}</b></span>",
        f"<span>Condenser X″d + Xt: <b id='ci-x'>{ci.condenser_xdss_pu:g} + {ci.condenser_xt_pu:g} pu</b></span>",
        "<span>Condenser cost: <b id='ci-cpm'>" + (f"{_money(ci.condenser_cost_per_mva)}/MVA"
                                                   if ci.condenser_cost_per_mva is not None else "not entered")
        + "</b></span>",
        "<span>Gen-tie cost: <b id='ci-gtc'>" + (f"{_money(ci.gen_tie_cost_per_mile)}/mile"
                                                 if ci.gen_tie_cost_per_mile is not None else "not entered")
        + "</b></span>",
        "<span>Buses costed: <b>" + (f"{len(rows)} candidate(s) from the site file" if ci.sites
                                       else f"all {len(rows)} (condenser mitigation only)") + "</b></span>",
        "</div>",
    ]
    if not priced:
        out.append("<div class='note' style='margin-bottom:8px'>No cost rates entered, so only the "
                   "condenser size needed is shown. Enter rates "
                   + ("in the inputs above" if live else "with --condenser-cost-per-mva and "
                      "--gen-tie-cost-per-mile") + " and per-bus costs to rank buses by cost.</div>")
    below = [r for r in rows if not r.meets_target]
    if below:
        names = ", ".join(escape(r.bus_id) for r in below[:8]) + (" …" if len(below) > 8 else "")
        alert = (f"<b>{len(below)} of {len(rows)} bus(es) are below your target SCR of {ci.target_scr:g}:</b> {names}. "
                 "For each, use a plant no larger than its “max at target” size, or add the condenser shown.")
    else:
        alert = f"<b>All costed buses meet your target SCR of {ci.target_scr:g}.</b> No condenser needed."
    out.append(f"<div id='cost-alert' class='calert{'' if below else ' good'}' role='status' aria-live='polite'>{alert}</div>")
    out.append("<div class='legend' style='margin:0 0 8px'>"
               "<span><span class='sw seg-c'></span>Synchronous condenser</span>"
               "<span><span class='sw seg-g'></span>Gen-tie line</span>"
               "<span><span class='sw seg-p'></span>POI substation</span></div>")
    out.append("<div class='tablewrap'><table class='cost'><thead><tr><th class='n'>#</th><th>Bus</th>"
               "<th class='n'>SCR</th><th>Target check</th><th class='n'>Added SCMVA needed</th><th class='n'>Condenser MVA</th>"
               "<th class='n'>SCR after condenser</th>"
               "<th class='n'>Condenser cost</th><th class='n'>Gen-tie (mi)</th><th class='n'>Gen-tie cost</th>"
               "<th class='n'>POI cost ($)</th><th class='n'>Total</th><th>Breakdown</th></tr></thead>"
               "<tbody id='cost-body'>")
    for i, r in enumerate(rows, start=1):
        w = (lambda v: f"{(v / mx * 100) if (v and mx) else 0:.2f}%")
        inc = "" if r.complete else " <span class='inc'>(incomplete)</span>"
        dist = _plain(r.gen_tie_mi)
        poi = _plain(r.poi_cost)
        bus = escape(r.bus_id)
        if live:
            dist_cell = (f"<input class='e-dist' type='number' min='0' step='any' value='{dist}' "
                         f"aria-label='Gen-tie distance in miles, {bus}'>")
            poi_cell = (f"<input class='e-poi' type='number' min='0' step='any' value='{poi}' "
                        f"aria-label='POI substation cost in dollars, {bus}'>")
        else:
            dist_cell = "—" if r.gen_tie_mi is None else f"{r.gen_tie_mi:g}"
            poi_cell = _money(r.poi_cost)
        out.append(
            f"<tr data-scmva='{r.scmva:.10g}' data-dist='{dist}' data-poi='{poi}' "
            f"data-dist0='{dist}' data-poi0='{poi}'>"
            f"<td class='n k-rank'>{i}</td><td>{bus}</td>"
            f"<td class='n k-scr'>{r.scr:.2f}</td><td class='k-tc'>{_target_check(r)}</td>"
            f"<td class='n k-need'>{r.added_scmva_needed:,.1f}</td>"
            f"<td class='n k-cmva'>{r.condenser_mva:,.1f}</td><td class='n k-after'>{r.scr_after:.2f}</td>"
            f"<td class='n k-cc'>{_money(r.condenser_cost)}</td>"
            f"<td class='n'>{dist_cell}</td>"
            f"<td class='n k-gc'>{_money(r.gen_tie_cost)}</td><td class='n'>{poi_cell}</td>"
            f"<td class='n k-tot'>{_money(r.total_cost)}{inc}</td>"
            f"<td><div class='mini'><span class='seg-c' style='width:{w(r.condenser_cost)}'></span>"
            f"<span class='seg-g' style='width:{w(r.gen_tie_cost)}'></span>"
            f"<span class='seg-p' style='width:{w(r.poi_cost)}'></span></div></td></tr>"
        )
    out.append("</tbody></table></div>")
    out.append("<div class='note'>Condenser MVA = max(0, plant MW × target SCR − SCMVA) × (X″d + Xt). "
               "\"Incomplete\" means a needed part has a quantity but no price entered. "
               + escape(LIMITATIONS) + "</div>")
    return "".join(out)


def _cls(v, vw, wk):
    return "vw" if v < vw else ("wk" if v < wk else "ok")


def _limit(rows):
    """Keep charts readable: show at most MAX_CHART_ROWS, keeping the weakest."""
    if len(rows) <= MAX_CHART_ROWS:
        return rows, ""
    return (rows[-MAX_CHART_ROWS:],
            f"Chart shows the {MAX_CHART_ROWS} weakest of {len(rows)}; the table below lists all.")


def _nice_ceiling(x: float) -> float:
    for step in (100, 500, 1000, 5000):
        if x <= step * 20:
            return float(-(-x // step) * step)
    return float(-(-x // 10000) * 10000)


def _card(key: str, value: str, cls: str = "", sub: str = "", vid: str = "") -> str:
    sub_html = f"<div class='sub'>{sub}</div>" if sub else ""
    id_attr = f" id='{vid}'" if vid else ""
    return (f"<div class='card'><div class='k'>{key}</div>"
            f"<div class='v {cls}'{id_attr}>{value}</div>{sub_html}</div>")
