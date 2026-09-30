from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from typing import List, Dict, Any
import uuid
import time
import json
from pathlib import Path
import sqlite3

from app.netcfg.visio import VisioParser
from app.netcfg.core import Equipment, VendorDetector

router = APIRouter(prefix="/netcfg", tags=["netcfg"])

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "recon_silo" / "recon_data" / "recon.db"


def get_db():
    """Connexion a la base d'inventaire, ou un 503 QUI DIT POURQUOI.

    Une dependance FastAPI s'execute AVANT le corps de la route : un `sqlite3.connect`
    nu y leve `OperationalError: unable to open database file`, et l'exception remonte
    en 500 opaque — le try/except de `get_inventory` ne peut PAS l'attraper, puisqu'on
    n'entre jamais dans la fonction. Mesure 2026-08-26 : c'est ce qui a fait tomber
    quatre tests d'interface en CI, la ou le compte du runner ne peut pas ouvrir cette
    base, alors que la route paraissait protegee.

    `mode=ro` : cette UI est en LECTURE SEULE (le module le dit lui-meme). Ouvrir en
    ecriture CREERAIT une base vide sur un chemin absent, et un inventaire vide se lit
    comme un reseau vide — un faux plus couteux qu'une erreur."""
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH.as_posix(), uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=("base d'inventaire indisponible (%s) : %s — ce n'est pas un "
                    "inventaire vide, c'est une base illisible ou absente"
                    % (DB_PATH.name, exc)),
        ) from exc
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


_NETCFG_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Netcfg — Nokido</title>
<script src="/static/tailwind.min.js"></script>
<script src="/static/lucide.min.js"></script>
<style>body{background:#0d1117;color:#c9d1d9;font-family:sans-serif;} .card{background:#161b22;border:1px solid #30363d;border-radius:6px;}</style>
</head>
<body class="p-6">
<div class="flex items-center gap-3 mb-4">
  <h1 class="text-xl font-bold text-cyan-400">🔌 Network Config</h1>
  <a href="http://127.0.0.1:7500" target="_blank" class="text-xs text-slate-400 border border-slate-700 px-2 py-1 rounded hover:border-cyan-700">Netcfg UI :7500 ↗</a>
  <a href="/netcfg/inventory" target="_blank" class="text-xs text-slate-400 border border-slate-700 px-2 py-1 rounded hover:border-cyan-700">API JSON ↗</a>
</div>
<div id="status" class="text-sm text-slate-500 mb-4">Chargement inventaire...</div>
<div class="card overflow-hidden">
  <table class="w-full text-sm" id="inv-table">
    <thead><tr class="border-b border-slate-700 text-xs text-slate-500">
      <th class="text-left p-3">Hostname</th>
      <th class="text-left p-3">IP</th>
      <th class="text-left p-3">Vendor</th>
      <th class="text-left p-3">Model</th>
      <th class="text-left p-3">OS</th>
      <th class="text-left p-3">Statut</th>
    </tr></thead>
    <tbody id="inv-body"><tr><td colspan="6" class="p-4 text-slate-600 text-center">Chargement...</td></tr></tbody>
  </table>
</div>
<script>
fetch('/netcfg/inventory').then(r => r.json()).then(rows => {
  document.getElementById('status').textContent = rows.length + ' équipement(s) actif(s)';
  const tbody = document.getElementById('inv-body');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="p-4 text-slate-600 text-center">Aucun équipement dans la base</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => `
    <tr class="border-b border-slate-800 hover:bg-slate-800/30">
      <td class="p-3 text-cyan-300 font-mono">\${r.hostname||'-'}</td>
      <td class="p-3 font-mono text-slate-300">\${r.ip_address||r.ip||'-'}</td>
      <td class="p-3 text-slate-400">\${r.vendor||'-'}</td>
      <td class="p-3 text-slate-500 text-xs">\${r.model||'-'}</td>
      <td class="p-3 text-slate-500 text-xs">\${r.os_version||'-'}</td>
      <td class="p-3"><span class="px-2 py-0.5 text-xs bg-green-900 text-green-300 rounded">\${r.status||'active'}</span></td>
    </tr>`).join('');
}).catch(e => {
  document.getElementById('status').textContent = '✗ Erreur: ' + e;
  document.getElementById('inv-body').innerHTML = '<tr><td colspan="6" class="p-4 text-red-400 text-center">Erreur chargement — voir console</td></tr>';
});
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def netcfg_index():
    """Dashboard HTML inventaire réseau."""
    return HTMLResponse(_NETCFG_HTML)


@router.get("/inventory")
def get_inventory(db: sqlite3.Connection = Depends(get_db)):
    """Liste les équipements réseau gérés.

    TROIS états, jamais deux. Le SELECT nu rendait un 500 « Internal Server Error »
    qui ne distinguait pas « aucun équipement » de « table absente » ni de « base
    illisible » — et un inventaire vide se lit comme un réseau vide. Mesuré le
    2026-08-26 : c'était le seul 500 franc du portail, et la cause exacte demandait
    d'ouvrir la base à la main.

    `def` et non `async def` : la fonction fait du SQLite bloquant. En `async` elle
    s'exécuterait dans la boucle d'événements et gèlerait le serveur entier
    (cf. `tools/forge_route_async_bloquante.py`).
    """
    try:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM netcfg_equipment WHERE status = 'active'")
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.OperationalError as exc:
        motif = str(exc)
        if "no such table" in motif:
            detail = ("inventaire non initialise : la table netcfg_equipment n'existe "
                      "pas encore dans %s" % DB_PATH.name)
        elif "unable to open" in motif or "readonly" in motif:
            detail = ("base d'inventaire ILLISIBLE pour le compte du portail (%s) — "
                      "ce n'est pas un inventaire vide, c'est un acces refuse"
                      % DB_PATH)
        else:
            detail = "base d'inventaire inutilisable : %s" % motif
        raise HTTPException(status_code=503, detail=detail) from exc


@router.post("/preview")
async def post_preview(visio_path: str):
    """
    Analyse un fichier Visio et retourne le plan de déploiement (diff).
    C'est une opération en lecture seule (dry-run).
    """
    try:
        parser = VisioParser(visio_path)
        equipments = parser.parse_minimal()
        return {"status": "success", "equipments_found": len(equipments), "data": equipments}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deploy")
async def post_deploy(run_id: str = None):
    """
    Lance un workflow de déploiement.
    Retourne un flux SSE pour le suivi des étapes et des gates.
    """
    if not run_id:
        run_id = str(uuid.uuid4())

    async def event_generator():
        # Simulation du workflow (Step 6.2 du design)
        steps = ["backup", "diff_review", "translate", "cmd_review", "push", "post_push"]

        yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"

        for i, step in enumerate(steps):
            time.sleep(1)  # Simulation processing
            yield f"data: {
                json.dumps(
                    {
                        'type': 'node_state_change',
                        'run_id': run_id,
                        'node_id': step,
                        'from_state': 'pending',
                        'to_state': 'running',
                    }
                )
            }\n\n"

            # Si c'est une gate, on simule l'attente (en réel, on attendrait un POST de validation)
            if "review" in step or "post" in step:
                yield f"data: {
                    json.dumps(
                        {
                            'type': 'node_state_change',
                            'run_id': run_id,
                            'node_id': step,
                            'from_state': 'running',
                            'to_state': 'gate_waiting',
                            'payload': {'gate': step},
                        }
                    )
                }\n\n"
                time.sleep(1)

            yield f"data: {
                json.dumps(
                    {
                        'type': 'node_state_change',
                        'run_id': run_id,
                        'node_id': step,
                        'from_state': 'running' if 'review' not in step else 'gate_waiting',
                        'to_state': 'done',
                    }
                )
            }\n\n"

        yield f"data: {json.dumps({'type': 'run_completed', 'run_id': run_id})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/runs/{run_id}")
async def get_run_audit(run_id: str, db: sqlite3.Connection = Depends(get_db)):
    """Récupère l'audit trail d'un run spécifique."""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM netcfg_deploy_log WHERE run_id = ? ORDER BY step_index", (run_id,))
    return [dict(row) for row in cursor.fetchall()]
