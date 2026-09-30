"""
app/web_hub/mcp_lab.py - Lab MCP integre au hub web Nokido.

Outil de debug interactif pour les frontaux MCP :
  - Streamable HTTP (POST /mcp sur 127.0.0.1:8766)
  - stdio bridge (Phase 2 - non implemente)

Architecture : router FastAPI mounte sous /mcp_lab. Pattern identique
a ctf_reports.views et netcfg.views.

PHASE 1 (this file) :
  GET  /mcp_lab/api/health   sante hub + bridge + logs
  GET  /mcp_lab/api/tools    liste les outils via tools/list
  POST /mcp_lab/api/invoke   invoque un tool (Streamable HTTP only)

Phases suivantes : transport=stdio, /api/tap SSE multi-source,
/api/diff comparaison transports, page HTML 3 onglets.

Note naming : 'mcp_lab' plutot que 'inspector' pour eviter collision
avec app/forge_inspector.py (agent monitoring sys, namespace
EventBus 'inspector.*').

Securite : herite AuthMiddleware du hub (JWT). Bind loopback (127.0.0.1).
SecretGuard du hub reste actif sur les tool calls.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from nokido_agent.app.forge_secrets import get_secret


router = APIRouter()

_HUB_URL = "http://127.0.0.1:8766/mcp"
_HEALTH_URL = "http://127.0.0.1:8766/health"
try:
    from app.web_hub.wired_routes import _hub_token as _mcplab_hub_token
except Exception:  # pragma: no cover
    def _mcplab_hub_token() -> str:
        # MEME ORDRE QUE LA SOURCE UNIQUE (`wired_routes._hub_token`) : le jeton
        # PROPRE de l'interface d'abord, le maitre en repli seulement. Cette copie
        # ne sert que si l'import ci-dessus echoue ; la laisser sur le maitre
        # reintroduirait le confused deputy par le chemin de secours, c'est-a-dire
        # exactement la ou personne ne regarde.
        return get_secret("FORGE_TOKEN_WEBHUB") or get_secret("FORGE_MCP_TOKEN") or ""
_TIMEOUT_S = 30.0


# -- MODELS -----------------------------------------------------------------


class InvokeRequest(BaseModel):
    """Body de POST /mcp_lab/api/invoke."""

    transport: str = Field(default="streamable_http", description="streamable_http | stdio (phase 2)")
    tool: str = Field(..., description="Nom de l outil MCP a invoquer")
    arguments: dict = Field(default_factory=dict, description="Arguments du tool (objet JSON)")


class InvokeResponse(BaseModel):
    """Reponse de POST /mcp_lab/api/invoke."""

    ok: bool
    transport: str
    tool: str
    request: dict  # payload JSON-RPC sortant
    response: Any  # payload JSON-RPC entrant (parse)
    latency_ms: float
    error: Optional[str] = None


# -- CLIENT TRANSPORT : Streamable HTTP -------------------------------------


async def _invoke_streamable_http(tool: str, arguments: dict) -> dict:
    """Invoque un tool via le hub /mcp (transport Streamable HTTP).

    Pas de retry interne : echec rapide pour debug. Si la reponse est
    en text/event-stream, on agrege le dernier 'data: {...}'.
    """
    req_id = str(uuid.uuid4())[:8]
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Agent-Name": "WEBHUB",
        "X-Transport": "mcp_lab/1.0",
    }
    _t = _mcplab_hub_token()
    if _t:
        headers["Authorization"] = "Bearer " + _t
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        r = await client.post(_HUB_URL, json=payload, headers=headers)
        ct = r.headers.get("content-type", "")
        if "text/event-stream" in ct:
            last = None
            async for line in r.aiter_lines():
                line = line.strip()
                if line.startswith("data: "):
                    body = line[6:]
                    if body.startswith("{"):
                        last = body
            response = json.loads(last) if last else {}
        else:
            response = r.json()
    latency_ms = round((time.monotonic() - t0) * 1000, 2)
    return {"request": payload, "response": response, "latency_ms": latency_ms}


async def _list_tools_streamable_http() -> dict:
    """Recupere tools/list depuis le hub via Streamable HTTP."""
    payload = {
        "jsonrpc": "2.0",
        "id": "list-" + str(uuid.uuid4())[:8],
        "method": "tools/list",
        "params": {},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Agent-Name": "WEBHUB",
    }
    _t = _mcplab_hub_token()
    if _t:
        headers["Authorization"] = "Bearer " + _t
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(_HUB_URL, json=payload, headers=headers)
        return r.json()


# -- HTML PAGE -------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCP Lab — Nokido</title>
<script src="/static/tailwind.min.js"></script>
<link rel="stylesheet" href="/static/nokido.css">
<style>
  body { background:var(--bg-0); color:var(--text-secondary); font-family:var(--font-sans); }
  .card { background:#161b22; border:1px solid #30363d; border-radius:6px; }
  pre { background:#0d1117; border:1px solid #30363d; border-radius:4px; padding:8px; overflow-x:auto; }
  input,textarea,select { background:#0d1117; border:1px solid #30363d; color:#c9d1d9; border-radius:4px; padding:4px 8px; width:100%; }
  button { cursor:pointer; }
</style>
</head>
<body class="p-6">
<h1 class="text-xl font-bold text-sky-400 mb-4">⚗️ MCP Lab — Nokido :8766</h1>

<div id="health" class="card p-3 mb-4 text-sm text-slate-400">Chargement santé...</div>

<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
  <!-- Tool list -->
  <div class="card p-4">
    <h2 class="text-sm font-semibold text-slate-300 mb-2">Outils disponibles</h2>
    <div id="tool-list" class="text-sm space-y-1 text-slate-400">Chargement...</div>
  </div>

  <!-- Invoke form -->
  <div class="card p-4">
    <h2 class="text-sm font-semibold text-slate-300 mb-2">Invoquer un outil</h2>
    <div class="space-y-2">
      <div>
        <label class="text-xs text-slate-500">Outil</label>
        <select id="sel-tool" class="mt-1 text-sm"></select>
      </div>
      <div id="tool-form" class="space-y-2"></div>
      <details class="mt-1">
        <summary class="text-xs text-slate-500 cursor-pointer">Arguments (JSON brut — fallback)</summary>
        <textarea id="sel-args" rows="4" class="mt-1 text-sm font-mono" placeholder='{"key": "value"}'>{}</textarea>
      </details>
      <button id="btn-invoke" data-testid="mcp-run-generic"
        class="mt-2 px-4 py-1.5 bg-sky-700 hover:bg-sky-600 text-white text-sm rounded">
        ▶ Invoquer
      </button>
    </div>

    <div id="result-box" class="mt-4 hidden">
      <div class="text-xs text-slate-500 mb-1">Résultat <span id="latency" class="text-sky-400"></span></div>
      <pre id="result-pre" class="text-xs max-h-96 overflow-y-auto"></pre>
    </div>
  </div>
</div>

<script>
const base = '/mcp_lab';
async function load() {
  try {
    // `fetch` NE REJETTE PAS sur 401/500 : sans ce test, la reponse d'erreur est un
    // JSON valide, `h.ok` vaut undefined, et la page annonce « Hub DOWN » alors que
    // le hub repond en 13 ms — mesure 2026-07-28, gate UI rouge sur ce seul motif.
    // On distingue desormais « hub en panne » de « ma propre route API inaccessible ».
    const rH = await fetch(base + '/api/health');
    const h = rH.ok ? await rH.json() : { ok: false, http: rH.status };
    document.getElementById('health').innerHTML =
      '<span class="' + (h.ok ? 'text-green-400' : 'text-red-400') + '">' +
      (h.ok ? '✓ Hub UP' : (h.http ? '✗ API mcp_lab HTTP ' + h.http : '✗ Hub DOWN')) + '</span>' +
      ' &nbsp;|&nbsp; latence hub: ' + (h.checks?.hub?.latency_ms ?? '?') + 'ms';
  } catch(e) { document.getElementById('health').textContent = '✗ ' + e; }

  try {
    const t = await fetch(base + '/api/tools').then(r => r.json());
    const tools = t.data?.result?.tools || t.result?.tools || t.tools || [];
    const sel = document.getElementById('sel-tool');
    sel.innerHTML = tools.map(t => '<option value="' + t.name + '">' + t.name + '</option>').join('');
    sel.onchange = () => {
      loadForm(sel.value);
      document.getElementById('btn-invoke').setAttribute('data-testid', 'mcp-run-' + sel.value);
    };
    if (sel.value) {
      loadForm(sel.value);
      document.getElementById('btn-invoke').setAttribute('data-testid', 'mcp-run-' + sel.value);
    }
    document.getElementById('tool-list').innerHTML = tools.map(t =>
      '<div class="py-1 border-b border-slate-800" data-testid="mcp-tool-' + t.name + '">' +
      '<span class="text-sky-300">' + t.name + '</span>' +
      '<span class="text-slate-500 ml-2 text-xs">' + (t.description || '').slice(0,60) + '</span>' +
      '</div>'
    ).join('') || '<span class="text-slate-600">Aucun outil</span>';
  } catch(e) { document.getElementById('tool-list').textContent = '✗ ' + e; }
}

async function loadForm(tool) {
  const c = document.getElementById('tool-form');
  c.innerHTML = '<span class="text-slate-600 text-xs">form…</span>';
  try { c.innerHTML = await fetch(base + '/api/form/' + encodeURIComponent(tool)).then(r => r.text()); }
  catch(e) { c.innerHTML = ''; }
}
function argsFromForm(formEl) {
  const o = {};
  formEl.querySelectorAll('[name]').forEach(el => {
    if (el.type === 'checkbox') { o[el.name] = el.checked; return; }
    if (el.value === '') return;
    if (el.type === 'number') { o[el.name] = Number(el.value); return; }
    if (el.tagName === 'TEXTAREA' && (el.placeholder || '').startsWith('JSON')) {
      try { o[el.name] = JSON.parse(el.value); } catch(e) { o[el.name] = el.value; } return;
    }
    o[el.name] = el.value;
  });
  return o;
}
document.getElementById('tool-form').addEventListener('submit', (e) => {
  e.preventDefault(); document.getElementById('btn-invoke').click();
});
document.getElementById('btn-invoke').onclick = async () => {
  const tool = document.getElementById('sel-tool').value;
  let args;
  const formEl = document.querySelector('#tool-form form');
  if (formEl) { args = argsFromForm(formEl); }
  else {
    try { args = JSON.parse(document.getElementById('sel-args').value || '{}'); }
    catch(e) { alert('JSON invalide: ' + e); return; }
  }
  document.getElementById('btn-invoke').disabled = true;
  try {
    const r = await fetch(base + '/api/invoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, arguments: args })
    }).then(r => r.json());
    document.getElementById('result-box').classList.remove('hidden');
    document.getElementById('latency').textContent = r.latency_ms + 'ms';
    document.getElementById('result-pre').textContent = JSON.stringify(r.response, null, 2);
  } catch(e) {
    document.getElementById('result-box').classList.remove('hidden');
    document.getElementById('result-pre').textContent = '✗ ' + e;
  } finally { document.getElementById('btn-invoke').disabled = false; }
};

load();
</script>
</body>
</html>"""


# `response_class=None` casse la GENERATION du schema, pas la route : FastAPI leve
# « A response class is needed to generate OpenAPI » et /openapi.json rend 500 -- donc
# /docs et /redoc s'affichent VIDES, puisque Swagger se nourrit de ce schema. Mesure
# 2026-08-26 : la page repondait 200 et paraissait saine, seule la documentation etait
# morte. Ces deux routes rendent du HTML, on le DECLARE.
@router.get("/", response_class=HTMLResponse)
async def mcp_lab_page():
    """HTML — Lab interactif : liste les outils MCP et permet l invocation."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(_HTML)


# -- ROUTES -----------------------------------------------------------------


@router.get("/api/health")
async def health() -> dict:
    """Synthese sante : hub /health, age des logs bridge/audit.

    Pas de tool calls -- pure lecture d etat.
    """
    out: dict[str, Any] = {"ok": True, "checks": {}}

    # Hub /health. `latency_ms` est ATTENDU par le badge de la page
    # (h.checks?.hub?.latency_ms) et n'etait jamais renvoye : il affichait « ?ms ».
    try:
        _t0 = time.time()
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(_HEALTH_URL)
            out["checks"]["hub"] = {
                "ok": r.status_code == 200,
                "status_code": r.status_code,
                "latency_ms": round((time.time() - _t0) * 1000),
                "body": r.json() if r.status_code == 200 else None,
            }
        # Un hub qui repond autre chose que 200 n'est pas sain : le verdict global
        # doit le refleter, sinon la page annonce UP sur un hub en erreur.
        if r.status_code != 200:
            out["ok"] = False
    except Exception as e:
        out["checks"]["hub"] = {"ok": False, "latency_ms": None,
                                "error": f"{type(e).__name__}: {e}"[:120]}
        out["ok"] = False

    # Logs frais
    from pathlib import Path as _P

    logs_dir = _P(__file__).resolve().parent.parent.parent / "logs"
    for log_name in ("mcp_audit.log", "mcp_bridge.log"):
        p = logs_dir / log_name
        if p.exists():
            stat = p.stat()
            out["checks"][log_name] = {
                "ok": True,
                "size_bytes": stat.st_size,
                "mtime_age_s": round(time.time() - stat.st_mtime, 1),
            }
        else:
            out["checks"][log_name] = {"ok": False, "error": "absent"}

    return out


@router.get("/api/tools")
async def list_tools() -> dict:
    """Liste les outils exposes par le hub (tools/list).

    Renvoie le JSON-RPC brut pour permettre une UI riche
    (description + inputSchema cote frontend).
    """
    try:
        result = await _list_tools_streamable_http()
        return {"ok": True, "data": result}
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
            httpx.PoolTimeout, ConnectionError, TimeoutError) as e:
        # DEPENDANCE INJOIGNABLE != DEFAUT DU PORTAIL. Mesure 2026-09-06 : la CI a rougi
        # sur `/mcp_lab/api/tools -> 502` pendant une coupure PASSAGERE du hub, alors que
        # cette page etait saine -- le gate a lu « erreur serveur » la ou il fallait lire
        # « amont muet ». Le corps distingue deja un service on-demand eteint (503,
        # legitime) d'une panne (500+) : une dependance absente releve de la meme
        # famille. Le 502 reste pour ce qui EST une panne de passerelle : le hub a
        # repondu, mais mal.
        raise HTTPException(503, f"hub injoignable ({type(e).__name__}: {e}) -- "
                                 f"dependance absente, pas un defaut de cette page")
    except Exception as e:
        raise HTTPException(502, f"hub tools/list failed: {type(e).__name__}: {e}")


@router.get("/api/form/{tool}", response_class=HTMLResponse)
async def tool_form(tool: str):
    """Form UI FIDELE d'un tool, genere depuis son inputSchema via forge_ui_moulinette (0 token)."""
    import re as _re
    import sys as _sys
    from pathlib import Path as _P
    from fastapi.responses import HTMLResponse

    _tools_dir = str(_P(__file__).resolve().parent.parent.parent / "tools")
    if _tools_dir not in _sys.path:
        _sys.path.insert(0, _tools_dir)
    try:
        data = await _list_tools_streamable_http()
        tools = (data.get("result") or {}).get("tools") or []
        spec = next((t for t in tools if t.get("name") == tool), None)
        if not spec:
            return HTMLResponse(f'<p class="text-red-400 text-xs">tool inconnu: {tool}</p>', status_code=404)
        from nokido_agent.tools.forge_ui_moulinette import render_form_html

        html = render_form_html(_re.sub(r"\W", "_", tool), spec.get("inputSchema") or {}, action="#")
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f'<p class="text-red-400 text-xs">form err: {e}</p>', status_code=500)


@router.post("/api/invoke", response_model=InvokeResponse)
async def invoke(body: InvokeRequest) -> InvokeResponse:
    """Invoque un outil MCP via le transport demande.

    Phase 1 : transport='streamable_http'. Phase 2 : 'stdio'.
    """
    if body.transport == "streamable_http":
        try:
            data = await _invoke_streamable_http(body.tool, body.arguments)
            resp = data["response"]
            err = None
            ok = True
            if isinstance(resp, dict) and "error" in resp:
                ok = False
                err = str(resp["error"])[:200]
            return InvokeResponse(
                ok=ok,
                transport=body.transport,
                tool=body.tool,
                request=data["request"],
                response=resp,
                latency_ms=data["latency_ms"],
                error=err,
            )
        except Exception as e:
            return InvokeResponse(
                ok=False,
                transport=body.transport,
                tool=body.tool,
                request={"intended_tool": body.tool, "arguments": body.arguments},
                response=None,
                latency_ms=0.0,
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )
    elif body.transport == "stdio":
        raise HTTPException(501, "transport=stdio non implemente (Phase 2)")
    else:
        raise HTTPException(400, f"transport inconnu: {body.transport!r}")
