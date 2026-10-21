"""forge_memory_consolidator.py — Hippocampus→Cortex consolidation (Hassabis).

Filters high-value traces from execution_traces.db, summarises them via LLM,
and ingests structured experience chunks into rag_chunks (embeddings.db).

Hassabis (2017): offline hippocampal replay during sleep → cortical consolidation.
Here: high-value traces (success=1, cost_after < COST_THRESHOLD) → ollama summary
→ RAG chunk with source=experience/consolidated/{task_type}.

Run: LAFORGE_PYTHON tools/forge_memory_consolidator.py --once
     LAFORGE_PYTHON tools/forge_memory_consolidator.py --daemon  (runs every 12h)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
RAG_DIR = ROOT / "RAG"
SANDBOX = ROOT / "sandbox"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
# --- amorce namespace (point d'entree) : lance PAR CHEMIN, `sys.path[0]` vaut tools/, pas la racine
# ou vit le package `nokido_agent` -> ModuleNotFoundError a chaque relance (mesure 18/10, service rallume).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger("Nokido.MemoryConsolidator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

TRACES_DB = RAG_DIR / "execution_traces.db"
EMBEDDINGS_DB = RAG_DIR / "embeddings.db"
HEARTBEAT = SANDBOX / "memory_consolidator.heartbeat"
STATE_FILE = SANDBOX / "memory_consolidator_state.json"

INTERVAL_S = 43_200  # 12h
COST_THRESHOLD = 0.3  # only traces with cost_after < this
MIN_GROUP_SIZE = 5  # min traces per task_type to trigger consolidation
MAX_TRACES_PER_GROUP = 50  # cap to avoid huge prompts

# Gate anti-régression (app/ déjà inséré sur sys.path ci-dessus).
from nokido_agent.app.forge_guarded_change import guarded_change

# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_memory_consolidator.py', 63, exc_info=True)
    return {"last_consolidated_ts": 0.0}


def _save_state(state: dict) -> None:
    SANDBOX.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _attente_avant_cycle(state: dict, maintenant: float) -> float:
    """20/10 : au reveil du daemon, aucun cycle avant la fin de l'intervalle."""
    debut = state.get("dernier_cycle_debut")
    if not debut:
        return 0.0
    return max(0.0, float(INTERVAL_S) - (float(maintenant) - float(debut)))


def _write_heartbeat(results: dict) -> None:
    SANDBOX.mkdir(exist_ok=True)
    HEARTBEAT.write_text(
        json.dumps(
            {
                "ts": datetime.now().isoformat(),
                "pid": os.getpid(),
                "interval_s": INTERVAL_S,
                "last_results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Trace retrieval
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_high_value_traces(since_ts: float) -> dict[str, list[dict]]:
    """Group high-value traces by task_type since last consolidation.
    Filtre system_tick legacy noise (~1588 entries d un ancien daemon)."""
    if not TRACES_DB.exists():
        return {}
    con = sqlite3.connect(str(TRACES_DB))
    rows = con.execute(
        "SELECT task_type, action_json, cost_before, cost_after, success "
        "FROM traces "
        "WHERE success=1 AND cost_after < ? AND ts > ? "
        "AND task_type IS NOT NULL "
        "AND action_json NOT LIKE '%system_tick%' "
        "ORDER BY cost_after ASC LIMIT 5000",
        (COST_THRESHOLD, since_ts),
    ).fetchall()
    con.close()

    groups: dict[str, list[dict]] = {}
    for task_type, action_json, cost_before, cost_after, success in rows:
        try:
            action = json.loads(action_json) if action_json else {}
        except Exception:
            action = {"raw": str(action_json)}
        groups.setdefault(task_type or "unknown", []).append(
            {
                "action": action,
                "cost_before": cost_before,
                "cost_after": cost_after,
                "improvement": round((cost_before or 1) - (cost_after or 0), 4),
            }
        )
    return groups


# ─────────────────────────────────────────────────────────────────────────────
# LLM summarisation
# ─────────────────────────────────────────────────────────────────────────────


def _summarise_group(task_type: str, traces: list[dict]) -> str:
    """Call ollama to distil traces into an experience narrative."""
    sample = traces[:MAX_TRACES_PER_GROUP]
    actions_text = "\n".join(
        f"- {t['action'].get('description') or t['action'].get('tool') or str(t['action'])[:80]}"
        f"  (cost {t['cost_before']:.3f}→{t['cost_after']:.3f})"
        for t in sample
    )
    prompt = (
        f"Synthesise the following successful Nokido agent actions for task_type='{task_type}'. "
        f"Write a compact experience summary (3-5 sentences) that captures: "
        f"what strategies worked, what cost reductions were achieved, and what to do next time.\n\n"
        f"Actions:\n{actions_text}\n\nSummary:"
    )
    try:
        from nokido_agent.app.forge_ollama import chat_ollama

        return chat_ollama(prompt, model="laforge-qwen", max_tokens=300)
    except Exception:
        # Fallback: structured text summary without LLM
        avg_improvement = sum(t["improvement"] for t in sample) / len(sample)
        return (
            f"Consolidated experience for {task_type}: {len(sample)} successful traces. "
            f"Avg cost improvement: {avg_improvement:.3f}. "
            f"Top strategies: {', '.join(set(str(t['action'].get('tool', 'unknown')) for t in sample[:5]))}."
        )


# ─────────────────────────────────────────────────────────────────────────────
# RAG ingest
# ─────────────────────────────────────────────────────────────────────────────


def _ingest_experience(task_type: str, summary: str, n_traces: int) -> str | None:
    """Insert consolidated experience chunk into rag_chunks.

    20/10 : renvoie l'id du chunk s'il vient d'etre CREE, None s'il existait
    deja ou en cas d'erreur (le cycle ne retire ensuite que ce qu'il a cree).
    """
    source = f"experience/consolidated/{task_type}"
    text = f"[{task_type}] {summary} (consolidated from {n_traces} traces)"
    chunk_id = sha256((source + text).encode()).hexdigest()[:16]
    try:
        con = sqlite3.connect(str(EMBEDDINGS_DB))
        # 20/10 : presence verifiee AVANT l'INSERT -> deja present = pas cree.
        deja_la = con.execute("SELECT 1 FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone() is not None
        if not deja_la:
            con.execute(
                "INSERT OR REPLACE INTO rag_chunks (id, source, text) VALUES (?, ?, ?)",
                (chunk_id, source, text),
            )
            con.commit()
        con.close()

        # Reveil du daemon d'embedding, via le helper qui VERIFIE l'ecouteur.
        #
        # CORRECTION DE MON PROPRE CORRECTIF (2026-08-05, meme journee) : j'avais
        # d'abord ajoute ici un log sur l'exception. Il etait INERTE — mesure faite
        # ensuite : un PUSH ZMQ vers un port ferme est ACCEPTE, aucune exception n'est
        # levee, donc il n'y avait rien a attraper. Journaliser une erreur qui ne se
        # produit pas ne repare rien ; il fallait verifier la presence d'un PAIR.
        try:
            from nokido_agent.app.forge_nudge_embed import nudge_embed

            nudge_embed(1, source="forge_memory_consolidator")
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger(__name__).warning(
                "[consolidateur] reveil d'embedding impossible (%s: %s) | consequence: "
                "cette experience consolidee reste sans vecteur jusqu'au prochain drain",
                type(e).__name__, str(e)[:90])
        return None if deja_la else chunk_id
    except Exception as e:
        logger.error("ingest_experience %s: %s", task_type, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Main cycle
# ─────────────────────────────────────────────────────────────────────────────


def _retirer_chunks(ids: list[str]) -> None:
    """20/10 : retour arriere CIBLE — DELETE des seuls ids crees par ce cycle."""
    if not ids:
        return
    try:
        con = sqlite3.connect(str(EMBEDDINGS_DB))
        con.executemany("DELETE FROM rag_chunks WHERE id=?", [(i,) for i in ids])
        con.commit()
        con.close()
    except Exception as e:  # noqa: BLE001
        logger.error("retour arriere de %d chunks: %s", len(ids), e)


def run_consolidation_cycle(state: dict) -> dict:
    t0 = time.monotonic()
    # 20/10 : debut du cycle sauve AVANT le travail lourd (reveil du regulateur).
    state["dernier_cycle_debut"] = time.time()
    _save_state(state)
    groups = _fetch_high_value_traces(state["last_consolidated_ts"])

    total_traces = sum(len(v) for v in groups.values())
    logger.info("Found %d high-value traces in %d task_types", total_traces, len(groups))

    if total_traces == 0:
        return {"skipped": "no new high-value traces", "groups": 0}

    results = {"total_traces": total_traces, "groups": {}}
    ids_crees: list[str] = []
    from tqdm import tqdm

    # 20/10 : plus de db_snapshot (base de 50 Go, integrity_check ~47 min) ; le
    # retour arriere retire les SEULS chunks CREES par ce cycle.
    try:
        with guarded_change("memory_consolidator: consolidation"):
            for task_type, traces in tqdm(groups.items(), desc="consolidate", unit="task_type"):
                if len(traces) < MIN_GROUP_SIZE:
                    logger.debug("skip %s: only %d traces", task_type, len(traces))
                    continue
                logger.info("Consolidating %s (%d traces)...", task_type, len(traces))
                summary = _summarise_group(task_type, traces)
                nouveau = _ingest_experience(task_type, summary, len(traces))
                if nouveau:
                    ids_crees.append(nouveau)
                results["groups"][task_type] = {
                    "n_traces": len(traces),
                    "ingested": bool(nouveau),
                    "summary_len": len(summary),
                }
    except Exception:
        # 20/10 : panne en cours de cycle -> on ne retire que ce qu'on a cree.
        _retirer_chunks(ids_crees)
        raise

    state["last_consolidated_ts"] = time.time()
    results["elapsed_s"] = round(time.monotonic() - t0, 1)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    import io as _io
    import sys as _sys

    if hasattr(_sys.stdout, "buffer"):
        _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")

    import argparse

    ap = argparse.ArgumentParser(description="Nokido memory consolidator (hippocampus→cortex)")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if not args.once and not args.daemon:
        ap.error("--once or --daemon required")

    state = _load_state()

    if args.once:
        results = run_consolidation_cycle(state)
        _save_state(state)
        _write_heartbeat(results)
        print(json.dumps(results, indent=2, default=str))
        return 0

    logger.info("Memory consolidator daemon started — interval=%ds pid=%d", INTERVAL_S, os.getpid())
    # 20/10 : reveil du regulateur -> attendre la fin de l'intervalle avant tout cycle.
    attente = _attente_avant_cycle(state, time.time())
    if attente > 0:
        logger.info("Premier cycle differe de %ds (debut du dernier cycle deja enregistre)", int(attente))
        time.sleep(attente)
    while True:
        try:
            results = run_consolidation_cycle(state)
            _save_state(state)
            _write_heartbeat(results)
        except Exception as exc:
            logger.error("cycle error: %s", exc)
            _write_heartbeat({"error": str(exc)})
        logger.info("Sleeping %ds", INTERVAL_S)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
