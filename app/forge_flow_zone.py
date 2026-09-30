"""
forge_flow_zone.py — Pierre-Yves Oudeyer (Inria) Flow Zone

Théorie : un agent autonome n'a pas d'objectif, il cherche la zone de
difficulté optimale (ni trop facile = ennui, ni trop dur = frustration).
Optimisation du *learning progress* (apprentissage qui progresse).

Application Nokido :
- Mesure progress = derivée de p_success(method, target_class) sur fenêtre glissante
- Ennui : progress proche 0 + p_success proche 1 (déjà maîtrisé)
- Frustration : progress négatif + p_success faible (régression)
- Flow : progress positif + p_success milieu (apprentissage actif)

Le routeur doit prioriser les tâches en flow zone — celles où l'agent
apprend le plus vite. Skip les routinières + les impossibles.

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:flow_zone|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

# Calibration
WINDOW_RECENT = 10  # n derniers obs pour calculer progress
WINDOW_OLD = 20  # n obs précédents pour comparaison
PROGRESS_HIGH = 0.10  # > 10% amélioration = flow
PROGRESS_LOW = -0.05  # < -5% = régression
SUCCESS_BOREDOM = 0.90  # p_success > 0.9 = ennuyeux
SUCCESS_FRUSTRATION = 0.20  # p_success < 0.2 = trop dur


def _recent_obs(method: str, target_class: str, limit: int) -> List[int]:
    """Retourne les N derniers résultats (1=succès, 0=échec) chronologique."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_inference_surprises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method TEXT, target_class TEXT,
                predicted_p_success REAL, actual_success INTEGER,
                predicted_time_s REAL, actual_time_s REAL,
                predicted_elegance REAL, actual_elegance REAL,
                surprise REAL, free_energy REAL, ts REAL NOT NULL
            )
        """)
        rows = conn.execute(
            "SELECT actual_success FROM active_inference_surprises "
            "WHERE method=? AND target_class=? ORDER BY ts DESC LIMIT ?",
            (method, target_class, limit),
        ).fetchall()
        conn.close()
        return [int(r[0]) for r in rows]
    except Exception:
        return []


def learning_progress(method: str, target_class: str = "_none_") -> Dict[str, Any]:
    """Mesure progress = succès récent - succès ancien.

    Returns:
        {progress, p_recent, p_old, n_recent, n_old, zone}
    """
    recent = _recent_obs(method, target_class, WINDOW_RECENT)
    older = _recent_obs(method, target_class, WINDOW_RECENT + WINDOW_OLD)[WINDOW_RECENT:]
    p_recent = sum(recent) / len(recent) if recent else 0.5
    p_old = sum(older) / len(older) if older else p_recent
    progress = p_recent - p_old

    # Classify zone
    if not recent:
        zone = "unknown"
    elif p_recent >= SUCCESS_BOREDOM and abs(progress) < 0.05:
        zone = "boredom"
    elif p_recent <= SUCCESS_FRUSTRATION and progress <= 0:
        zone = "frustration"
    elif progress >= PROGRESS_HIGH:
        zone = "flow"
    elif progress <= PROGRESS_LOW:
        zone = "regression"
    elif SUCCESS_FRUSTRATION < p_recent < SUCCESS_BOREDOM:
        zone = "comfort"
    else:
        zone = "stable"

    return {
        "method": method,
        "target_class": target_class,
        "progress": round(progress, 4),
        "p_recent": round(p_recent, 4),
        "p_old": round(p_old, 4),
        "n_recent": len(recent),
        "n_old": len(older),
        "zone": zone,
        "is_flow": zone == "flow",
        "is_boredom": zone == "boredom",
        "is_frustration": zone == "frustration",
    }


def flow_score(method: str, target_class: str = "_none_") -> float:
    """Score 0-1 pour prioriser dans router.

    flow > comfort > stable > regression > frustration > boredom > unknown
    """
    info = learning_progress(method, target_class)
    zone = info["zone"]
    return {
        "flow": 1.0,
        "comfort": 0.7,
        "stable": 0.5,
        "regression": 0.3,
        "frustration": 0.2,
        "boredom": 0.1,
        "unknown": 0.4,
    }.get(zone, 0.5)


def find_flow_methods(min_n: int = 5) -> List[Dict[str, Any]]:
    """Trouve toutes les paires (method, target_class) en flow zone."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        rows = conn.execute(
            """
            SELECT method, target_class, COUNT(*) as n
            FROM active_inference_surprises
            GROUP BY method, target_class
            HAVING n >= ?
        """,
            (min_n,),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    out = []
    for r in rows:
        info = learning_progress(r[0], r[1])
        if info["is_flow"]:
            out.append(info)
    out.sort(key=lambda x: -x["progress"])
    return out


def find_boredom_zones(min_n: int = 10) -> List[Dict[str, Any]]:
    """Tâches ennuyeuses (déjà maîtrisées) — candidates pour skip ou augmenter difficulté."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        rows = conn.execute(
            """
            SELECT method, target_class, COUNT(*) as n
            FROM active_inference_surprises
            GROUP BY method, target_class
            HAVING n >= ?
        """,
            (min_n,),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    out = []
    for r in rows:
        info = learning_progress(r[0], r[1])
        if info["is_boredom"]:
            out.append(info)
    return out


def stats() -> Dict[str, Any]:
    """Stats globales zones d'apprentissage."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        rows = conn.execute("""
            SELECT method, target_class, COUNT(*) as n
            FROM active_inference_surprises
            GROUP BY method, target_class
            HAVING n >= 3
        """).fetchall()
        conn.close()
    except Exception:
        return {"error": "no data"}
    by_zone = {"flow": 0, "comfort": 0, "stable": 0, "regression": 0, "frustration": 0, "boredom": 0, "unknown": 0}
    for r in rows:
        info = learning_progress(r[0], r[1])
        by_zone[info["zone"]] = by_zone.get(info["zone"], 0) + 1
    total = sum(by_zone.values())
    return {
        "total_method_target_pairs": total,
        "by_zone": by_zone,
        "flow_ratio": round(by_zone["flow"] / max(total, 1), 3),
        "frustration_ratio": round(by_zone["frustration"] / max(total, 1), 3),
        "boredom_ratio": round(by_zone["boredom"] / max(total, 1), 3),
    }


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys, argparse

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--progress", nargs="+", metavar=("METHOD", "[TARGET_CLASS]"))
    ap.add_argument("--flow", action="store_true")
    ap.add_argument("--boredom", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.progress:
        m = args.progress[0]
        tc = args.progress[1] if len(args.progress) > 1 else "_none_"
        print(json.dumps(learning_progress(m, tc), indent=2))
    elif args.flow:
        print(json.dumps(find_flow_methods(), indent=2))
    elif args.boredom:
        print(json.dumps(find_boredom_zones(), indent=2))
    elif args.stats:
        print(json.dumps(stats(), indent=2))
    else:
        ap.print_help()
