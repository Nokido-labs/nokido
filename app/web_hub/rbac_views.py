"""RBAC mapping views — agent↔OS account editor pour web_hub :7400.

Endpoints :
  GET  /rbac                       page HTML (table éditable)
  GET  /api/rbac/entities          liste mappings JSON
  GET  /api/rbac/entities/{id}     détail
  PATCH /api/rbac/entities/{id}    update mapping (body: {zone, reason})
  GET  /api/rbac/audit?limit=N     journal modifications

Auth : middleware AuthMiddleware déjà appliqué côté app.py (cookie JWT).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rbac"])


def _mod():
    import sys

    p = str(Path(__file__).resolve().parent.parent)
    if p not in sys.path:
        sys.path.insert(0, p)
    from nokido_agent.app import forge_rbac_mapping as fm

    return fm


def _subject(request: Request) -> str:
    for k, v in request.scope.get("headers", []):
        if k.decode("latin-1").lower() == "x-laforge-user":
            return v.decode("latin-1")
    return "anonymous"


# ── JSON API ────────────────────────────────────────────────────────────────


@router.get("/api/rbac/entities")
async def api_list_entities():
    try:
        return {"entities": _mod().list_mappings()}
    except Exception as e:
        logger.exception("rbac list failed")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.get("/api/rbac/entities/{entity_id}")
async def api_get_entity(entity_id: str):
    m = _mod().get_mapping(entity_id)
    if not m:
        raise HTTPException(status_code=404, detail=f"entity inconnue: {entity_id}")
    return m


@router.patch("/api/rbac/entities/{entity_id}")
async def api_set_entity(entity_id: str, request: Request):
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")
    zone = body.get("zone")
    if not zone:
        raise HTTPException(status_code=400, detail="champ 'zone' requis")
    reason = (body.get("reason") or "")[:300]
    try:
        r = _mod().set_mapping(
            entity_id,
            zone=zone,
            actor=_subject(request),
            reason=reason,
        )
        return r
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("rbac set failed")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/api/rbac/entities")
async def api_create_entity(request: Request):
    """Cree une entite et son compte OS derive.

    Demande owner du 2026-09-18. Aucun chemin de creation n'existait : la page
    ne savait que modifier ce qui etait deja la, et `set_mapping` refuse une
    entite inconnue. Les refus (identifiant illisible, doublon, zone qui ne
    decoule pas du ring) viennent du metier et remontent en 422 avec leur motif
    -- l'interface AFFICHE ce motif, au lieu de se contenter d'un echec.
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")
    entity_id = (body.get("entity_id") or "").strip()
    if not entity_id:
        raise HTTPException(status_code=400, detail="champ 'entity_id' requis")
    try:
        ring = int(body.get("ring_level", 4))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="ring_level doit etre un entier")
    try:
        return _mod().create_mapping(
            entity_id,
            entity_type=(body.get("entity_type") or "agent"),
            ring_level=ring,
            display_name=(body.get("display_name") or None),
            actor=_subject(request),
            reason=(body.get("reason") or "")[:300],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("rbac create failed")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.get("/api/rbac/audit")
async def api_audit(limit: int = 50):
    limit = max(1, min(int(limit), 500))
    try:
        return {"log": _mod().audit_log(limit=limit)}
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


# ── HTML view ───────────────────────────────────────────────────────────────

_PAGE = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><title>RBAC mapping — Nokido</title>
<link rel="stylesheet" href="/static/nokido.css">
<style>
body{padding:20px;max-width:1100px;margin:0 auto;font-family:system-ui,sans-serif}
h1{font-size:1.2rem;margin-bottom:14px}
table{width:100%;border-collapse:collapse;background:var(--bg-2,#161b22);
  border:1px solid var(--border,#30363d);border-radius:6px;overflow:hidden}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border,#30363d);
  font-size:13px}
th{background:var(--bg-3,#21262d);font-weight:600;color:var(--text-secondary,#8b949e)}
tr:hover td{background:rgba(255,255,255,0.02)}
.ring{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.ring-master{background:#8b5cf6;color:#fff}
.ring-0{background:#dc2626;color:#fff}
.ring-1{background:#ea580c;color:#fff}
.ring-2{background:#ca8a04;color:#fff}
.ring-3{background:#0891b2;color:#fff}
.ring-4{background:#4b5563;color:#fff}
select{background:var(--bg-1,#0d1117);color:var(--text,#c9d1d9);
  border:1px solid var(--border,#30363d);padding:4px 6px;border-radius:4px;font-size:12px}
button{background:#2ea043;color:#fff;border:0;padding:5px 10px;border-radius:4px;
  cursor:pointer;font-size:12px}
button:hover{background:#3fb950}
button:disabled{background:#444;cursor:not-allowed}
.msg{margin-top:10px;padding:8px;border-radius:4px;font-size:13px}
.msg.ok{background:rgba(46,160,67,.15);color:#3fb950}
.msg.err{background:rgba(220,38,38,.15);color:#f85149}
a{color:#58a6ff;text-decoration:none}
.subt{font-size:12px;color:var(--text-dim,#6e7681);margin-bottom:14px}
input[type=text]{background:var(--bg-1,#0d1117);color:var(--text,#c9d1d9);
  border:1px solid var(--border,#30363d);padding:4px 6px;border-radius:4px;
  font-size:12px;width:160px}
</style></head><body>
<a href="/">← Dashboard</a>
<h1>🔐 RBAC mapping — agent → ring → zone → compte OS</h1>
<p class="subt">Chaque entité Nokido (agent CLI, humain, worker) est mappée
sur un compte Windows local. Le ring détermine la zone par défaut ; un
override est possible pour test/debug.</p>

<table id="t">
  <thead><tr>
    <th>entity_id</th><th>type</th><th>ring</th><th>zone</th>
    <th>os_user</th><th>os_group</th><th>raison</th><th></th>
  </tr></thead>
  <tbody></tbody>
</table>
<div id="msg"></div>

<h2 style="font-size:1rem;margin-top:24px">➕ Ajouter une entité</h2>
<p class="subt">La zone n'est pas un champ libre : elle <b>découle du ring</b>, parce
qu'elle porte le compte OS. On la resserre ensuite si besoin — elle ne s'invente pas
à la naissance.</p>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
  <input type="text" id="n_id" placeholder="entity_id — ex. agt_exemple">
  <select id="n_type">
    <option value="agent">agent</option>
    <option value="human">human</option>
    <option value="worker">worker</option>
    <option value="system">system</option>
  </select>
  <select id="n_ring">
    <option value="4" selected>R4 — sandbox-offline</option>
    <option value="3">R3 — sandbox-online</option>
    <option value="2">R2 — trusted</option>
    <option value="1">R1 — trusted</option>
    <option value="0">R0 — system</option>
  </select>
  <input type="text" id="n_reason" placeholder="raison (tracée dans l'audit)">
  <button id="n_add">Créer</button>
</div>

<h2 style="font-size:1rem;margin-top:20px">📜 Audit (20 derniers)</h2>
<table id="a">
  <thead><tr>
    <th>ts</th><th>entity_id</th><th>actor</th>
    <th>old zone</th><th>new zone</th><th>raison</th>
  </tr></thead><tbody></tbody>
</table>

<script>
const ZONES = ['system','trusted','sandbox-online','sandbox-offline'];

function ringClass(r){
  if(r===-1) return 'ring-master';
  return 'ring-' + r;
}

async function load(){
  const r = await fetch('/api/rbac/entities', {credentials:'same-origin'});
  if(!r.ok){ document.getElementById('msg').innerHTML =
    '<div class="msg err">Erreur API: '+r.status+'</div>'; return; }
  const data = await r.json();
  const tb = document.querySelector('#t tbody');
  tb.innerHTML = '';
  for(const e of data.entities){
    const acc = e.os_account;
    const sel = ZONES.map(z=>
      `<option value="${z}"${z===acc.zone?' selected':''}>${z}</option>`).join('');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${e.entity_id}</code></td>
      <td>${e.entity_type}</td>
      <td><span class="ring ${ringClass(e.ring_level)}">R${e.ring_level}</span></td>
      <td><select data-id="${e.entity_id}">${sel}</select></td>
      <td><span class="os-user">${acc.os_user||'-'}</span></td>
      <td><span class="os-group">${acc.os_group||'-'}</span></td>
      <td><input type="text" placeholder="raison" data-reason="${e.entity_id}"></td>
      <td><button data-save="${e.entity_id}">Save</button></td>`;
    tb.appendChild(tr);
  }
  document.querySelectorAll('[data-save]').forEach(btn=>{
    btn.onclick = ()=>save(btn.dataset.save);
  });
}

async function save(id){
  const sel = document.querySelector(`select[data-id="${id}"]`);
  const reasonEl = document.querySelector(`input[data-reason="${id}"]`);
  const body = {zone: sel.value, reason: reasonEl.value};
  const r = await fetch(`/api/rbac/entities/${id}`, {
    method:'PATCH', credentials:'same-origin',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  const msg = document.getElementById('msg');
  if(r.ok){
    msg.innerHTML = '<div class="msg ok">OK: '+id+' → '+sel.value+'</div>';
    reasonEl.value = '';
    loadAudit();
    load();
  } else {
    let detail = '';
    try { detail = (await r.json()).detail || ''; } catch(e){}
    msg.innerHTML = '<div class="msg err">'+r.status+' '+detail+'</div>';
  }
}

async function loadAudit(){
  const r = await fetch('/api/rbac/audit?limit=20', {credentials:'same-origin'});
  const tb = document.querySelector('#a tbody');
  /* AVANT : `if(!r.ok) return;` — un echec laissait le tableau vide, sans un mot,
     et un tableau vide se lit « c'est casse » alors qu'il peut simplement n'y
     avoir aucune modification enregistree. Mesure du 2026-09-18 : l'API repondait
     200 avec un journal VIDE (zero ligne en base) et l'ecran etait indistinguable
     d'une panne. On separe donc ILLISIBLE de VIDE. */
  if(!r.ok){
    tb.innerHTML = '<tr><td colspan="6">Journal illisible — HTTP '+r.status+
      ' — ce n\\'est PAS « aucune entrée »</td></tr>';
    return;
  }
  const data = await r.json();
  tb.innerHTML = '';
  if(!(data.log||[]).length){
    tb.innerHTML = '<tr><td colspan="6">Aucune modification enregistrée à ce jour — '+
      'le journal est vide, il n\\'est pas en panne.</td></tr>';
    return;
  }
  for(const e of (data.log||[])){
    const ts = new Date(e.ts*1000).toISOString().slice(0,19).replace('T',' ');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${ts}</td>
      <td><code>${e.entity_id}</code></td>
      <td>${e.actor}</td>
      <td>${e.old?.zone||'-'}</td>
      <td>${e.new?.zone||'-'}</td>
      <td>${(e.reason||'').slice(0,80)}</td>`;
    tb.appendChild(tr);
  }
}

async function creer(){
  const id = document.getElementById('n_id').value.trim();
  const msg = document.getElementById('msg');
  if(!id){ msg.innerHTML = '<div class="msg err">entity_id requis</div>'; return; }
  const r = await fetch('/api/rbac/entities', {
    method:'POST', credentials:'same-origin',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      entity_id: id,
      entity_type: document.getElementById('n_type').value,
      ring_level: parseInt(document.getElementById('n_ring').value, 10),
      reason: document.getElementById('n_reason').value
    })
  });
  if(r.ok){
    const d = await r.json();
    msg.innerHTML = '<div class="msg ok">Créé : '+d.entity_id+' → '+
      ((d.os_account&&d.os_account.zone)||'?')+'</div>';
    document.getElementById('n_id').value = '';
    document.getElementById('n_reason').value = '';
    load(); loadAudit();
  } else {
    /* Le motif du refus est AFFICHE : identifiant illisible, doublon, zone
       incoherente. Un formulaire qui echoue sans dire pourquoi fait recommencer
       a l'aveugle, et c'est la qu'on finit par forcer. */
    let detail = '';
    try { detail = (await r.json()).detail || ''; } catch(e){}
    msg.innerHTML = '<div class="msg err">'+r.status+' — '+detail+'</div>';
  }
}
document.getElementById('n_add').addEventListener('click', creer);
load();
loadAudit();
</script>
</body></html>
"""


@router.get("/rbac", response_class=HTMLResponse)
async def rbac_page():
    return HTMLResponse(_PAGE)
