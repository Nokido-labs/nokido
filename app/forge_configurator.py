"""
Phase 4 - AMI roadmap: Configurator dynamique.
Classify task type via embedding NN + return optimal module config.
Depends on: forge_state_encoder.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import numpy as np

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).parent.parent
_DB = ROOT / "RAG" / "embeddings.db"

# ---------------------------------------------------------------------------
# Task catalog — 10 types with representative descriptions
# ---------------------------------------------------------------------------

TASK_CATALOG: dict[str, dict] = {
    "code_gen": {
        "examples": ["write a python function", "implement module", "generate code", "create script"],
        "config": {"model": "qwen2.5-coder:latest", "cost_lambda": 0.8, "actor_N": 3, "horizon": 2},
    },
    "rag_query": {
        "examples": ["search knowledge base", "find similar", "retrieve context", "query RAG"],
        "config": {"model": "laforge-qwen:latest", "cost_lambda": 0.5, "actor_N": 2, "horizon": 1},
    },
    "network_audit": {
        "examples": ["ping host", "check firewall", "audit network", "scan ports", "topology"],
        "config": {"model": "qwen2.5:latest", "cost_lambda": 0.6, "actor_N": 3, "horizon": 3},
    },
    "security_audit": {
        "examples": ["audit CVE", "analyse de vulnerabilite", "revue de securite", "reconnaissance defensive"],
        "config": {"model": "deepseek-r1:14b", "cost_lambda": 0.9, "actor_N": 5, "horizon": 4},
    },
    "refactor": {
        "examples": ["refactor code", "clean up", "rename variables", "restructure module"],
        "config": {"model": "qwen2.5-coder:latest", "cost_lambda": 0.6, "actor_N": 3, "horizon": 2},
    },
    "analysis": {
        "examples": ["analyze logs", "diagnose error", "investigate issue", "debug"],
        "config": {"model": "deepseek-r1:14b", "cost_lambda": 0.7, "actor_N": 4, "horizon": 3},
    },
    "research": {
        "examples": ["research topic", "find papers", "survey literature", "veille"],
        "config": {"model": "qwen3:8b", "cost_lambda": 0.5, "actor_N": 4, "horizon": 2},
    },
    "orchestration": {
        "examples": ["coordinate agents", "dispatch task", "run pipeline", "orchestrate"],
        "config": {"model": "laforge-qwen:latest", "cost_lambda": 0.7, "actor_N": 5, "horizon": 4},
    },
    "monitoring": {
        "examples": ["check health", "monitor service", "watch metrics", "alert on failure"],
        "config": {"model": "qwen2.5:latest", "cost_lambda": 0.4, "actor_N": 2, "horizon": 1},
    },
    "data_ingestion": {
        "examples": ["ingest document", "index file", "embed chunks", "crawl url"],
        "config": {"model": "laforge-qwen:latest", "cost_lambda": 0.5, "actor_N": 2, "horizon": 1},
    },
}

_DEFAULT_CONFIG = {"model": "laforge-qwen:latest", "cost_lambda": 0.7, "actor_N": 3, "horizon": 2}

_catalog_embs: Optional[dict[str, np.ndarray]] = None


def _get_catalog_embeddings() -> dict[str, np.ndarray]:
    global _catalog_embs
    if _catalog_embs is not None:
        return _catalog_embs
    from nokido_agent.app.forge_state_encoder import encode_state

    _catalog_embs = {}
    for task_type, meta in TASK_CATALOG.items():
        combined = " ".join(meta["examples"])
        _catalog_embs[task_type] = encode_state(combined)
    return _catalog_embs


# ---------------------------------------------------------------------------
# classify_task
# ---------------------------------------------------------------------------


def classify_task(task_description: str) -> str:
    """Embed task description → nearest neighbor in catalog."""
    from nokido_agent.app.forge_state_encoder import encode_state, cosine_similarity

    task_emb = encode_state(task_description)
    catalog = _get_catalog_embeddings()
    best_type, best_sim = "orchestration", -1.0
    for task_type, cat_emb in catalog.items():
        sim = cosine_similarity(task_emb, cat_emb)
        if sim > best_sim:
            best_sim, best_type = sim, task_type
    return best_type


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------


def configure(task_type: str) -> dict:
    """Return module config for task_type. Falls back to default."""
    meta = TASK_CATALOG.get(task_type, {})
    config = dict(meta.get("config", _DEFAULT_CONFIG))
    config["task_type"] = task_type
    return config


def configure_from_description(task_description: str) -> dict:
    """End-to-end: description → task_type → config."""
    task_type = classify_task(task_description)
    return configure(task_type)


# MPC-specific surprise thresholds per task type (conservative for security)
_SURPRISE_THRESHOLDS = {
    "security_audit": 1.05,  # tight — surprises are dangerous
    "network_audit": 1.10,
    "code_gen": 1.20,
    "refactor": 1.15,
    "orchestration": 1.20,
    "monitoring": 1.30,  # loose — monitoring tolerates variance
    "research": 1.30,
    "rag_query": 1.40,
    "data_ingestion": 1.35,
    "analysis": 1.15,
}


def get_mpc_config(task_description: str, state_text: str = "") -> dict:
    """Return complete MPC-ready config by classifying task.

    Returns dict accepted directly by run_mpc_loop(config=...).
    """
    task_type = classify_task(task_description)
    base = configure(task_type)
    return {
        "task_type": task_type,
        "model": base.get("model", "laforge-qwen:latest"),
        "horizon": base.get("horizon", 2),
        "n_candidates": base.get("actor_N", 3),
        "cost_lambda": base.get("cost_lambda", 0.7),
        "surprise_threshold": _SURPRISE_THRESHOLDS.get(task_type, 1.20),
        "gradient_refine": task_type in {"security_audit", "analysis", "orchestration"},
        "use_jepa": task_type in {"security_audit", "analysis", "orchestration"},
        "use_mcts": task_type in {"security_audit", "analysis", "orchestration"},
    }


# ---------------------------------------------------------------------------
# learn (feedback-based reinforcement)
# ---------------------------------------------------------------------------


def learn(task_description: str, config_used: dict, success: bool, cost_final: float) -> None:
    """Persist feedback. Future: update catalog weights based on outcomes."""
    conn = sqlite3.connect(_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS configurator_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            task_description TEXT,
            task_type TEXT,
            config_json TEXT,
            success INTEGER,
            cost_final REAL
        )
    """)
    conn.execute(
        "INSERT INTO configurator_feedback (ts, task_description, task_type, config_json, success, cost_final) VALUES (?,?,?,?,?,?)",
        (
            time.time(),
            task_description[:500],
            config_used.get("task_type", "unknown"),
            json.dumps(config_used),
            int(success),
            cost_final,
        ),
    )
    conn.commit()
    conn.close()


def get_feedback_stats() -> dict:
    conn = sqlite3.connect(_DB)
    try:
        rows = conn.execute("""
            SELECT task_type, COUNT(*), AVG(success), AVG(cost_final)
            FROM configurator_feedback GROUP BY task_type
        """).fetchall()
    except Exception:
        rows = []
    conn.close()
    return {r[0]: {"count": r[1], "success_rate": r[2], "avg_cost": r[3]} for r in rows}


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        "write a Python script to parse JSON logs",
        "audit the firewall rules on router localhost",
        "find papers on MCTS for language agents",
        "check if hub service is healthy",
        "exploit SQL injection on test target",
        "orchestrate 3 agents to complete data pipeline",
    ]
    print("[configurator] Classification test:\n")
    for desc in tests:
        cfg = configure_from_description(desc)
        print(f"  [{cfg['task_type']:18s}] model={cfg['model']:30s} N={cfg['actor_N']} H={cfg['horizon']}")
        print(f"    task: {desc[:60]}")
