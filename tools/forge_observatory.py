#!/usr/bin/env python3
"""
forge_observatory.py — Neural Swarm Observatory : node-graph LIVE du flux de
réflexion Nokido (inspiré Netron : DAG layout propre).

Serveur stdlib auto-suffisant (pas de FastAPI/auth) :
  GET /         -> page HTML (cytoscape.js + dagre, thème dark Netron-like)
  GET /stream   -> SSE : tail `sandbox/reflexion.jsonl` (miroir forge_swarm_bus)

Backbone fixe = pipeline AMI/raisonnement (Perception → World Model → MPC →
MCTS → Cost → Action) + GOAP + LLM Cascade. Chaque event `reasoning:*` /
`goap` PULSE le node correspondant + trace le chemin actif + log live.

Phase 2 du chantier viz (phase 1 = forge_reflexion_cli). Source = même JSONL.
Events visibles après restart hub (hooks actor/mpc/cascade + GOAP actifs).

Usage : python tools/forge_observatory.py   (puis http://127.0.0.1:7600)
"""

from __future__ import annotations

import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "sandbox" / "reflexion.jsonl"
PORT = 7600

HTML = r"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Neural Swarm Observatory — Nokido</title>
<script src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
<script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
<script src="https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js"></script>
<style>
 html,body{margin:0;height:100%;background:#0d1117;color:#c9d1d9;font:13px ui-monospace,Consolas,monospace;overflow:hidden}
 #cy{position:absolute;left:0;top:0;right:340px;bottom:0}
 #side{position:absolute;right:0;top:0;width:340px;bottom:0;border-left:1px solid #21262d;background:#0a0d12;display:flex;flex-direction:column}
 #hd{padding:10px 12px;border-bottom:1px solid #21262d}
 #hd b{color:#58a6ff;font-size:14px}
 #hd .st{color:#8b949e;font-size:11px}
 #log{flex:1;overflow:auto;padding:6px 10px}
 .ev{padding:4px 6px;border-bottom:1px solid #161b22;animation:fade .6s}
 .ev .k{font-weight:bold}.ev .m{color:#8b949e}
 @keyframes fade{from{background:#1f6feb33}to{background:transparent}}
 .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
</style></head><body>
<div id="cy"></div>
<div id="side"><div id="hd"><b>🧠 Neural Swarm Observatory</b><div class="st" id="st">connexion…</div></div><div id="log"></div></div>
<script>
const COL={perception:'#3fb950',world:'#a371f7',mpc:'#58a6ff',mcts:'#d29922',goap:'#39c5cf',cost:'#f85149',action:'#db61a2',llm:'#ff7b72',silo:'#7ee787',tool:'#ffa657'};
// backbone fixe (les "neurones")
const NODES=[
 ['perception','Perception\n(state_encoder)','perception'],
 ['world','World Model\n(JEPA)','world'],
 ['mpc','MPC\n(plan_horizon)','mpc'],
 ['mcts','Actor MCTS\n(propose)','mcts'],
 ['goap','GOAP\n(plan)','goap'],
 ['llm','LLM Cascade','llm'],
 ['cost','Cost Net','cost'],
 ['action','Action','action'],
];
const EDGES=[['perception','world'],['world','mpc'],['mpc','mcts'],['mcts','cost'],['cost','action'],['goap','mcts'],['llm','goap'],['world','llm']];
const cy=cytoscape({container:document.getElementById('cy'),
 elements:[...NODES.map(([id,l,c])=>({data:{id,label:l,c}})),...EDGES.map(([s,t],i)=>({data:{id:'e'+i,source:s,target:t}}))],
 style:[
  {selector:'node',style:{'label':'data(label)','text-wrap':'wrap','text-valign':'center','text-halign':'center','color':'#e6edf3','background-color':'#161b22','border-width':2,'border-color':d=>COL[d.data('c')]||'#30363d','shape':'round-rectangle','width':110,'height':54,'font-size':10,'text-max-width':100}},
  {selector:'edge',style:{'width':1.5,'line-color':'#30363d','target-arrow-color':'#30363d','target-arrow-shape':'triangle','curve-style':'bezier'}},
  {selector:'.pulse',style:{'border-width':5,'background-color':d=>(COL[d.data('c')]||'#30363d')+'33'}},
 ],
 layout:{name:'dagre',rankDir:'LR',nodeSep:30,rankSep:70}});

// map event -> node id
function nodeFor(ev){const k=(ev.kind||'').toLowerCase(),t=(ev.topic||'');
 if(k.includes('mcts')||k.includes('actor'))return'mcts';
 if(k.includes('mpc')||k.includes('horizon'))return'mpc';
 if(k.includes('llm')||k.includes('provider')||k.includes('cascade'))return'llm';
 if(t.startsWith('goap')||k.includes('goap'))return'goap';
 if(k.includes('cost'))return'cost';
 if(t.startsWith('silo'))return'goap';
 return null;}

function pulse(id){const n=cy.getElementById(id);if(!n||n.empty())return;n.addClass('pulse');setTimeout(()=>n.removeClass('pulse'),700);}
const logEl=document.getElementById('log');let nlog=0;
function addLog(ev){const id=nodeFor(ev);const c=id?(COL[cy.getElementById(id).data('c')]||'#8b949e'):'#8b949e';
 const d=document.createElement('div');d.className='ev';
 const data=ev.data||{};const m=Object.entries(data).slice(0,3).map(([k,v])=>k+'='+(''+JSON.stringify(v)).slice(0,28)).join(' ');
 d.innerHTML='<span class="dot" style="background:'+c+'"></span><span class="k">'+(ev.topic||'?')+'/'+(ev.kind||'?')+'</span> <span class="m">'+m+'</span>';
 logEl.insertBefore(d,logEl.firstChild);if(++nlog>120)logEl.removeChild(logEl.lastChild);}

const es=new EventSource('/stream');
es.onopen=()=>document.getElementById('st').textContent='● live';
es.onerror=()=>document.getElementById('st').textContent='○ déconnecté (reflexion.jsonl actif après restart hub)';
es.onmessage=e=>{let ev;try{ev=JSON.parse(e.data)}catch(_){return}pulse(nodeFor(ev));addLog(ev);};
</script></body></html>"""


class _H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/" or self.path.startswith("/?"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self._stream()
        else:
            self.send_error(404)

    def _send(self, line: str):
        self.wfile.write(b"data: " + line.encode("utf-8") + b"\n\n")
        self.wfile.flush()

    def _ping(self):
        self.wfile.write(b":ping\n\n")
        self.wfile.flush()

    def _stream(self):
        try:
            if LOG.exists():
                for ln in LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]:
                    if ln.strip():
                        self._send(ln.strip())
            while not LOG.exists():
                self._ping()
                time.sleep(1)
            with open(LOG, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)
                idle = 0
                while True:
                    ln = f.readline()
                    if not ln:
                        time.sleep(0.4)
                        idle += 1
                        if idle % 25 == 0:
                            self._ping()
                        continue
                    idle = 0
                    ln = ln.strip()
                    if ln:
                        self._send(ln)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        except Exception:
            return

    def log_message(self, *a):  # silence
        pass


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), _H)
    print(f"[observatory] http://127.0.0.1:{PORT}  (SSE tail {LOG})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
