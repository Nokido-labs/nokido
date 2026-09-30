#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_supervisor_reconcile.py — relance une boucle de waves calée.

Contexte : si le boot du supervisor (supervisor.ts :8765) cale après wave 1
(p.ex. collision CTRL_PORT AddrInUse), les services wave 2-6 ne sont jamais
spawnés -> cascade DOWN par les `deps` (DenoProxy:8000 absent -> tout le web
hub + régulation tombe). cf incident_services_down_cascade.

Ce script NE redémarre PAS LaForge-Master (ça tuerait la wave 1 saine et
risque la re-collision). Il pilote le supervisor VIVANT : POST
/supervisor/start/<name> pour chaque service wave 2-5 non-running. Le
supervisor attend lui-même les deps (waitForPort) -> on se contente d'émettre
les starts, il séquence. Idempotent (skip ce qui tourne déjà).

Pre-flight OBLIGATOIRE : la base RAG canonique doit résoudre en REALPATH sur
V: (forge_db_path). Sinon les daemons qui écrivent (Ingest/Consolidator)
taperaient le symlink C: read-only -> "readonly database" silencieux. Abort si
pas V:.

Exclus du reconcile (-> on-demand, lancés à la demande, pas au boot) :
  - NokidoSearxng / NokidoWatchAgent : conteneur Docker (daemon down).
  - NokidoEmbedTrigger : dep :5557 (EmbedWorkerIsolated disabled).
  - NokidoLlama* (sauf Keeper) : pool LLM géré séparément.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT)

BASE = "http://127.0.0.1:8765"

EXCLUDE = {
    "NokidoSearxng",      # Docker down -> on-demand
    "NokidoWatchAgent",   # dep Searxng:8080 -> on-demand
    "NokidoEmbedTrigger",  # dep :5557 disabled -> on-demand
}


def _token() -> str:
    """Jeton du superviseur, par le GUICHET seul (2b-6, 2026-09-28).

    Avant : l'environnement, puis le jeton MAITRE comme jeton superviseur de secours,
    puis le coffre machine en DIRECT (hors guichet, donc hors coffre reserve et hors
    recensement). Hors SYSTEM le guichet tait ce nom : le reconcile est un geste owner
    sous `ps_clm`, ou passe par le hub (`nokido_ensure_service`)."""
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore
        return get_secret("LAFORGE_SUPERVISOR_TOKEN") or ""
    except Exception:
        return ""


def _call(path: str, method: str = "GET", timeout: float = 10.0):
    req = urllib.request.Request(BASE + path, method=method)
    # Lu a l'APPEL, jamais a l'import : importer ce module ne lit aucun secret.
    jeton = _token()
    if jeton:
        req.add_header("authorization", jeton)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - report and continue
        return -1, str(exc)


def _preflight_db() -> None:
    from nokido_agent.app import forge_db_path as dbp  # type: ignore

    db = dbp.db_path()
    drive = os.path.splitdrive(db)[0].upper()
    if drive != "V:" or not os.path.exists(db):
        print(f"ABORT preflight: DB not on V: -> {db} "
              f"(drive={drive}, exists={os.path.exists(db)})")
        sys.exit(2)
    print(f"[preflight] DB OK -> {db} ({os.path.getsize(db) // (1024 * 1024)} MB)")


def main() -> int:
    _preflight_db()

    st, body = _call("/supervisor/status")
    if st != 200:
        print(f"ABORT: supervisor status {st}: {body[:200]}")
        return 3
    state = json.loads(body).get("services", {})

    llama_skip = {
        n for n in state
        if n.startswith("NokidoLlama") and n != "NokidoLlamaKeeper"
    }

    targets = []
    for name, info in state.items():
        wave = int(info.get("wave", 0) or 0)
        if wave < 2 or wave > 5:
            continue
        if name in EXCLUDE or name in llama_skip:
            continue
        if info.get("status") == "running":
            continue
        targets.append((wave, name))
    targets.sort()

    print(f"[reconcile] {len(targets)} service(s) wave 2-5 à démarrer "
          f"(ordre wave; supervisor attend les deps)")
    for wave, name in targets:
        st, _b = _call(f"/supervisor/service/start/{name}", "POST", timeout=5.0)
        print(f"  w{wave} start {name} -> {st}")
        time.sleep(0.2)

    # Laisser le temps aux dep-waiters (DenoProxy:8000 -> WebHub) de remonter.
    print("[reconcile] settle 12s...")
    time.sleep(12)

    st, body = _call("/supervisor/status")
    final = json.loads(body).get("services", {}) if st == 200 else {}
    up = sorted(n for n, i in final.items() if i.get("status") == "running")
    down = sorted(
        n for n, i in final.items()
        if i.get("status") != "running" and 2 <= int(i.get("wave", 0) or 0) <= 6
    )
    print(f"[done] running={len(up)}")
    print(f"[done] still_down(w2-6)={down}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
