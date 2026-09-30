#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_trace_ui.py — interface web SOUVERAINE de visualisation observabilité.

Rend le call-flow runtime (`forge_trace_viz`) en **Mermaid live dans le navigateur**.
Lit `audit.db` (spans imbriqués span_id/parent_id). ZÉRO backend externe, ZÉRO
licence non-libre — le remplaçant souverain d'Arize Phoenix (Elastic License 2.0).
`mermaid.js` via CDN (rendu client-side, dans TON navigateur).

  - liste des traces (id · spans · durée · erreurs),
  - clic -> arbre d'appels (`tree`) / séquence (`seq`) / graphe deps (`deps`),
  - auto-refresh, tri récent/volume.

Usage : forge_trace_ui.py --serve [--port 7611]   ->  http://127.0.0.1:7611
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/
from nokido_agent.tools.forge_trace_viz import (  # noqa: E402
    list_traces, load_spans, to_tree, to_sequence, to_deps, summary,
)

HTML = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nokido — Observabilité (souverain)</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0d1117;color:#c9d1d9;font:14px/1.5 ui-monospace,Consolas,monospace;display:flex;height:100vh}
#side{width:340px;border-right:1px solid #21262d;overflow:auto;flex:none}
#main{flex:1;overflow:auto;padding:16px}
header{padding:12px 14px;border-bottom:1px solid #21262d;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
h1{font-size:14px;margin:0;font-weight:600;color:#58a6ff}
button,select{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 8px;cursor:pointer;font:inherit}
button:hover{border-color:#58a6ff}
.tr{padding:8px 12px;border-bottom:1px solid #161b22;cursor:pointer}
.tr:hover{background:#161b22}
.tr.sel{background:#1f6feb22;border-left:3px solid #58a6ff}
.tr .id{color:#79c0ff;font-size:11px;word-break:break-all}
.tr .meta{color:#8b949e;font-size:11px;margin-top:2px}
.err{color:#f85149}
#sum{color:#8b949e;font-size:12px;margin-bottom:10px;white-space:pre-wrap}
.mermaid{background:#0d1117}
footer{color:#484f58;font-size:11px;padding:8px 14px;border-top:1px solid #21262d}
</style></head><body>
<div id="side">
  <header><h1>🩺 Observabilité</h1>
    <select id="by"><option value="recent">récent</option><option value="count">volume</option></select>
    <button onclick="loadList()">↻</button></header>
  <div id="list"></div>
  <footer>souverain · audit.db · zéro licence externe</footer>
</div>
<div id="main">
  <header style="border:0;padding:0 0 10px 0">
    <button onclick="show('tree')">arbre</button>
    <button onclick="show('seq')">séquence</button>
    <button onclick="show('deps')">deps</button>
    <span id="cur" style="color:#8b949e;font-size:11px"></span></header>
  <div id="sum"></div>
  <div id="diagram" class="mermaid">%% sélectionne une trace à gauche</div>
</div>
<script>
mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'loose'});
let CUR=null, VIEW='tree';
async function loadList(){
  const by=document.getElementById('by').value;
  const r=await fetch('/api/traces?by='+by); const t=await r.json();
  const el=document.getElementById('list'); el.innerHTML='';
  t.forEach(x=>{
    const d=document.createElement('div'); d.className='tr'+(x.trace_id===CUR?' sel':'');
    const err=x.errs?` <span class="err">!${x.errs}</span>`:'';
    d.innerHTML=`<div class="id">${x.trace_id||'(null)'}</div><div class="meta">${x.spans} spans · ${x.wall_ms}ms${err}</div>`;
    d.onclick=()=>sel(x.trace_id); el.appendChild(d);
  });
}
async function sel(id){CUR=id;document.getElementById('cur').textContent=id;loadList();render();}
function show(v){VIEW=v;render();}
async function render(){
  if(!CUR)return;
  const r=await fetch('/api/trace/'+CUR+'?view='+VIEW); const j=await r.json();
  document.getElementById('sum').textContent=j.summary||'';
  const m=j.mermaid||'%% (aucun span)';
  const box=document.getElementById('diagram');
  try{const {svg}=await mermaid.render('g'+Date.now(),m);box.innerHTML=svg;}
  catch(e){box.innerHTML='<pre>'+m+'\\n\\n'+e+'</pre>';}
}
loadList(); setInterval(loadList,8000);
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="UI observabilité souveraine (Mermaid live)")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=7611)
    a = ap.parse_args()

    import http.server
    from urllib.parse import urlparse, parse_qs

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, body, ct="application/json"):
            b = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(200)
            self.send_header("content-type", ct)
            self.send_header("content-length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path == "/api/traces":
                    by = q.get("by", ["recent"])[0]
                    self._send(json.dumps(list_traces(40, by=by), default=str))
                    return
                if u.path.startswith("/api/trace/"):
                    tid = u.path.split("/api/trace/", 1)[1]
                    spans = load_spans(tid)
                    view = q.get("view", ["tree"])[0]
                    fn = {"tree": to_tree, "seq": to_sequence, "deps": to_deps}.get(view, to_tree)
                    self._send(json.dumps(
                        {"summary": summary(tid, spans), "mermaid": fn(spans) if spans else ""},
                        default=str))
                    return
                self._send(HTML, "text/html; charset=utf-8")
            except Exception as exc:  # noqa: BLE001
                self._send(json.dumps({"error": str(exc)}))

    srv = http.server.HTTPServer(("127.0.0.1", a.port), H)
    print(f"[trace-ui] http://127.0.0.1:{a.port}  (Ctrl-C pour stop)")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
