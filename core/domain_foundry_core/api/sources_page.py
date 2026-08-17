"""Server-rendered 'Add a source' page for ``domain-foundry serve``.

A no-terminal way to bolt existing notes/logs onto your foundries: pick a folder,
preview where each note would land (read-only), then pull it in. Talks to the
local, same-origin ``/api/ingest/preview`` and ``/api/ingest`` endpoints. Kept as
a standalone page (not the built SPA) so it works without a frontend build.
"""

from __future__ import annotations

SOURCES_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Add a source · Domain Foundry</title>
<style>
  :root { --green:#0f766e; --green-soft:#e3f1ec; --ink:#111917; --muted:#5b6b66;
    --line:#e1e7e4; --ground:#f4f6f5; --card:#fff; --coral:#c7615a; --coral-soft:#f6e4e2;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--ground); color:var(--ink); font-family:var(--sans); }
  .wrap { max-width:760px; margin:0 auto; padding:28px 22px 60px; }
  .brand { font-weight:700; display:flex; align-items:center; gap:8px; }
  .brand .m { color:var(--green); }
  h1 { font-size:26px; letter-spacing:-.02em; margin:18px 0 4px; }
  .sub { color:var(--muted); margin:0 0 22px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; }
  label { display:block; font-size:13px; font-weight:600; margin:14px 0 6px; }
  input, select { width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:9px;
    font-family:var(--mono); font-size:14px; background:var(--ground); color:var(--ink); }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .actions { display:flex; gap:10px; margin-top:18px; }
  button { font-weight:600; font-size:14px; border-radius:9px; padding:11px 18px; cursor:pointer; border:1px solid var(--line); }
  .primary { background:var(--green); color:#fff; border-color:var(--green); }
  .ghost { background:var(--card); color:var(--ink); }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .hint { font-size:12px; color:var(--muted); margin-top:8px; }
  #out { margin-top:22px; }
  .stat-row { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
  .stat .n { font-size:20px; font-weight:800; font-variant-numeric:tabular-nums; }
  .stat .l { font-family:var(--mono); font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
  .bars { display:flex; flex-direction:column; gap:8px; }
  .bar { display:grid; grid-template-columns:120px 1fr 44px; align-items:center; gap:10px; font-size:13px; }
  .bar .name { font-weight:600; }
  .bar .track { height:12px; background:var(--ground); border-radius:999px; overflow:hidden; }
  .bar .fill { height:100%; background:var(--green); }
  .bar.unf .fill { background:var(--coral); }
  .bar .cnt { font-family:var(--mono); text-align:right; color:var(--muted); }
  .pill { display:inline-block; font-family:var(--mono); font-size:11px; font-weight:600;
    padding:3px 9px; border-radius:999px; background:var(--green-soft); color:var(--green); }
  .safe { margin-top:14px; font-size:13px; color:var(--muted); border-left:3px solid var(--green); padding-left:12px; }
</style></head>
<body><div class="wrap">
  <div class="brand"><span class="m">&#9670;</span> Domain Foundry</div>
  <h1>Add a source</h1>
  <p class="sub">Pull notes and logs you already have into your foundries. Nothing at the
    source is moved or changed &mdash; preview first, it writes nothing.</p>

  <div class="card">
    <label for="path">Folder or file to pull in</label>
    <input id="path" placeholder="~/Notes/climbing" spellcheck="false">
    <div class="row">
      <div>
        <label for="only">Only this foundry <span style="font-weight:400;color:var(--muted)">(optional)</span></label>
        <select id="only"><option value="">Let the models pick</option></select>
      </div>
      <div>
        <label for="split">Each file is</label>
        <select id="split">
          <option value="file">one note</option>
          <option value="lines">an append-only log (one per line)</option>
        </select>
      </div>
    </div>
    <div class="actions">
      <button class="ghost" id="preview">Preview routing</button>
      <button class="primary" id="commit" disabled>Pull in</button>
    </div>
    <p class="hint">Preview reads your files read-only and shows where each note would land.
      Re-running &ldquo;Pull in&rdquo; only picks up what&rsquo;s new.</p>
  </div>

  <div id="out"></div>
</div>
<script>
  var path = document.getElementById('path'), only = document.getElementById('only'),
      split = document.getElementById('split'), out = document.getElementById('out'),
      previewBtn = document.getElementById('preview'), commitBtn = document.getElementById('commit');

  var auth = window.__DE_TOKEN__ ? {'Authorization':'Bearer '+window.__DE_TOKEN__} : {};
  fetch('/api/packs', {headers:auth}).then(function(r){return r.json()}).then(function(d){
    (d.packs || []).forEach(function(p){
      var o = document.createElement('option'); o.value = p.name; o.textContent = p.title || p.name; only.appendChild(o);
    });
  }).catch(function(){});

  function body(){ return { path: path.value.trim(), only: only.value || null, split: split.value }; }

  function render(rep, committed){
    var domains = rep.by_domain || {}, names = Object.keys(domains);
    var max = Math.max(1, ...names.map(function(n){return domains[n]}), rep.unfiled||0);
    var bars = names.map(function(n){
      var w = Math.round((domains[n]/max)*100);
      return '<div class="bar"><span class="name">'+n+'</span><div class="track"><div class="fill" style="width:'+w+'%"></div></div><span class="cnt">'+domains[n]+'</span></div>';
    }).join('');
    if (rep.unfiled) { var w=Math.round((rep.unfiled/max)*100);
      bars += '<div class="bar unf"><span class="name">unfiled</span><div class="track"><div class="fill" style="width:'+w+'%"></div></div><span class="cnt">'+rep.unfiled+'</span></div>'; }
    var head = committed
      ? '<span class="pill">pulled in &#10003;</span>'
      : '<span class="pill">preview &middot; nothing written</span>';
    out.innerHTML = '<div class="card">'+head+
      '<div class="stat-row" style="margin-top:14px">'+
        stat(rep.scanned,'scanned')+
        stat(committed?rep.captured:(rep.scanned-(rep.unfiled||0)-(rep.filtered_out||0)), committed?'captured':'would file')+
        (rep.filtered_out?stat(rep.filtered_out,'left alone'):'')+
        (committed&&rep.skipped_existing?stat(rep.skipped_existing,'already had'):'')+
      '</div>'+
      '<div class="bars">'+(bars||'<span class="hint">No matches yet &mdash; try a different folder or foundry.</span>')+'</div>'+
      (committed?'':'<p class="safe">Looks right? Click <b>Pull in</b> to file these into your foundries.</p>')+
      '</div>';
  }
  function stat(n,l){ return '<div class="stat"><div class="n">'+(n||0)+'</div><div class="l">'+l+'</div></div>'; }

  function call(url, committed){
    if(!path.value.trim()){ path.focus(); return; }
    out.innerHTML = '<div class="card"><span class="hint">Reading&hellip;</span></div>';
    fetch(url, {method:'POST', headers:Object.assign({'Content-Type':'application/json'}, auth), body:JSON.stringify(body())})
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
      .then(function(rep){ render(rep, committed); commitBtn.disabled = committed; })
      .catch(function(e){ out.innerHTML = '<div class="card"><span class="hint">Couldn\\'t read that path ('+e.message+'). Check the folder exists.</span></div>'; });
  }
  previewBtn.onclick = function(){ call('/api/ingest/preview', false); };
  commitBtn.onclick = function(){ call('/api/ingest', true); };
</script>
</body></html>
"""
