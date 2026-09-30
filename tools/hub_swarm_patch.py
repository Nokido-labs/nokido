"""
tools/hub_swarm_patch.py — Patch Hub : route /swarm + /team
=============================================================
Expose l état du swarm et la config team en temps réel via le Hub.
Appliqué automatiquement au démarrage via hub_rt_patch.py.

Routes ajoutées :
  GET /swarm         — état state machine + queue + agents
  GET /swarm/events  — N derniers events depuis events.db
  GET /team          — config SwarmTeam courante (participants actifs)
  POST /team/toggle  — activer/désactiver un participant
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def _swarm_state() -> dict:
    """Lit l état swarm depuis live_bridge (mmap) ou fallback bridge_state."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.live_bridge import bridge

        lb = bridge.snapshot().get("json", {})
        return {
            "state": lb.get("swarm.state", "IDLE"),
            "active_agent": lb.get("swarm.active_agent", ""),
            "seq": lb.get("swarm.seq", 0),
            "ts": lb.get("swarm.ts", time.time()),
            "source": "live_bridge",
        }
    except Exception:
        pass
    # Fallback : lire events.db dernier event swarm
    try:
        db = ROOT / "sandbox" / "events.db"
        conn = sqlite3.connect(str(db), timeout=3)
        row = conn.execute(
            "SELECT agent_id, event_type, target, timecode FROM event_log "
            "WHERE event_type='state_transition' ORDER BY sequence_id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            return {"state": row[2], "active_agent": row[0], "ts": row[3], "source": "events.db"}
    except Exception:
        pass
    return {"state": "UNKNOWN", "active_agent": "", "source": "fallback"}


def _swarm_events(n: int = 20) -> list:
    try:
        db = ROOT / "sandbox" / "events.db"
        conn = sqlite3.connect(str(db), timeout=3)
        rows = conn.execute(
            "SELECT timecode,sequence_id,agent_id,event_type,target,status "
            "FROM event_log ORDER BY sequence_id DESC LIMIT ?",
            (n,),
        ).fetchall()
        conn.close()
        return [
            {"ts": r[0], "seq": r[1], "agent": r[2], "type": r[3], "target": r[4], "status": r[5]}
            for r in rows
        ]
    except Exception as e:
        return [{"error": str(e)[:80]}]


def _team_config() -> dict:
    cfg = ROOT / "sandbox" / "swarm_team_config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            # Ne retourner que les participants actifs + métadonnées légères
            actives = [
                {
                    "id": p["id"],
                    "label": p["label"],
                    "kind": p["kind"],
                    "priority": p["priority"],
                    "async_call": p["async_call"],
                }
                for p in data.get("participants", [])
                if p.get("active")
            ]
            return {
                "session_id": data.get("session_id", "?"),
                "status": data.get("status", "draft"),
                "active_count": len(actives),
                "active": actives,
            }
        except Exception as e:
            return {"error": str(e)[:80]}
    return {"active_count": 0, "active": [], "status": "no_config"}


def patch_app(app, event_queue=None, db=None):
    """Injecte les routes /swarm et /team dans l application Hub FastAPI."""
    try:
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except ImportError:
        return  # Hub non FastAPI, skip

    @app.get("/swarm")
    async def swarm_status_route():
        state = _swarm_state()
        events = _swarm_events(5)
        cfg = _team_config()
        return JSONResponse(
            {
                "ok": True,
                "swarm": state,
                "team": cfg,
                "recent_events": events,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )

    @app.get("/swarm/events")
    async def swarm_events_route(n: int = 20):
        return JSONResponse(
            {
                "ok": True,
                "events": _swarm_events(min(n, 100)),
            }
        )

    @app.get("/team")
    async def team_route():
        return JSONResponse(_team_config())

    @app.post("/team/toggle")
    async def team_toggle_route(request: Request):
        try:
            body = await request.json()
            pid = str(body.get("id", "")).strip()
            if not pid:
                return JSONResponse({"ok": False, "error": "id requis"}, status_code=400)
            cfg_path = ROOT / "sandbox" / "swarm_team_config.json"
            if not cfg_path.exists():
                return JSONResponse({"ok": False, "error": "no team config"}, status_code=404)
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            found = False
            for p in data.get("participants", []):
                if p["id"] == pid:
                    p["active"] = not p.get("active", False)
                    found = True
                    break
            if not found:
                return JSONResponse(
                    {"ok": False, "error": "participant not found"}, status_code=404
                )
            cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return JSONResponse({"ok": True, "id": pid})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)[:120]}, status_code=500)
