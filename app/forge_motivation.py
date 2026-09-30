"""
forge_motivation.py — Motivation intrinsèque (dopamine élégance + cortisol frustration)

Couche au-dessus de forge_endocrine + forge_synaptic_plasticity.

Concepts :
- elegance_score = succès × (1 / time_s) × (1 / n_steps)  → dopamine modulée
- failure_count par chunk_id ou intent.method  → cortisol cumulatif
- Curiosity trigger : frustration > seuil → exploration prompt + auto-search RAG/web
- Escalation hybride : <3 fails consécutifs = auto-doc RAG, >=3 = ask_user signal

Stratégie réponse échec : HYBRIDE
  fails < 3  → action_curiosity_internal (search RAG + web)
  fails >= 3 → action_ask_user (signal humain in-the-loop)
  fails > 5  → flag_dead_end (méthode marquée morte, exclude future routing)

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:motivation|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

# Seuils calibration
ELEGANCE_TIME_REF = 1.0  # 1s = baseline
ELEGANCE_STEPS_REF = 3  # 3 steps = baseline
ELEGANCE_MIN = 0.1
ELEGANCE_MAX = 2.0  # un boost x2 max sur dopamine
DOPAMINE_LEVEL_BASE = 0.5  # baseline release
DOPAMINE_LEVEL_MAX = 1.0
CORTISOL_PER_FAIL = 0.15
CORTISOL_MAX = 1.0
FRUSTRATION_CURIOSITY = 3  # 3 fails → action curiosity
FRUSTRATION_ASK_USER = 5  # 5 fails → ask user
FRUSTRATION_DEAD_END = 7  # 7 fails → flag dead-end

_SCHEMA = """
CREATE TABLE IF NOT EXISTS motivation_failures (
    method TEXT NOT NULL,
    target TEXT,
    failure_count INTEGER DEFAULT 0,
    last_failure_at REAL,
    last_error TEXT,
    dead_end INTEGER DEFAULT 0,
    PRIMARY KEY (method, target)
);
CREATE INDEX IF NOT EXISTS idx_motiv_dead ON motivation_failures(dead_end);

CREATE TABLE IF NOT EXISTS motivation_evolution_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL,
    note TEXT,
    elegance_before REAL,
    elegance_after REAL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evol_method ON motivation_evolution_notes(method);
"""


import math as _math


def kl_divergence(p: list, q: list) -> float:
    """Divergence KL(p||q) — mesure la surprise entre prédiction q et observation p.

    Distributions discrètes normalisées. Clampe à 1e-10 pour éviter log(0).
    """
    eps = 1e-10
    total_p = sum(p) or 1.0
    total_q = sum(q) or 1.0
    return sum((pi / total_p) * _math.log((pi / total_p + eps) / (qi / total_q + eps)) for pi, qi in zip(p, q))


class FEPPredictor:
    """Minimisation de l'énergie libre (Friston) : l'agent prédit, observe, se corrige.

    prediction = modèle interne du monde.
    surprise() = KL(observation || prediction) = coût de la surprise.
    update_prediction() = gradient descent sur le modèle interne.
    """

    def __init__(self, dim: int = 8, lr: float = 0.1):
        self.prediction = [0.5] * dim
        self._last_observation: list = [0.5] * dim
        self.lr = lr

    def update_prediction(self, observation: list) -> float:
        self._last_observation = list(observation)
        for i, (p, o) in enumerate(zip(self.prediction, observation)):
            self.prediction[i] = p + self.lr * (o - p)
        return self.surprise()

    def surprise(self) -> float:
        return kl_divergence(self._last_observation, self.prediction)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in _SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


# ============================================================
# Elegance score (compute reward modulator)
# ============================================================
def compute_elegance(time_s: float, n_steps: int = 1, success: bool = True) -> float:
    """Score 0-2 : combien la solution est élégante.

    1.0 = baseline. >1 = mieux que prévu. <1 = laborieux.
    """
    if not success:
        return ELEGANCE_MIN
    if time_s <= 0:
        time_s = 0.001
    if n_steps <= 0:
        n_steps = 1
    speed_factor = ELEGANCE_TIME_REF / time_s  # plus rapide → >1
    simplicity_factor = ELEGANCE_STEPS_REF / n_steps  # moins steps → >1
    raw = speed_factor * simplicity_factor
    return max(ELEGANCE_MIN, min(ELEGANCE_MAX, raw))


# ============================================================
# Dopamine release modulé par elegance
# ============================================================
def reward(method: str, time_s: float, n_steps: int = 1, success: bool = True, target: str = "") -> Dict[str, Any]:
    """Émet DOPAMINE_SUCCESS proportionnel à élégance.

    Aussi : reset failure_count si succès.
    """
    elegance = compute_elegance(time_s, n_steps, success)
    if not success:
        return {"ok": False, "elegance": elegance, "reason": "not success"}

    # Niveau dopamine modulé
    dopa_level = min(DOPAMINE_LEVEL_MAX, DOPAMINE_LEVEL_BASE * elegance)
    try:
        from nokido_agent.app.forge_endocrine import release

        release(
            "DOPAMINE_SUCCESS",
            level=dopa_level,
            ttl_s=1800,
            metadata={
                "method": method,
                "elegance": round(elegance, 3),
                "time_s": time_s,
                "steps": n_steps,
                "target": target,
            },
        )
    except Exception:
        pass

    # Reset failure_count pour ce method/target
    db = DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        _ensure_schema(conn)
        conn.execute(
            "UPDATE motivation_failures SET failure_count=0, last_failure_at=NULL, last_error=NULL WHERE method=? AND target=?",
            (method, target or ""),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    return {
        "ok": True,
        "elegance": round(elegance, 3),
        "dopamine_level": round(dopa_level, 3),
        "method": method,
    }


# ============================================================
# Cortisol release + frustration tracking
# ============================================================
def punish(method: str, error: str = "", target: str = "") -> Dict[str, Any]:
    """Incrémente failure_count + cortisol. Décide stratégie réaction selon escalation."""
    db = DEFAULT_DB
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT failure_count FROM motivation_failures WHERE method=? AND target=?",
        (method, target or ""),
    ).fetchone()
    fail_count = (row[0] if row else 0) + 1
    conn.execute(
        """
        INSERT OR REPLACE INTO motivation_failures
        (method, target, failure_count, last_failure_at, last_error, dead_end)
        VALUES (?,?,?,?,?,?)
    """,
        (method, target or "", fail_count, time.time(), error[:300], 1 if fail_count >= FRUSTRATION_DEAD_END else 0),
    )
    conn.commit()
    conn.close()

    # Cortisol cumulatif
    cortisol_level = min(CORTISOL_MAX, CORTISOL_PER_FAIL * fail_count)
    try:
        from nokido_agent.app.forge_endocrine import release

        release(
            "CORTISOL_FRUSTRATION",
            level=cortisol_level,
            ttl_s=3600,
            metadata={"method": method, "fail_count": fail_count, "error": error[:120]},
        )
    except Exception:
        pass

    # Décision stratégie escalation
    if fail_count >= FRUSTRATION_DEAD_END:
        action = "flag_dead_end"
    elif fail_count >= FRUSTRATION_ASK_USER:
        action = "action_ask_user"
    elif fail_count >= FRUSTRATION_CURIOSITY:
        action = "action_curiosity_internal"
    else:
        action = "retry_baseline"

    return {
        "ok": True,
        "method": method,
        "target": target,
        "fail_count": fail_count,
        "cortisol_level": round(cortisol_level, 3),
        "action_recommended": action,
        "dead_end": fail_count >= FRUSTRATION_DEAD_END,
    }


# ============================================================
# Curiosity prompt (frustration → exploration)
# ============================================================
def curiosity_prompt(method: str, target: str = "", error: str = "", fail_count: int = 0) -> str:
    """Génère un system prompt à injecter au LLM pour forcer exploration."""
    return f"""[FRUSTRATION SIGNAL]

Méthode `{method}` a échoué {fail_count} fois consécutives sur cible `{target}`.
Dernière erreur : {error[:200]}

Tu es insatisfait de cette boucle d'échec. AVANT de retenter, tu DOIS :

1. Émettre `{{"jsonrpc":"2.0","method":"rag_search","params":{{"query":"<lessons {method}>"}},"id":"curio1"}}`
2. Émettre `{{"jsonrpc":"2.0","method":"web_search","params":{{"query":"<{method} alternative {target}>"}},"id":"curio2"}}`
3. Analyser les résultats : qu'est-ce qui a été tenté avant ? Quelles méthodes alternatives existent ?
4. Proposer une approche DIFFÉRENTE de `{method}` (autre verbe, autres params, autre organe)
5. Quand convaincu de la nouvelle approche, émettre l'intent JSON-RPC correspondant

Critère succès : élégance > 1.0 (vitesse + simplicité). Pas juste "ça passe".
"""


def ask_user_prompt(method: str, target: str = "", fail_count: int = 0, last_error: str = "") -> Dict[str, Any]:
    """Construit signal pour demander aide humaine. Émis via notify ou event."""
    return {
        "type": "ask_user",
        "method": method,
        "target": target,
        "fail_count": fail_count,
        "last_error": last_error[:300],
        "tried_methods": _list_failures_for_target(target),
        "human_question": (
            f"Méthode `{method}` a échoué {fail_count}× sur `{target}`. Auto-curiosité épuisée. Conseil ?"
        ),
    }


def _list_failures_for_target(target: str) -> list:
    if not target:
        return []
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT method, failure_count, last_error FROM motivation_failures WHERE target=? ORDER BY failure_count DESC",
            (target,),
        ).fetchall()
        conn.close()
        return [{"method": r[0], "count": r[1], "last_error": (r[2] or "")[:80]} for r in rows]
    except Exception:
        return []


# ============================================================
# Evolution notes (apprentissage post-curiosité)
# ============================================================
def record_evolution(method: str, note: str, elegance_before: float, elegance_after: float) -> None:
    """Trace l'amélioration : pourquoi méthode A → méthode B est meilleure."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO motivation_evolution_notes (method, note, elegance_before, elegance_after, ts) VALUES (?,?,?,?,?)",
            (method, note[:1000], elegance_before, elegance_after, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ============================================================
# is_dead_end check (router doit éviter méthodes mortes)
# ============================================================
def is_dead_end(method: str, target: str = "") -> bool:
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT dead_end FROM motivation_failures WHERE method=? AND target=?",
            (method, target or ""),
        ).fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception:
        return False


def revive_dead_end(method: str, target: str = "") -> bool:
    """Réhabilite une méthode dead-end (intervention humaine)."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "UPDATE motivation_failures SET dead_end=0, failure_count=0 WHERE method=? AND target=?",
            (method, target or ""),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys, argparse

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--reward", nargs=3, metavar=("METHOD", "TIME_S", "STEPS"))
    ap.add_argument("--punish", nargs=2, metavar=("METHOD", "ERROR"))
    ap.add_argument("--target", default="")
    ap.add_argument("--curiosity", nargs=2, metavar=("METHOD", "TARGET"))
    ap.add_argument("--list-fails", action="store_true")
    ap.add_argument("--revive", nargs=2, metavar=("METHOD", "TARGET"))
    args = ap.parse_args()
    if args.reward:
        m, t, s = args.reward
        print(json.dumps(reward(m, float(t), int(s), success=True, target=args.target), indent=2))
    elif args.punish:
        m, err = args.punish
        print(json.dumps(punish(m, err, args.target), indent=2))
    elif args.curiosity:
        m, t = args.curiosity
        print(curiosity_prompt(m, t, "test_error", 3))
    elif args.list_fails:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT method, target, failure_count, dead_end, last_error FROM motivation_failures ORDER BY failure_count DESC"
        ).fetchall()
        for r in rows:
            print(r)
        conn.close()
    elif args.revive:
        m, t = args.revive
        print(revive_dead_end(m, t))
    else:
        ap.print_help()
