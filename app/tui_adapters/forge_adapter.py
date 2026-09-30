"""Adapter Forge — vue consolidée AMI / skill_curator / GOAP / training."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
RAG_DB = ROOT / "RAG" / "embeddings.db"
TRACES_DB = ROOT / "RAG" / "execution_traces.db"
SANDBOX = ROOT / "sandbox"


def top_curated_skills(limit: int = 8, db_path: Optional[Path] = None) -> list[dict]:
    """Top curated_skills par score décroissant."""
    db = db_path if db_path is not None else RAG_DB
    if not db.exists():
        return []
    try:
        c = sqlite3.connect(str(db), timeout=5)
        rows = c.execute("SELECT id, text, meta FROM rag_chunks WHERE domain='curated_skills' LIMIT 100").fetchall()
        c.close()
    except Exception:
        return []
    out: list[dict] = []
    for r in rows:
        try:
            meta = json.loads(r[2] or "{}")
        except Exception:
            meta = {}
        out.append(
            {
                "id": r[0],
                "score": float(meta.get("score") or 0),
                "task": meta.get("task_type", "?"),
                "action": meta.get("action_type", "?"),
                "uses": int(meta.get("uses") or 0),
                "rate": float(meta.get("success_rate") or 0),
            }
        )
    out.sort(key=lambda x: -x["score"])
    return out[: max(1, min(int(limit), 50))]


def ami_traces_summary(db_path: Optional[Path] = None) -> dict:
    """Compteurs traces + success rate global."""
    db = db_path if db_path is not None else TRACES_DB
    if not db.exists():
        return {"present": False}
    try:
        c = sqlite3.connect(str(db), timeout=5)
        total = c.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        ok = c.execute("SELECT SUM(success) FROM traces").fetchone()[0] or 0
        last_24 = c.execute("SELECT COUNT(*) FROM traces WHERE ts > strftime('%s','now') - 86400").fetchone()[0]
        c.close()
    except Exception:
        return {"present": False}
    return {
        "present": True,
        "total": total,
        "successes": ok,
        "rate": round(ok / total, 3) if total else 0,
        "last_24h": last_24,
    }


def goap_state(path: Optional[Path] = None) -> dict:
    """Lit sandbox/goap_state.json si présent (plans/goals en cours)."""
    p = path if path is not None else SANDBOX / "goap_state.json"
    if not p.exists():
        return {"present": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"present": True, "data": d}
    except Exception as e:
        return {"present": True, "error": str(e)[:120]}


def night_trainer_state(path: Optional[Path] = None) -> dict:
    """Lit dernier heartbeat night/offline trainer."""
    out: dict[str, dict] = {}
    for name, fname in [("night", "night_trainer.heartbeat"), ("offline", "offline_trainer.heartbeat")]:
        p = path / fname if path else SANDBOX / fname
        if not p.exists():
            out[name] = {"present": False}
            continue
        try:
            out[name] = {"present": True, "data": json.loads(p.read_text(encoding="utf-8"))}
        except Exception as e:
            out[name] = {"present": True, "error": str(e)[:80]}
    return out
