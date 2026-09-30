"""
hub_live_patch.py — Monkey-patch temps reel pour nokido_hub
============================================================
Importe ce module UNE FOIS au demarrage du Hub.
Override /health et /metrics pour lire live_bridge.
Override _event_worker pour utiliser forge_db persistant.

Usage dans nokido_hub.py (ajouter a la fin des imports) :
    try:
        import hub_live_patch  # noqa
    except Exception:
        pass
"""

from __future__ import annotations

import queue as _queue
import threading
import time
from pathlib import Path

# ── Override _event_worker ────────────────────────────────────────────────────


def _patched_event_worker(event_queue, db_path):
    """Remplace l event_worker original — forge_db persistant, zéro connect/close."""
    BATCH = 20
    EVERY = 2.0
    while True:
        batch, deadline = [], time.monotonic() + EVERY
        while len(batch) < BATCH:
            rem = deadline - time.monotonic()
            if rem <= 0:
                break
            try:
                batch.append(event_queue.get(timeout=min(rem, 0.1)))
            except _queue.Empty:
                if time.monotonic() >= deadline:
                    break
        if not batch:
            continue
        try:
            from nokido_agent.app.forge_db import db_evt as _de

            seq = (_de.scalar("SELECT COALESCE(MAX(sequence_id),0) FROM event_log") or 0) + 1
            rows = [
                (
                    ev["ts"],
                    seq + i,
                    "hub",
                    ev["agent"],
                    "tool_call",
                    ev["tool"],
                    ev["payload"],
                    "",
                    "",
                    "ok",
                )
                for i, ev in enumerate(batch)
            ]
            _de.executemany(
                "INSERT INTO event_log "
                "(timecode,sequence_id,session_id,agent_id,event_type,"
                "target,payload,prev_hash,new_hash,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        except Exception:
            pass


# ── Patch /health et /metrics via registre d app Starlette ────────────────────


def patch_app(app, event_queue, db_path):
    """
    Appeler apres creation de l app Starlette.
    Remplace les routes /health et /metrics par des versions live_bridge.
    """
    try:
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def health_rt(request: Request):
            try:
                from nokido_agent.app.live_bridge import bridge as _br

                seq = _br.seq()
                tasks = [t for t in _br.tasks_active() if t["status"] in ("pend", "run")]
                agents = {
                    a: d.get("status")
                    for a, d in (_br.json_get("hb") or {}).get("agents", {}).items()
                }
            except Exception:
                seq, tasks, agents = 0, [], {}
            return JSONResponse(
                {
                    "status": "ok",
                    "hub": "Nokido v17",
                    "bridge_seq": seq,
                    "tasks_active": len(tasks),
                    "agents": agents,
                }
            )

        async def metrics_rt(request: Request):
            try:
                from nokido_agent.app.live_bridge import bridge as _br

                snap = _br.snapshot()
                tasks = snap.get("tasks", [])
            except Exception:
                snap, tasks = {}, []
            rag_count = -1
            try:
                from nokido_agent.app.forge_db import db as _db

                rag_count = _db.scalar("SELECT COUNT(*) FROM rag_chunks") or -1
            except Exception:
                pass
            # Swarm state depuis live_bridge ou events.db
            swarm_state = "IDLE"
            swarm_seq = 0
            team_active = 0
            try:
                lb_json = snap.get("json", {})
                swarm_state = lb_json.get("swarm.state", "IDLE")
                swarm_seq = lb_json.get("swarm.seq", 0)
            except Exception:
                pass
            try:
                import json as _json

                _cfg = Path(__file__).parent.parent / "sandbox" / "swarm_team_config.json"
                if _cfg.exists():
                    _data = _json.loads(_cfg.read_text())
                    team_active = sum(1 for p in _data.get("participants", []) if p.get("active"))
            except Exception:
                pass
            return JSONResponse(
                {
                    "bridge_seq": snap.get("seq", 0),
                    "tasks_active": len([t for t in tasks if t["status"] in ("pend", "run")]),
                    "tasks": tasks[:10],
                    "rag_chunks": rag_count,
                    "queue_size": event_queue.qsize(),
                    "uptime_s": int(time.monotonic()),
                    "swarm_state": swarm_state,
                    "swarm_seq": swarm_seq,
                    "team_active_count": team_active,
                }
            )

        # Remplacer les routes existantes
        new_routes = []
        for route in app.routes:
            path = getattr(route, "path", "")
            if path == "/health":
                new_routes.append(Route("/health", health_rt, methods=["GET"]))
            elif path == "/metrics":
                new_routes.append(Route("/metrics", metrics_rt, methods=["GET"]))
            else:
                new_routes.append(route)
        app.routes = new_routes
        print("[hub_live_patch] /health + /metrics patched -> live_bridge", flush=True)
    except Exception as e:
        print("[hub_live_patch] patch_app error:", e, flush=True)

    # Redemarrer l event_worker avec forge_db
    try:
        t = threading.Thread(
            target=_patched_event_worker,
            args=(event_queue, db_path),
            name="HubEventWorker-RT",
            daemon=True,
        )
        t.start()
        print("[hub_live_patch] _event_worker remplace -> forge_db persistant", flush=True)
    except Exception as e:
        print("[hub_live_patch] event_worker error:", e, flush=True)
