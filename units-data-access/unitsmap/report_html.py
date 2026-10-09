"""A single self-contained HTML page for exploring the catalog in any browser, offline."""

from __future__ import annotations

import datetime as _dt
import html
import json
from pathlib import Path

from . import __version__
from .catalog import Catalog


def payload(cat: Catalog) -> dict:
    dws = []
    for dw in cat.datawindows:
        dws.append({
            "n": dw.name, "f": Path(dw.library).name, "form": dw.form, "cm": dw.comment,
            "t": dw.tables, "a": [a for a, _ in dw.arguments], "sql": dw.sql_text or dw.sql,
            "raw": dw.sql if dw.sql != dw.sql_text else "", "enc": dw.sql_encrypted,
            "lab": dw.labels[:60], "ref": dw.references, "w": dw.warnings,
            "cp": [list(c) for c in dw.computes],
            "c": [[c.name, c.dbname, c.label, {True: 1, False: 0, None: -1}[c.shown], c.dddw,
                   c.dddw_display, c.dddw_data, c.type] for c in dw.columns],
        })
    tables = [{"n": v["name"], "c": sorted(v["columns"], key=str.lower), "d": v["datawindows"]}
              for v in cat.tables().values()]
    edges = [{"a": e.a, "b": e.b, "p": [list(p) for p in e.pairs], "k": e.count, "x": e.examples}
             for e in cat.edges().values()]
    return {"dws": dws, "tables": tables, "edges": edges,
            "files": [s.get("path") for s in cat.sources], "errors": cat.errors,
            "generated": _dt.datetime.now().strftime("%d %b %Y %H:%M"), "version": __version__}


def render(cat: Catalog, title: str = "Units data map") -> str:
    data = json.dumps(payload(cat), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", data)


def write(cat: Catalog, path: str | Path, title: str = "Units data map") -> None:
    Path(path).write_text(render(cat, title), encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1b1d21;--muted:#5d6470;--line:#e2e2de;--accent:#1f5fa8;--accent-ink:#fff;
--chip:#eef2f8;--warn:#9a3b00;--warn-bg:#fff1e6;--ok:#246b3a;--code:#f1f1ee;--hl:#fff3a3}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171b;--panel:#1d2025;--ink:#e8e9ec;--muted:#a1a7b1;
--line:#2e323a;--accent:#7fb0ff;--accent-ink:#0d1117;--chip:#262b33;--warn:#ffb27a;--warn-bg:#3a2617;--ok:#7fd69a;--code:#24272d;--hl:#5a4f12}}
:root[data-theme=dark]{--bg:#15171b;--panel:#1d2025;--ink:#e8e9ec;--muted:#a1a7b1;--line:#2e323a;--accent:#7fb0ff;--accent-ink:#0d1117;
--chip:#262b33;--warn:#ffb27a;--warn-bg:#3a2617;--ok:#7fd69a;--code:#24272d;--hl:#5a4f12}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:20px 16px 8px;max-width:1200px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);font-size:13px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 4px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px;min-width:110px}
.stat b{display:block;font-size:20px}.stat span{color:var(--muted);font-size:12px}
nav{max-width:1200px;margin:0 auto;padding:0 16px;display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--line)}
nav button{background:none;border:0;border-bottom:3px solid transparent;padding:10px 12px;font:inherit;color:var(--muted);cursor:pointer}
nav button.on{color:var(--ink);border-color:var(--accent);font-weight:600}
main{max-width:1200px;margin:0 auto;padding:16px}
.panel{display:none}.panel.on{display:block}
input[type=search],input[type=text]{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--ink);font:inherit}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}
label.opt{color:var(--muted);font-size:13px;display:flex;gap:6px;align-items:center}
.hint{color:var(--muted);font-size:13px;margin:6px 0 12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0}
.card h3{margin:0;font-size:16px;cursor:pointer;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;word-break:break-word}
.card h3 small{color:var(--muted);font-weight:400;font-size:12px}
.why{color:var(--muted);font-size:13px;margin:4px 0 0;padding-left:16px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:12px;cursor:pointer;border:0;color:var(--ink);font-family:inherit}
.tag{font-size:11px;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--muted)}
.tag.hidden{background:var(--warn-bg);color:var(--warn);font-weight:600}
.tag.enc{background:var(--warn-bg);color:var(--warn)}
.detail{margin-top:10px;display:none}.card.open .detail{display:block}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--code);position:sticky;top:0;font-weight:600}
tr:last-child td{border-bottom:0}
pre{background:var(--code);border-radius:8px;padding:10px 12px;overflow-x:auto;font:12.5px/1.45 ui-monospace,Consolas,monospace;white-space:pre;margin:6px 0}
.btn{background:var(--accent);color:var(--accent-ink);border:0;border-radius:8px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
.btn.ghost{background:var(--chip);color:var(--ink)}
mark{background:var(--hl);color:inherit;border-radius:2px}
.muted{color:var(--muted)}.warn{color:var(--warn)}
.empty{color:var(--muted);padding:30px 0;text-align:center}
.picked{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.picked .chip{background:var(--accent);color:var(--accent-ink)}
textarea{width:100%;min-height:220px;font:12.5px/1.45 ui-monospace,Consolas,monospace;background:var(--code);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:10px}
.theme{float:right;background:var(--chip);border:0;border-radius:8px;padding:6px 10px;color:var(--ink);cursor:pointer;font:inherit;font-size:12px}
.more{margin:12px 0;text-align:center}
@media (max-width:600px){.stat{min-width:calc(50% - 4px)}header{padding-top:14px}}
</style>
</head>
<body>
<header>
  <button class="theme" id="theme" title="Switch light/dark">◐ Theme</button>
  <h1>__TITLE__</h1>
  <div class="sub" id="sub"></div>
  <div class="stats" id="stats"></div>
</header>
<nav id="tabs">
  <button data-p="search" class="on">Find a field</button>
  <button data-p="columns">All columns</button>
  <button data-p="tables">Tables</button>
  <button data-p="join">Join builder</button>
  <button data-p="files">Files read</button>
</nav>
<main>
  <section class="panel on" id="p-search">
    <input type="search" id="q" placeholder="What are you looking for? e.g.  sold by   ·   salesperson   ·   vin   ·   odometer" autofocus>
    <div class="hint">Every word must match. Searches screen labels, column names, database names, tables, comments and SQL. Click a result to see its columns and SQL.</div>
    <div id="results"></div>
  </section>
  <section class="panel" id="p-columns">
    <input type="search" id="cq" placeholder="Filter columns by name, label, table or database name">
    <div class="row"><label class="opt"><input type="checkbox" id="onlyHidden"> Only columns that are fetched but hidden on screen</label></div>
    <div class="tablewrap"><table><thead><tr><th>DataWindow</th><th>Column</th><th>Database name</th><th>Screen label</th><th>On screen</th><th>Lookup</th></tr></thead><tbody id="ctable"></tbody></table></div>
    <div class="more" id="cmore"></div>
  </section>
  <section class="panel" id="p-tables">
    <input type="search" id="tq" placeholder="Filter tables or columns">
    <div id="tlist"></div>
  </section>
  <section class="panel" id="p-join">
    <div class="hint">Pick the tables you need. The builder links them using joins that Units itself uses, then writes the SQL. First table picked is the starting point.</div>
    <div class="row"><input type="text" id="jt" list="tablenames" placeholder="Type a table name and press Enter" style="flex:1;min-width:220px"><button class="btn" id="jadd">Add</button><button class="btn ghost" id="jclear">Clear</button></div>
    <datalist id="tablenames"></datalist>
    <div class="picked" id="jpicked"></div>
    <textarea id="jsql" spellcheck="false" placeholder="SQL appears here"></textarea>
    <div class="row"><button class="btn" id="jcopy">Copy SQL</button><span class="muted" id="jnote"></span></div>
  </section>
  <section class="panel" id="p-files"><div id="flist"></div></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s==null?'':s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mark = (s, terms) => { let h = esc(s); for (const t of terms) { if (!t) continue; const re = new RegExp('(' + t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + ')', 'ig'); h = h.replace(re, '<mark>$1</mark>'); } return h; };
const low = s => String(s||'').toLowerCase();
const byName = {}; D.dws.forEach(d => byName[low(d.n)] = d);

// theme
try { const t = localStorage.getItem('unitsmap-theme'); if (t) document.documentElement.dataset.theme = t; } catch(e) {}
$('#theme').onclick = () => { const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark':'light');
  const nx = cur === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = nx; try { localStorage.setItem('unitsmap-theme', nx); } catch(e) {} };

// header
const nCols = D.dws.reduce((a,d)=>a+d.c.length,0), nHidden = D.dws.reduce((a,d)=>a+d.c.filter(c=>c[3]===0).length,0);
$('#sub').textContent = 'Generated ' + D.generated + ' from ' + D.files.length + ' file(s) · unitsmap ' + D.version + ' · read-only map, no database connection';
$('#stats').innerHTML = [[D.dws.length,'screens / reports (DataWindows)'],[D.tables.length,'tables'],[nCols,'columns'],[nHidden,'hidden on screen'],[D.edges.length,'known joins']]
  .map(([n,l]) => '<div class="stat"><b>'+n.toLocaleString()+'</b><span>'+l+'</span></div>').join('');

// tabs
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => show(b.dataset.p));
function show(p){ document.querySelectorAll('#tabs button').forEach(x=>x.classList.toggle('on', x.dataset.p===p));
  document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('on', x.id==='p-'+p));
  if (p==='columns') renderCols(); if (p==='tables') renderTables(); if (p==='files') renderFiles(); }

// search
function scoreDw(d, t){ let s=0, why=[];
  if (low(d.n).includes(t)) { s+=6; why.push('name'); }
  for (const c of d.c) { const hit = low(c[0]).includes(t)||low(c[1]).includes(t)||low(c[2]).includes(t);
    if (hit) { s+=5; why.push('column <b>'+esc(c[0])+'</b>'+(c[1]?' = '+esc(c[1]):'')+(c[2]?' “'+esc(c[2])+'”':'')+(c[3]===0?' <span class="tag hidden">hidden on screen</span>':'')); } }
  if (d.lab.some(x=>low(x).includes(t))) { s+=3; why.push('screen text'); }
  if (d.t.some(x=>low(x).includes(t))) { s+=3; why.push('table'); }
  if (low(d.cm).includes(t)) { s+=2; why.push('comment'); }
  if (!s && low(d.sql).includes(t)) { s+=1; why.push('in SQL'); }
  return [s, why]; }
let lastHits = [], shown = 0;
function search(){ const terms = low($('#q').value).split(/\s+/).filter(Boolean); const out = $('#results');
  if (!terms.length) { out.innerHTML = '<div class="empty">Type a word above. Try the label you see on screen, like <b>sold</b>, <b>sales</b>, <b>vin</b> or <b>odometer</b>.</div>'; return; }
  lastHits = []; for (const d of D.dws) { let tot=0, why=[], ok=true; for (const t of terms) { const [s,w]=scoreDw(d,t); if(!s){ok=false;break;} tot+=s; why=why.concat(w);} if(ok) lastHits.push([tot,d,[...new Set(why)]]); }
  lastHits.sort((a,b)=>b[0]-a[0]||a[1].n.localeCompare(b[1].n)); shown = 0; out.innerHTML = '';
  if (!lastHits.length) { out.innerHTML = '<div class="empty">Nothing matches every word. Try fewer or shorter words.</div>'; return; }
  more(terms); }
function more(terms){ const out = $('#results'); const old = out.querySelector('.more'); if (old) old.remove();
  const next = lastHits.slice(shown, shown+50); shown += next.length;
  out.insertAdjacentHTML('beforeend', next.map(([s,d,why]) => card(d, terms, why)).join(''));
  if (shown < lastHits.length) { out.insertAdjacentHTML('beforeend', '<div class="more"><button class="btn ghost">Show more ('+(lastHits.length-shown)+' left)</button></div>'); out.querySelector('.more button').onclick=()=>more(terms); }
  wire(out); }
function card(d, terms, why){ terms = terms||[]; const hidden = d.c.filter(c=>c[3]===0).length;
  return '<div class="card" data-n="'+esc(d.n)+'"><h3>'+mark(d.n,terms)+' <small>'+esc(d.f)+' · '+d.c.length+' columns'+(hidden?' · <span class="tag hidden">'+hidden+' hidden</span>':'')+(d.enc?' · <span class="tag enc">SQL encrypted</span>':'')+'</small></h3>'+
    (d.cm?'<div class="muted">'+mark(d.cm,terms)+'</div>':'')+
    '<div class="chips">'+d.t.map(t=>'<button class="chip" data-table="'+esc(t)+'">'+mark(t,terms)+'</button>').join('')+'</div>'+
    (why&&why.length?'<ul class="why">'+why.slice(0,6).map(w=>'<li>'+w+'</li>').join('')+'</ul>':'')+
    '<div class="detail"></div></div>'; }
function detail(d){ const rows = d.c.map(c=>'<tr><td>'+esc(c[0])+'</td><td>'+esc(c[1])+'</td><td>'+esc(c[2])+'</td><td>'+(c[3]===1?'yes':c[3]===0?'<span class="tag hidden">HIDDEN</span>':'<span class="muted">?</span>')+'</td><td>'+(c[4]?'<button class="chip" data-dw="'+esc(c[4])+'">'+esc(c[4])+'</button>'+(c[5]?' shows '+esc(c[5]):''):'')+'</td><td>'+esc(c[7])+'</td></tr>').join('');
  let h = '<div class="tablewrap"><table><thead><tr><th>Column</th><th>Database name</th><th>Screen label</th><th>On screen</th><th>Lookup</th><th>Type</th></tr></thead><tbody>'+(rows||'<tr><td colspan=6 class="muted">No columns recovered</td></tr>')+'</tbody></table></div>';
  if (d.cp.length) h += '<p class="muted">Computed fields: '+d.cp.map(c=>'<b>'+esc(c[0])+'</b> = '+esc(c[1])).join(' · ')+'</p>';
  if (d.a.length) h += '<p>Inputs (replace before running): '+d.a.map(a=>'<code>:'+esc(a)+'</code>').join(', ')+'</p>';
  if (d.sql) h += '<div class="row"><b>SQL</b><button class="btn" data-copy>Copy SQL</button></div><pre>'+esc(d.sql)+'</pre>';
  else if (d.enc) h += '<p class="warn">The SQL inside this compiled DataWindow is encrypted. The columns above are still accurate; build a query from them with the Join builder.</p>';
  if (d.raw) h += '<details><summary class="muted">As stored by Units (PowerBuilder notation)</summary><pre>'+esc(d.raw)+'</pre></details>';
  if (d.ref.length) h += '<p>Uses: '+d.ref.map(r=>'<button class="chip" data-dw="'+esc(r)+'">'+esc(r)+'</button>').join(' ')+'</p>';
  if (d.w.length) h += '<p class="warn">'+d.w.map(esc).join('<br>')+'</p>';
  return h; }
function wire(root){
  root.querySelectorAll('.card h3').forEach(h=>{ if(h._w) return; h._w=1; h.onclick=()=>{ const c=h.parentElement; const d=byName[low(c.dataset.n)];
    const det=c.querySelector('.detail'); if(!det.innerHTML) { det.innerHTML=detail(d); wire(det); } c.classList.toggle('open'); }; });
  root.querySelectorAll('[data-copy]').forEach(b=>{ if(b._w) return; b._w=1; b.onclick=()=>copy(b.parentElement.nextElementSibling.textContent, b); });
  root.querySelectorAll('[data-dw]').forEach(b=>{ if(b._w) return; b._w=1; b.onclick=e=>{ e.stopPropagation(); $('#q').value=b.dataset.dw; show('search'); search(); const c=$('#results .card'); if(c) c.querySelector('h3').click(); }; });
  root.querySelectorAll('[data-table]').forEach(b=>{ if(b._w) return; b._w=1; b.onclick=e=>{ e.stopPropagation(); $('#tq').value=b.dataset.table; show('tables'); }; });
}
function copy(text, btn){ const done=()=>{ const o=btn.textContent; btn.textContent='Copied ✓'; setTimeout(()=>btn.textContent=o,1500); };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, ()=>fallback(text,done)); else fallback(text,done); }
function fallback(text, done){ const t=document.createElement('textarea'); t.value=text; document.body.appendChild(t); t.select(); try{document.execCommand('copy');}catch(e){} t.remove(); done(); }
let timer; $('#q').addEventListener('input', ()=>{ clearTimeout(timer); timer=setTimeout(search,150); }); search();

// all columns
let allCols = null, cShown = 0, cRows = [];
function renderCols(reset=true){ if(!allCols){ allCols=[]; for(const d of D.dws) for(const c of d.c) allCols.push([d.n,c]); }
  const t = low($('#cq').value), oh = $('#onlyHidden').checked; const body = $('#ctable');
  if (reset) { cRows = allCols.filter(([n,c])=>(!oh||c[3]===0)&&(!t||low(n).includes(t)||low(c[0]).includes(t)||low(c[1]).includes(t)||low(c[2]).includes(t))); cShown=0; body.innerHTML=''; }
  const next = cRows.slice(cShown, cShown+300); cShown += next.length;
  body.insertAdjacentHTML('beforeend', next.map(([n,c])=>'<tr><td><button class="chip" data-dw="'+esc(n)+'">'+esc(n)+'</button></td><td>'+esc(c[0])+'</td><td>'+esc(c[1])+'</td><td>'+esc(c[2])+'</td><td>'+(c[3]===1?'yes':c[3]===0?'<span class="tag hidden">HIDDEN</span>':'<span class="muted">?</span>')+'</td><td>'+esc(c[4])+'</td></tr>').join(''));
  $('#cmore').innerHTML = cShown < cRows.length ? '<button class="btn ghost">Show more ('+(cRows.length-cShown)+' left)</button>' : (cRows.length? '<span class="muted">'+cRows.length+' column(s)</span>' : '<span class="muted">No columns match</span>');
  const mb = $('#cmore button'); if (mb) mb.onclick = ()=>renderCols(false); wire(body); }
$('#cq').addEventListener('input', ()=>{ clearTimeout(timer); timer=setTimeout(()=>renderCols(),150); }); $('#onlyHidden').onchange = ()=>renderCols();

// tables
function renderTables(){ const t = low($('#tq').value); const list = D.tables.filter(x=>!t||low(x.n).includes(t)||x.c.some(c=>low(c).includes(t))).slice(0,200);
  $('#tlist').innerHTML = list.map(x=>'<div class="card"><h3>'+mark(x.n,[t])+' <small>'+x.c.length+' columns · used by '+x.d.length+' DataWindow(s)</small> <button class="chip" data-join="'+esc(x.n)+'">+ Join builder</button></h3><div class="chips">'+x.c.map(c=>'<span class="tag">'+mark(c,[t])+'</span>').join(' ')+'</div><div class="muted" style="font-size:12px">'+x.d.slice(0,30).map(n=>'<button class="chip" data-dw="'+esc(n)+'">'+esc(n)+'</button>').join(' ')+(x.d.length>30?' …':'')+'</div></div>').join('') || '<div class="empty">No tables match.</div>';
  wire($('#tlist')); $('#tlist').querySelectorAll('[data-join]').forEach(b=>b.onclick=e=>{ e.stopPropagation(); addTable(b.dataset.join); show('join'); }); }
$('#tq').addEventListener('input', ()=>{ clearTimeout(timer); timer=setTimeout(renderTables,150); });

// join builder
const tableNames = {}; D.tables.forEach(t=>tableNames[low(t.n)]=t.n);
$('#tablenames').innerHTML = D.tables.map(t=>'<option value="'+esc(t.n)+'">').join('');
const adj = {}; D.edges.forEach(e=>{ const a=low(e.a), b=low(e.b); (adj[a]=adj[a]||[]).push([b,e]); (adj[b]=adj[b]||[]).push([a,e]); });
function path(s, g){ s=low(s); g=low(g); if(s===g) return []; const dist={[s]:0}, prev={}, done=new Set(); const q=[[0,s]];
  while(q.length){ q.sort((x,y)=>x[0]-y[0]); const [d,n]=q.shift(); if(done.has(n)) continue; done.add(n); if(n===g) break;
    for(const [m,e] of (adj[n]||[])){ const nd=d+1+1/(1+e.k); if(nd<(dist[m]??Infinity)){ dist[m]=nd; prev[m]=[n,e]; q.push([nd,m]); } } }
  if(!(g in prev)) return null; const chain=[]; let n=g; while(n!==s){ const [p,e]=prev[n]; chain.push(e); n=p; } return chain.reverse(); }
let picked = [];
function addTable(name){ name=(name||'').trim(); if(!name) return; const real = tableNames[low(name)] || name; if(!picked.some(p=>low(p)===low(real))) picked.push(real); $('#jt').value=''; buildJoin(); }
function buildJoin(){ $('#jpicked').innerHTML = picked.map((p,i)=>'<button class="chip" data-i="'+i+'">'+esc(p)+' ✕</button>').join('');
  $('#jpicked').querySelectorAll('[data-i]').forEach(b=>b.onclick=()=>{ picked.splice(+b.dataset.i,1); buildJoin(); });
  if(!picked.length){ $('#jsql').value=''; $('#jnote').textContent=''; return; }
  const placed=[low(picked[0])], lines=['FROM '+picked[0]], missing=[];
  for(const t of picked.slice(1)){ if(placed.includes(low(t))) continue; let best=null;
    for(const p of placed){ const c=path(p,t); if(c && (!best || c.length<best.length)) best=c; }
    if(!best){ missing.push(t); continue; }
    for(const e of best){ const ai=placed.includes(low(e.a)), bi=placed.includes(low(e.b)); if(ai&&bi) continue; const nw = ai? e.b : e.a;
      lines.push('JOIN '+nw+' ON '+e.p.map(p=>p[0]+' = '+p[1]).join(' AND ')); placed.push(low(nw)); } }
  const cols = placed.map(p=>(tableNames[p]||p)+'.*');
  let sql = 'SELECT '+cols.join(',\n       ')+'\n'+lines.join('\n');
  if (missing.length) sql += '\n-- No join seen in Units\' own SQL for: '+missing.join(', ')+'\n-- Look for a shared key column (stock number, VIN, customer number) on the Tables tab.';
  $('#jsql').value = sql; $('#jnote').textContent = 'Replace the .* lists with the columns you want. Tables added along the way link your picks together.'; }
$('#jadd').onclick = ()=>addTable($('#jt').value); $('#jt').addEventListener('keydown', e=>{ if(e.key==='Enter') addTable($('#jt').value); });
$('#jclear').onclick = ()=>{ picked=[]; buildJoin(); }; $('#jcopy').onclick = ()=>copy($('#jsql').value, $('#jcopy'));

// files
function renderFiles(){ $('#flist').innerHTML = '<div class="card"><h3>Files read ('+D.files.length+')</h3><pre>'+esc(D.files.join('\n'))+'</pre></div>' +
  (D.errors.length? '<div class="card"><h3 class="warn">Could not read ('+D.errors.length+')</h3><pre>'+esc(D.errors.join('\n'))+'</pre></div>':''); }
})();
</script>
</body>
</html>
"""
