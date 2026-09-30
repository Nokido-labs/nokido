"""
forge_synaptic_plasticity.py — Plasticité synaptique RAG (Phase 6 Symbiose)

Couche d'auto-amélioration au-dessus de forge_rag_qualify.apply_trust_weight().

Mécanismes biomimétiques :
- synaptic_weight : poids d'usage (renforcé/diminué par feedback)
- access_count   : nb fois accédé en search
- dynamic_threshold : seuil global qui s'auto-ajuste
- active_forgetting : purge si poids < 0.4

Stockage : rag_chunks.meta JSON (synaptic_weight, access_count) + table synaptic_metrics.

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:plasticity|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

# Bornes (clip pour stabilité)
WEIGHT_MIN = 0.0
WEIGHT_MAX = 1.5
WEIGHT_DEFAULT = 1.0
WEIGHT_REINFORCE = 0.05  # +5% si helpful
WEIGHT_PENALTY = 0.15  # -15% si false positive
PURGE_THRESHOLD = 0.4  # active forgetting si < 0.4

# Threshold dynamique global
THRESHOLD_MIN = 0.60
THRESHOLD_MAX = 0.90
THRESHOLD_DEFAULT = 0.75
THRESHOLD_DELTA_DOWN = 0.01  # si succès → seuil baisse
THRESHOLD_DELTA_UP = 0.02  # si échec → seuil monte

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS synaptic_metrics (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS synaptic_feedback_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL,
    helpful INTEGER NOT NULL,
    agent TEXT,
    context TEXT,
    weight_before REAL,
    weight_after REAL,
    threshold_after REAL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_chunk ON synaptic_feedback_log(chunk_id);
CREATE INDEX IF NOT EXISTS idx_feedback_ts ON synaptic_feedback_log(ts);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in _SCHEMA_DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


def _get_metric(conn: sqlite3.Connection, key: str, default: float) -> float:
    row = conn.execute("SELECT value FROM synaptic_metrics WHERE key=?", (key,)).fetchone()
    return float(row[0]) if row else default


def _set_metric(conn: sqlite3.Connection, key: str, value: float) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO synaptic_metrics (key, value, updated_at) VALUES (?,?,?)",
        (key, float(value), time.time()),
    )


def _meta_get_weight(meta_json: Optional[str]) -> float:
    if not meta_json:
        return WEIGHT_DEFAULT
    try:
        m = json.loads(meta_json)
        return float(m.get("synaptic_weight", WEIGHT_DEFAULT))
    except Exception:
        return WEIGHT_DEFAULT


def _meta_set(meta_json: Optional[str], updates: Dict[str, Any]) -> str:
    try:
        m = json.loads(meta_json) if meta_json else {}
    except Exception:
        m = {}
    m.update(updates)
    return json.dumps(m, ensure_ascii=False)


# ============================================================
# API publique
# ============================================================
def get_dynamic_threshold(db_path: Optional[Path] = None) -> float:
    db = Path(db_path) if db_path else DEFAULT_DB
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)
    val = _get_metric(conn, "dynamic_threshold", THRESHOLD_DEFAULT)
    conn.close()
    return val


def get_global_metrics(db_path: Optional[Path] = None) -> Dict[str, float]:
    db = Path(db_path) if db_path else DEFAULT_DB
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)
    out = {
        "dynamic_threshold": _get_metric(conn, "dynamic_threshold", THRESHOLD_DEFAULT),
        "total_queries": _get_metric(conn, "total_queries", 0),
        "successful_matches": _get_metric(conn, "successful_matches", 0),
        "false_positives": _get_metric(conn, "false_positives", 0),
        "purged_count": _get_metric(conn, "purged_count", 0),
    }
    if out["total_queries"] > 0:
        out["success_ratio"] = round(out["successful_matches"] / out["total_queries"], 3)
        out["fp_ratio"] = round(out["false_positives"] / out["total_queries"], 3)
    conn.close()
    return out


def record_query(matched: bool, db_path: Optional[Path] = None) -> None:
    """Incrémente compteurs. matched=True si un chunk a passé le seuil."""
    db = Path(db_path) if db_path else DEFAULT_DB
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)
    cur = _get_metric(conn, "total_queries", 0) + 1
    _set_metric(conn, "total_queries", cur)
    if matched:
        cur_m = _get_metric(conn, "successful_matches", 0) + 1
        _set_metric(conn, "successful_matches", cur_m)
    conn.commit()
    conn.close()


def feedback_loop(
    chunk_id: str,
    helpful: bool,
    agent: str = "",
    context: str = "",
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Boucle de feedback synaptique.

    Args:
        chunk_id: id du rag_chunk à renforcer/affaiblir
        helpful: True si LLM a utilisé l'info pour résoudre, False sinon
        agent: agent qui donne le feedback (audit)
        context: notes optionnelles

    Returns:
        {ok, weight_before, weight_after, threshold_after, purged}
    """
    db = Path(db_path) if db_path else DEFAULT_DB
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)

    row = conn.execute("SELECT meta, quality_score FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"chunk_id '{chunk_id}' not found"}

    weight_before = _meta_get_weight(row[0])
    purged = False

    if helpful:
        weight_after = min(WEIGHT_MAX, weight_before + WEIGHT_REINFORCE)
        # Threshold legèrement baissé (système gagne confiance)
        thr = _get_metric(conn, "dynamic_threshold", THRESHOLD_DEFAULT)
        thr = max(THRESHOLD_MIN, thr - THRESHOLD_DELTA_DOWN)
        _set_metric(conn, "dynamic_threshold", thr)
    else:
        weight_after = max(WEIGHT_MIN, weight_before - WEIGHT_PENALTY)
        thr = _get_metric(conn, "dynamic_threshold", THRESHOLD_DEFAULT)
        thr = min(THRESHOLD_MAX, thr + THRESHOLD_DELTA_UP)
        _set_metric(conn, "dynamic_threshold", thr)
        cur_fp = _get_metric(conn, "false_positives", 0) + 1
        _set_metric(conn, "false_positives", cur_fp)

    # Update meta + quality_score (couple lié au weight)
    new_meta = _meta_set(
        row[0],
        {
            "synaptic_weight": weight_after,
            "last_feedback_at": time.time(),
            "last_helpful": bool(helpful),
        },
    )
    new_quality = round(weight_after / WEIGHT_MAX, 3)  # normalisé 0-1
    conn.execute(
        "UPDATE rag_chunks SET meta=?, quality_score=?, updated_at=? WHERE id=?",
        (new_meta, new_quality, int(time.time()), chunk_id),
    )

    # Active forgetting (purge si poids effondré)
    if weight_after <= PURGE_THRESHOLD and not helpful:
        try:
            _ancien = conn.execute("SELECT text FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
            conn.execute("DELETE FROM rag_chunks WHERE id=?", (chunk_id,))
            try:
                # `WHERE id=?` visait une colonne qui N'EXISTE PAS dans rag_fts : l'erreur
                # etait avalee et la ligne lexicale restait orpheline a chaque oubli actif.
                # Purge par MATCH sur l'ancien texte, jamais par balayage (2026-09-27).
                if _ancien is not None:
                    try:
                        from nokido_agent.app.forge_db_path import purger_fts
                    except ImportError:  # lance par chemin : app/ est sys.path[0]
                        from forge_db_path import purger_fts
                    purger_fts(conn, [(chunk_id, _ancien[0])])
            except Exception as e:  # noqa: BLE001
                import logging  # ce module n'a pas de logger propre

                logging.getLogger(__name__).debug(f"[plasticity] purge FTS KO chunk={chunk_id}: {e}")
            cur_p = _get_metric(conn, "purged_count", 0) + 1
            _set_metric(conn, "purged_count", cur_p)
            purged = True
        except Exception:
            pass

    # Log feedback
    conn.execute(
        "INSERT INTO synaptic_feedback_log (chunk_id, helpful, agent, context, weight_before, weight_after, threshold_after, ts) VALUES (?,?,?,?,?,?,?,?)",
        (chunk_id, 1 if helpful else 0, agent, context[:500], weight_before, weight_after, thr, time.time()),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "chunk_id": chunk_id,
        "weight_before": round(weight_before, 4),
        "weight_after": round(weight_after, 4),
        "threshold_after": round(thr, 4),
        "purged": purged,
        "helpful": helpful,
    }


def synaptic_score(base_score: float, chunk_meta: Optional[str]) -> float:
    """Applique le synaptic_weight au score de similarité brute.

    Combiné à apply_trust_weight (forge_rag_qualify) pour score final.
    """
    w = _meta_get_weight(chunk_meta)
    return round(base_score * w, 6)


def filter_by_dynamic_threshold(
    candidates: list, score_key: str = "score", db_path: Optional[Path] = None
) -> Tuple[list, float]:
    """Filtre candidats selon threshold dynamique courant.

    Args:
        candidates: list de dicts avec score_key
        score_key: clé du score dans chaque dict

    Returns:
        (filtered, threshold_used)
    """
    thr = get_dynamic_threshold(db_path)
    return [c for c in candidates if c.get(score_key, 0) >= thr], thr


def reset_metrics(db_path: Optional[Path] = None) -> None:
    """Reset compteurs globaux (gardé feedback_log)."""
    db = Path(db_path) if db_path else DEFAULT_DB
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)
    conn.execute("DELETE FROM synaptic_metrics")
    _set_metric(conn, "dynamic_threshold", THRESHOLD_DEFAULT)
    conn.commit()
    conn.close()


# ============================================================
# CLI debug
# ============================================================
if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("Usage:")
        print("  forge_synaptic_plasticity.py --metrics                      # global stats")
        print("  forge_synaptic_plasticity.py --feedback <chunk_id> <0|1>   # send feedback")
        print("  forge_synaptic_plasticity.py --threshold                   # current dynamic threshold")
        print("  forge_synaptic_plasticity.py --reset                       # reset counters")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "--metrics":
        print(json.dumps(get_global_metrics(), indent=2))
    elif cmd == "--threshold":
        print(get_dynamic_threshold())
    elif cmd == "--feedback" and len(sys.argv) >= 4:
        cid = sys.argv[2]
        hp = sys.argv[3] in ("1", "true", "yes", "helpful")
        r = feedback_loop(cid, hp, agent="CLI")
        print(json.dumps(r, indent=2))
    elif cmd == "--reset":
        reset_metrics()
        print("metrics reset")
    else:
        print(f"unknown command: {cmd}")
