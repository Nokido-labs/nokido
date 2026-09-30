"""
app/forge_dag_runner.py — Nokido v18.5
========================================
Exécution parallèle des plans agent_tasks en DAG.
Remplace: for step in plan (séquentiel)
Par:      gather(steps sans dépendances) → unlock suivants

Format plan DAG:
[
  {"id":"s1", "action":"read_config", "tool":"read",  "deps":[]},
  {"id":"s2", "action":"web_search",  "tool":"web",   "deps":[]},      ← parallèle avec s1
  {"id":"s3", "action":"synthesize",  "tool":"ask",   "deps":["s1","s2"]} ← attend s1+s2
]
"""

from __future__ import annotations
import asyncio, json, time, logging
from typing import Any, Callable, Coroutine

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("forge.dag")


class DAGRunner:
    """
    Exécute un plan JSON en respectant les dépendances.
    Les étapes sans dépendances partent en parallèle via asyncio.gather.
    """

    # Lock partagé : écriture event_log safe en concurrent
    _log_lock: asyncio.Lock | None = None

    def __init__(self, executor: Callable[[dict], Coroutine]):
        """
        executor: coroutine async qui prend un step dict et retourne str.
        Ex: lambda step: handle_meta_tool(step["tool"], step.get("args", {}))
        """
        self._exec = executor

    async def run(self, plan: list[dict], timeout_per_step: float = 30.0) -> dict:
        if DAGRunner._log_lock is None:
            DAGRunner._log_lock = asyncio.Lock()
        """
        Lance le plan DAG. Retourne {step_id: result, ...} + métadonnées.
        """
        if not plan:
            return {"results": {}, "elapsed_ms": 0.0, "error": None}

        # Normaliser — si plan est séquentiel (pas de deps), ajouter deps auto
        plan = self._normalize(plan)

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        t0 = time.perf_counter()

        # Ensemble des steps complétés
        done: set[str] = set()
        remaining = {s["id"]: s for s in plan}

        max_rounds = len(plan) + 2  # garde-fou anti-boucle infinie
        rounds = 0

        while remaining and rounds < max_rounds:
            rounds += 1

            # Steps dont toutes les dépendances sont satisfaites
            ready = [s for s in remaining.values() if all(dep in done for dep in s.get("deps", []))]

            if not ready:
                # Dépendances circulaires ou étapes bloquées
                blocked = list(remaining.keys())
                logger.warning(f"DAG bloqué: {blocked}")
                errors["DAG_BLOCKED"] = f"steps bloqués: {blocked}"
                break

            logger.info(f"DAG round {rounds}: {len(ready)} steps en parallèle ({[s['id'] for s in ready]})")

            # Lancer tous les ready en parallèle
            async def _run_step(step: dict) -> tuple[str, Any]:
                sid = step["id"]
                try:
                    result = await asyncio.wait_for(self._exec(step), timeout=timeout_per_step)
                    return sid, result
                except asyncio.TimeoutError:
                    return sid, f"TIMEOUT: step {sid} > {timeout_per_step}s"
                except Exception as e:
                    return sid, f"ERR: {e}"

            batch = await asyncio.gather(*[_run_step(s) for s in ready])

            for sid, result in batch:
                results[sid] = result
                done.add(sid)
                del remaining[sid]

        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "results": results,
            "errors": errors,
            "elapsed_ms": round(elapsed, 1),
            "steps_done": len(done),
            "steps_total": len(plan),
        }

    @staticmethod
    def _normalize(plan: list[dict]) -> list[dict]:
        """
        Si le plan est une liste séquentielle (step 1, 2, 3 sans deps),
        le convertir en DAG linéaire: chaque step dépend du précédent.
        Si le plan a déjà des deps, le laisser tel quel.
        """
        has_deps = any("deps" in s for s in plan)
        has_ids = all("id" in s for s in plan)

        normalized = []
        for i, step in enumerate(plan):
            s = dict(step)
            # Assigner un id si absent
            if "id" not in s:
                s["id"] = f"s{i + 1}"
            # Assigner deps si absent — séquentiel par défaut
            if "deps" not in s:
                s["deps"] = [f"s{i}"] if i > 0 else []
            normalized.append(s)

        return normalized

    @staticmethod
    def from_parallel_steps(steps: list[dict]) -> list[dict]:
        """Helper: créer un plan où TOUS les steps partent en parallèle."""
        return [dict(s, id=s.get("id", f"s{i}"), deps=[]) for i, s in enumerate(steps)]

    @staticmethod
    def from_sequential_steps(steps: list[dict]) -> list[dict]:
        """Helper: créer un plan séquentiel (comportement actuel)."""
        result = []
        for i, s in enumerate(steps):
            result.append(dict(s, id=s.get("id", f"s{i + 1}"), deps=[f"s{i}"] if i > 0 else []))
        return result


# ── Intégration dans handle_meta_tool / agent_tasks ─────────────────────────


async def log_concurrent(db_path, agent_id: str, event_type: str, payload: str):
    """Écriture SQLite thread-safe pour exécutions parallèles."""
    async with DAGRunner._log_lock or asyncio.Lock():
        import sqlite3

        try:
            conn = sqlite3.connect(str(db_path), timeout=3)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO event_log(timecode,agent_id,event_type,target,payload,status,sequence_id,session_id,ring_id,token_id) "
                "VALUES(datetime('now'),?,?,?,?,'dag_run',0,'','','')",
                (agent_id, event_type, event_type[:50], payload[:200]),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # log non-bloquant


async def execute_task_plan(task_id: str, plan: list[dict], entity_id: str = "laforge") -> dict:
    """
    Point d'entrée principal: prend un plan agent_tasks et l'exécute en DAG.
    Utilisé par forge_meta_tools.handle_meta_tool name=run_pipeline.
    """
    from pathlib import Path
    import sqlite3

    DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"

    async def _step_executor(step: dict) -> str:
        """Dispatch chaque step vers le bon handler."""
        tool = step.get("tool", "")
        args = step.get("args", {})
        action = step.get("action", "")

        # Fast-path: si tool connu localement → pas de LLM
        if tool in ("read", "query", "system_status"):
            from nokido_agent.app.forge_meta_tools import handle_meta_tool

            return await handle_meta_tool(tool, args, entity_id)
        elif tool in ("web_search", "web"):
            from nokido_agent.app.forge_meta_tools import handle_meta_tool

            return await handle_meta_tool("web_fetch", args, entity_id)
        elif tool.startswith("pipeline:"):
            from nokido_agent.app.forge_sandbox_guard import run_analysis_pipeline

            key = tool.replace("pipeline:", "")
            return json.dumps(run_analysis_pipeline(key, entity_id))
        else:
            # Fallback: log et skip
            logger.warning(f"Step tool inconnu: {tool!r} — skipped")
            return f"SKIPPED: {action}"

    runner = DAGRunner(_step_executor)
    result = await runner.run(plan)

    # Persister le résultat dans agent_tasks
    try:
        conn = sqlite3.connect(str(DB), timeout=3)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE agent_tasks SET status='done', result=? WHERE id=?", (json.dumps(result)[:2000], task_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"DAG result persist err: {e}")

    return result


if __name__ == "__main__":
    # Test DAG
    import asyncio

    call_log = []

    async def mock_exec(step):
        await asyncio.sleep(0.05)  # simuler I/O
        call_log.append(step["id"])
        return f"done:{step['id']}"

    # Plan avec dépendances
    plan = [
        {"id": "fetch_web", "action": "scrape", "deps": []},
        {"id": "check_db", "action": "query", "deps": []},  # parallèle avec fetch_web
        {"id": "synthesize", "action": "ask_llm", "deps": ["fetch_web", "check_db"]},
        {"id": "save", "action": "write", "deps": ["synthesize"]},
    ]

    runner = DAGRunner(mock_exec)
    result = asyncio.run(runner.run(plan))
    print(f"DAG terminé en {result['elapsed_ms']}ms")
    print(f"Ordre exécution: {call_log}")
    print(f"Results: {result['results']}")
    assert call_log.index("fetch_web") < call_log.index("synthesize")
    assert call_log.index("check_db") < call_log.index("synthesize")
    print("✓ fetch_web et check_db lancés avant synthesize")

    # Plan séquentiel auto-normalisé
    seq_plan = [{"step": 1, "action": "a"}, {"step": 2, "action": "b"}, {"step": 3, "action": "c"}]
    result2 = asyncio.run(runner.run(seq_plan))
    print(f"\nPlan séquentiel: {result2['steps_done']}/3 steps")
