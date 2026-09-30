# -*- coding: utf-8 -*-
"""forge_events_wait.py — attente bloquante d'événements (jobs) pour SCRIPTS DÉPORTÉS.

MOTIF (hermes-agent `events_wait`, veille 2026-06-17) — mais rendu SÛR pour Nokido :
le BLOCAGE doit vivre dans un script déporté (lancé via `run_job` = process séparé),
JAMAIS sur l'event-loop du hub. Un `time.sleep` sur la boucle asyncio = wedge (/health
mort → restart ; incident vécu). C'est pourquoi ceci N'EST PAS un verbe MCP bloquant.

Décomposition des attentes Nokido :
  - côté AGENT (Claude/Gemini)  : déjà couvert par `run_job notify_agent=<agent>` →
    poussé sur l'inbox à la fin (NON bloquant). Ne pas poller `job_status` en boucle.
  - côté SCRIPT déporté orchestrateur : utilise ce module pour lancer des sous-jobs
    et attendre leur fin → pipeline multi-étapes serveur-side, 0 round-trip contexte.

RÉUTILISE `forge_job_runner.read_job` (source de vérité de l'état job sur disque).

API :
  wait_for_job(job_id, timeout=600, poll=1.0)  -> dict   (état final, ou timeout)
  wait_for_jobs(job_ids, timeout=600, poll=1.0) -> dict   {job_id: état} (tous)
"""
from __future__ import annotations

import time

__FORGE_COLOR__ = "cerveau/event_stream : attente bloquante d'evenements pour scripts deportes"
__FORGE_TAGS__ = "#FORGE:[score:84|agent:events-wait|risk:0.10|color:GREEN]"


def _read(job_id: str) -> dict:
    from nokido_agent.app.forge_job_runner import read_job

    st = read_job(job_id)
    return st if isinstance(st, dict) else {"job_id": job_id, "status": "unknown", "raw": st}


def wait_for_job(job_id: str, timeout: int = 600, poll: float = 1.0) -> dict:
    """Bloque jusqu'à ce que le job soit 'done' ou que `timeout` (s) expire.

    À appeler DANS un script déporté (jamais sur l'event-loop du hub).
    Retourne l'état final (+ 'waited': True) ou le dernier état (+ 'timeout': True).
    """
    deadline = time.monotonic() + max(1, int(timeout))
    last: dict = {"job_id": job_id, "status": "unknown"}
    while time.monotonic() < deadline:
        last = _read(job_id)
        if last.get("status") == "done":
            last["waited"] = True
            return last
        time.sleep(max(0.1, float(poll)))
    last["waited"] = False
    last["timeout"] = True
    return last


def wait_for_jobs(job_ids, timeout: int = 600, poll: float = 1.0) -> dict:
    """Bloque jusqu'à ce que TOUS les jobs soient 'done' ou `timeout` expire.

    Retourne {job_id: état}. Les jobs non finis au timeout ont status='timeout'.
    """
    deadline = time.monotonic() + max(1, int(timeout))
    pending = list(job_ids)
    done: dict = {}
    while pending and time.monotonic() < deadline:
        for jid in list(pending):
            st = _read(jid)
            if st.get("status") == "done":
                st["waited"] = True
                done[jid] = st
                pending.remove(jid)
        if pending:
            time.sleep(max(0.1, float(poll)))
    for jid in pending:
        done[jid] = {"job_id": jid, "status": "timeout", "waited": False}
    return done
