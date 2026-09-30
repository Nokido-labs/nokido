"""
forge_trajectory.py — Structured Agentic Trajectory

Implémentation du pattern JSON-RPC inter-agent strict (vs prose chatbot).

Usage :
    from forge_trajectory import (
        Trajectory, parse_intent, dispatch_intent,
        SYSTEM_PROMPT_JSON_MODE, IntentValidationError,
    )

    # 1. LLM forcé JSON Mode (system prompt)
    response = llm_call(prompt, system=SYSTEM_PROMPT_JSON_MODE)

    # 2. Parse strict (lève si invalide → re-prompt LLM)
    intent = parse_intent(response)

    # 3. Validate + dispatch
    result = await dispatch_intent(intent, ctx)

    # 4. Append trajectory state machine
    traj.append(intent, result)

Inspiration : JSON-RPC 2.0 + DeepMind Tool Calling + Anthropic Structured Outputs.
Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:trajectory|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"


# ============================================================
# 1. Whitelist méthodes (registry des verbes connus)
# ============================================================
ALLOWED_METHODS = {
    # Memory / RAG
    "embed": {"params": {"texts": "list[str]"}, "ring": 2, "organ": "memoire"},
    "rag_search": {"params": {"query": "str", "limit": "int?"}, "ring": 2, "organ": "memoire"},
    "rag_ingest": {"params": {"chunks": "list[str]", "domain": "str?"}, "ring": 1, "organ": "digestif"},
    # Compute
    "swarm_vectorize": {"params": {"target_repo": "str", "depth": "str?"}, "ring": 2, "organ": "cervelet"},
    # Network / Recon
    # Web
    "web_search": {"params": {"query": "str"}, "ring": 2, "organ": "sens"},
    "crawl": {"params": {"url": "str"}, "ring": 2, "organ": "sens"},
    "get_file_skeleton": {"params": {"file_path": "str"}, "ring": 2, "organ": "sens"},
    "read_function_body": {"params": {"file_path": "str", "function_name": "str"}, "ring": 2, "organ": "sens"},
    "get_function_dependencies": {"params": {"function_name": "str", "file_path": "str?"}, "ring": 2, "organ": "sens"},
    "blackboard_read_zone": {"params": {"zone_name": "str"}, "ring": 2, "organ": "memoire"},
    "blackboard_propose_fact": {"params": {"zone_name": "str", "fact": "str", "category": "str?", "trust": "float?"}, "ring": 2, "organ": "memoire"},
    # LLM cascade
    "llm_call": {"params": {"provider": "str", "message": "str"}, "ring": 2, "organ": "metabolisme"},
    "llm_route": {"params": {"task_type": "str", "payload": "dict"}, "ring": 2, "organ": "snc"},
    # Locomoteur
    "run_python": {"params": {"code": "str"}, "ring": 1, "organ": "locomoteur"},
    "run_shell": {"params": {"code": "str"}, "ring": 1, "organ": "locomoteur"},
    # Comm
    "notify": {"params": {"to": "str", "message": "str"}, "ring": 2, "organ": "comm"},
    "event_publish": {"params": {"topic": "str", "data": "dict"}, "ring": 2, "organ": "vasc"},
    # Result (réponse async)
    "result": {"params": {"job_id": "str", "data": "dict"}, "ring": 0, "organ": "*"},
    "error": {"params": {"job_id": "str", "reason": "str"}, "ring": 0, "organ": "*"},
    # OPSEC Rules of Engagement (Phase 6)
    "set_opsec_level": {"params": {"level": "str", "reason": "str?"}, "ring": 0, "organ": "membrane"},
    "opsec_status": {"params": {}, "ring": 1, "organ": "membrane"},
    "sanitize_text": {"params": {"text": "str", "level": "str?"}, "ring": 1, "organ": "membrane"},
    "detect_lab": {"params": {"text": "str"}, "ring": 1, "organ": "membrane"},
}


def _charger_intents_offensifs_optionnels() -> None:
    """Intents offensifs (ring>=3) sortis du coeur (owner 2026-09-26) : fournis par le depot
    redteam, charges SEULEMENT si NOKIDO_REDTEAM_INTENTS_JSON pointe un fichier lisible.
    Absent -> le coeur ne peut pas planifier d'action offensive, et c'est l'etat voulu."""
    import json as _json
    import os as _os

    p = _os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON")
    if not p or not _os.path.isfile(p):
        return
    try:
        extra = _json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001  # muet-ok : un chargeur optionnel ne casse jamais l'import
        return
    if isinstance(extra, dict):
        for _k, _v in extra.items():
            if isinstance(_v, dict) and isinstance(_v.get("ring"), int) and _v["ring"] >= 3:
                ALLOWED_METHODS[_k] = _v  # noqa: F821  (defini plus haut dans le module)


_charger_intents_offensifs_optionnels()


# ============================================================
# 2. System prompt pour forcer JSON Mode strict
# ============================================================
SYSTEM_PROMPT_JSON_MODE = (
    """Tu es un agent dans Nokido. Tu communiques EXCLUSIVEMENT en JSON-RPC 2.0.

INTERDIT:
- Phrases en français/anglais hors JSON
- Markdown ```code blocks```
- Préambules ("Voici", "Bien sûr", "D'accord")
- Résumés / commentaires explicatifs

OBLIGATOIRE: ta réponse complète = un seul objet JSON valide :
{
  "jsonrpc": "2.0",
  "method": "<verbe parmi ALLOWED_METHODS>",
  "params": { ... },
  "id": "<uuid_court>"
}

Méthodes autorisées : """
    + ", ".join(sorted(ALLOWED_METHODS.keys()))
    + """.

Si tu dois enchaîner plusieurs actions, retourne un tableau d'objets JSON-RPC.
Si tu n'as pas la réponse, réponds {"jsonrpc":"2.0","method":"error","params":{"reason":"..."},"id":"..."}.

EXEMPLES VALIDES :
{"jsonrpc":"2.0","method":"web_search","params":{"query":"AMD XDNA NPU benchmarks 2026"},"id":"a1b2"}
{"jsonrpc":"2.0","method":"embed","params":{"texts":["t1","t2"]},"id":"c3d4"}
"""
)


# ============================================================
# 3. Validation
# ============================================================
class IntentValidationError(Exception):
    pass


def parse_intent(raw: str) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Parse strict JSON-RPC depuis sortie LLM. Lève si invalide.

    Tolérance minimale : retire ```json...``` markdown si présent (LLMs rebelles).
    """
    if not raw or not isinstance(raw, str):
        raise IntentValidationError("empty response")
    s = raw.strip()
    # Strip markdown code fences (LLMs ignorent parfois la consigne)
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise IntentValidationError(f"not valid JSON : {e}")
    return validate_intent(obj)


def validate_intent(obj: Any) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Vérifie schema JSON-RPC 2.0 + whitelist method."""
    if isinstance(obj, list):
        return [validate_intent(o) for o in obj]
    if not isinstance(obj, dict):
        raise IntentValidationError("intent must be object or array")
    if obj.get("jsonrpc") != "2.0":
        raise IntentValidationError("jsonrpc field must be '2.0'")
    method = obj.get("method")
    if not method or not isinstance(method, str):
        raise IntentValidationError("method missing or not str")
    if method not in ALLOWED_METHODS:
        raise IntentValidationError(f"method '{method}' not in whitelist")
    params = obj.get("params", {})
    if not isinstance(params, dict):
        raise IntentValidationError("params must be object")
    if "id" not in obj:
        obj["id"] = uuid.uuid4().hex[:8]
    return obj


def correction_prompt(error: str) -> str:
    """Prompt à renvoyer au LLM s'il a halluciné du texte."""
    return (
        f"Format invalide ({error}). Re-réponds STRICTEMENT en JSON-RPC 2.0 sans texte hors JSON. "
        f"Aucun préambule. Aucun markdown. Schema attendu : "
        '{"jsonrpc":"2.0","method":"<verbe>","params":{...},"id":"<uuid>"}'
    )


# ============================================================
# 4. Trajectory state machine
# ============================================================
@dataclass
class TrajectoryStep:
    intent: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    agent: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    status: str = "pending"  # pending|running|completed|failed


@dataclass
class Trajectory:
    """État complet d'un flow inter-agent. Trace via job_id partagé."""

    job_id: str = field(default_factory=lambda: f"traj_{uuid.uuid4().hex[:12]}")
    steps: List[TrajectoryStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def append(self, intent: Dict[str, Any], agent: str = "") -> TrajectoryStep:
        step = TrajectoryStep(intent=intent, agent=agent)
        self.steps.append(step)
        return step

    def complete(self, step_idx: int, result: Dict[str, Any]) -> None:
        if 0 <= step_idx < len(self.steps):
            self.steps[step_idx].result = result
            self.steps[step_idx].ended_at = time.time()
            self.steps[step_idx].status = "completed"

    def fail(self, step_idx: int, reason: str) -> None:
        if 0 <= step_idx < len(self.steps):
            self.steps[step_idx].status = "failed"
            self.steps[step_idx].ended_at = time.time()
            self.steps[step_idx].result = {"error": reason}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "steps": [asdict(s) for s in self.steps],
            "metadata": self.metadata,
            "started_at": self.started_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ============================================================
# 5. Dispatcher
# ============================================================
DispatcherFn = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
_dispatchers: Dict[str, DispatcherFn] = {}


def register_dispatcher(method: str, fn: DispatcherFn) -> None:
    _dispatchers[method] = fn


async def dispatch_intent(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Route intent JSON-RPC vers son organe registered + hooks motivation auto.

    Si dispatcher inconnu → {jsonrpc, error: -32601 method not found}.
    Hook reward/punish auto via forge_motivation (mesure élégance + escalation frustration).
    Hook is_dead_end : si méthode flagée morte, refuse direct.
    """
    method = intent.get("method")
    if not method:
        return {"jsonrpc": "2.0", "id": intent.get("id"), "error": {"code": -32600, "message": "no method"}}

    # Extract target pour failure tracking (best-effort)
    params = intent.get("params", {})
    target = (
        params.get("target")
        or params.get("ip")
        or params.get("url")
        or params.get("query")
        or params.get("chunk_id")
        or params.get("topic")
        or ""
    )
    if isinstance(target, dict):
        target = json.dumps(target, sort_keys=True)[:120]
    target = str(target)[:120]

    # Dead-end check : router skip méthodes mortes
    try:
        from nokido_agent.app.forge_motivation import is_dead_end

        if is_dead_end(method, target):
            return {
                "jsonrpc": "2.0",
                "id": intent.get("id"),
                "error": {
                    "code": -32004,
                    "message": f"method '{method}' flagged dead_end on target '{target}'. Use revive_dead_end() to reactivate.",
                },
            }
    except ImportError:
        pass

    fn = _dispatchers.get(method)
    if fn is None:
        return {
            "jsonrpc": "2.0",
            "id": intent.get("id"),
            "error": {
                "code": -32601,
                "message": f"method '{method}' not registered (organ: {ALLOWED_METHODS.get(method, {}).get('organ', '?')})",
            },
        }

    import time as _t

    t0 = _t.monotonic()
    try:
        result = await fn(params)
        dt = _t.monotonic() - t0
        # Hook motivation : reward si succès
        try:
            from nokido_agent.app.forge_motivation import reward, punish

            ok = (
                result is not None
                and not (isinstance(result, dict) and result.get("error"))
                and not (isinstance(result, dict) and result.get("ok") is False)
            )
            n_steps = 1
            if isinstance(result, dict) and "n_steps" in result:
                n_steps = int(result.get("n_steps", 1))
            if ok:
                reward_res = reward(method, time_s=dt, n_steps=n_steps, success=True, target=target)
                elegance = reward_res.get("elegance", 1.0)
                # Hook novelty : archive comportement + log si discovery
                try:
                    from nokido_agent.app.forge_novelty_search import observe_intent

                    nov = observe_intent(method, params, True, elegance, target)
                    if isinstance(result, dict):
                        result["_novelty"] = {
                            "score": nov["novelty"],
                            "is_discovery": nov["is_discovery"],
                            "recommend": nov["recommend"],
                        }
                except (ImportError, Exception):
                    pass
                # Hook Friston Active Inference : update generative model + surprise
                try:
                    from nokido_agent.app.forge_active_inference import observe as ai_observe

                    ai = ai_observe(method, target, success=True, time_s=dt, elegance=elegance)
                    if isinstance(result, dict):
                        result["_active_inference"] = {
                            "surprise": ai.get("surprise"),
                            "free_energy": ai.get("free_energy"),
                            "high_surprise": ai.get("high_surprise"),
                        }
                except (ImportError, Exception):
                    pass
                # Hook Oudeyer Flow Zone : classify learning zone
                try:
                    from nokido_agent.app.forge_flow_zone import learning_progress
                    from nokido_agent.app.forge_active_inference import _target_class

                    fz = learning_progress(method, _target_class(target))
                    if isinstance(result, dict):
                        result["_flow_zone"] = {"zone": fz["zone"], "progress": fz["progress"]}
                except (ImportError, Exception):
                    pass
            else:
                err_msg = ""
                if isinstance(result, dict):
                    err_msg = str(result.get("error") or result.get("reason") or "")[:200]
                punish(method, error=err_msg, target=target)
                try:
                    from nokido_agent.app.forge_novelty_search import observe_intent

                    observe_intent(method, params, False, 0.1, target)
                except (ImportError, Exception):
                    pass
                try:
                    from nokido_agent.app.forge_active_inference import observe as ai_observe

                    ai_observe(method, target, success=False, time_s=dt, elegance=0.1)
                except (ImportError, Exception):
                    pass
        except ImportError:
            pass
        return {"jsonrpc": "2.0", "id": intent.get("id"), "result": result}
    except Exception as e:
        dt = _t.monotonic() - t0
        # Punish auto sur exception
        try:
            from nokido_agent.app.forge_motivation import punish

            punish(method, error=f"{type(e).__name__}: {e}"[:200], target=target)
        except ImportError:
            pass
        return {
            "jsonrpc": "2.0",
            "id": intent.get("id"),
            "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"},
        }


# ============================================================
# 6. Trajectory persistence SQLite
# ============================================================
def persist_trajectory(traj: Trajectory, db_path: Optional[Path] = None) -> bool:
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trajectories (
                job_id TEXT PRIMARY KEY,
                steps_json TEXT,
                metadata_json TEXT,
                started_at REAL,
                updated_at REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_traj_started ON trajectories(started_at)")
        conn.execute(
            "INSERT OR REPLACE INTO trajectories (job_id, steps_json, metadata_json, started_at, updated_at) VALUES (?,?,?,?,?)",
            (
                traj.job_id,
                json.dumps([asdict(s) for s in traj.steps], ensure_ascii=False),
                json.dumps(traj.metadata, ensure_ascii=False),
                traj.started_at,
                time.time(),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def load_trajectory(job_id: str, db_path: Optional[Path] = None) -> Optional[Trajectory]:
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT job_id, steps_json, metadata_json, started_at FROM trajectories WHERE job_id=?", (job_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        steps = [TrajectoryStep(**s) for s in json.loads(row[1])]
        return Trajectory(
            job_id=row[0],
            steps=steps,
            metadata=json.loads(row[2]) if row[2] else {},
            started_at=row[3],
        )
    except Exception:
        return None


# ============================================================
# 7. Helpers : LLM call avec JSON Mode
# ============================================================
async def llm_to_intent(
    llm_call_fn: Callable[[str, str], Awaitable[str]], user_prompt: str, max_retries: int = 2
) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Call LLM avec JSON Mode + auto-retry si format invalide.

    Args:
        llm_call_fn: async fn(user_prompt, system_prompt) -> str
        user_prompt: tâche utilisateur
        max_retries: nb max corrections si LLM hallucine
    """
    system = SYSTEM_PROMPT_JSON_MODE
    last_err = ""
    for attempt in range(max_retries + 1):
        prompt = (
            user_prompt
            if attempt == 0
            else f"{user_prompt}\n\n[Erreur tour {attempt}: {last_err}]\n{correction_prompt(last_err)}"
        )
        raw = await llm_call_fn(prompt, system)
        try:
            intent = parse_intent(raw)
            return intent
        except IntentValidationError as e:
            last_err = str(e)
    raise IntentValidationError(f"LLM failed JSON Mode after {max_retries + 1} attempts: {last_err}")


# ============================================================
# 9. Cross-session trajectory analysis (SONA-inspired)
# ============================================================
from collections import defaultdict, Counter


def analyze_trajectories(db_path: Optional[Path] = None, limit: int = 100) -> Dict[str, Any]:
    """Mine patterns from recent persisted trajectories.

    Returns method frequency, success rates, avg duration, common bigrams.
    Equivalent SONA: trajectoire cross-session sans modèle neural — pure stat.
    """
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT steps_json, metadata_json FROM trajectories ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
    except Exception:
        return {}

    method_stats: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "success": 0, "total_duration": 0.0})
    bigrams: Counter = Counter()

    for steps_json, _meta in rows:
        try:
            steps = json.loads(steps_json)
        except Exception:
            continue
        methods_in_traj = []
        for s in steps:
            m = s.get("intent", {}).get("method", "")
            if not m:
                continue
            ok = s.get("status") == "completed"
            dur = 0.0
            if s.get("ended_at") and s.get("started_at"):
                dur = float(s["ended_at"]) - float(s["started_at"])
            method_stats[m]["count"] += 1
            method_stats[m]["success"] += int(ok)
            method_stats[m]["total_duration"] += dur
            methods_in_traj.append(m)
        for a, b in zip(methods_in_traj, methods_in_traj[1:]):
            bigrams[(a, b)] += 1

    result_stats = {}
    for m, v in method_stats.items():
        result_stats[m] = {
            "count": v["count"],
            "success_rate": round(v["success"] / v["count"], 3) if v["count"] else 0,
            "avg_duration_s": round(v["total_duration"] / v["count"], 3) if v["count"] else 0,
        }

    return {
        "trajectories_analyzed": len(rows),
        "method_stats": dict(sorted(result_stats.items(), key=lambda x: -x[1]["count"])),
        "common_sequences": [{"from": a, "to": b, "count": c} for (a, b), c in bigrams.most_common(20)],
    }


def recommend_next_action(
    current_method: str,
    history_methods: Optional[List[str]] = None,
    db_path: Optional[Path] = None,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Markov-chain next-method recommendation from successful trajectories.

    Args:
        current_method: dernier method exécuté.
        history_methods: séquence récente (optionnel, utilisé pour trigrams).
        top_k: nombre de recommandations.

    Returns: [{"method": str, "confidence": float, "organ": str}]
    """
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT steps_json FROM trajectories ORDER BY started_at DESC LIMIT 200").fetchall()
        conn.close()
    except Exception:
        return []

    next_counts: Counter = Counter()
    for (steps_json,) in rows:
        try:
            steps = json.loads(steps_json)
        except Exception:
            continue
        methods = [s.get("intent", {}).get("method", "") for s in steps if s.get("status") == "completed"]
        for i, m in enumerate(methods[:-1]):
            if m == current_method:
                nxt = methods[i + 1]
                if nxt:
                    next_counts[nxt] += 1

    total = sum(next_counts.values()) or 1
    return [
        {
            "method": m,
            "confidence": round(c / total, 3),
            "organ": ALLOWED_METHODS.get(m, {}).get("organ", "?"),
        }
        for m, c in next_counts.most_common(top_k)
    ]


# ============================================================
# 8. CLI debug
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--methods":
        print(json.dumps(ALLOWED_METHODS, indent=2))
    elif len(sys.argv) > 2 and sys.argv[1] == "--validate":
        try:
            v = parse_intent(sys.argv[2])
            print(json.dumps(v, indent=2))
        except IntentValidationError as e:
            print(f"INVALID: {e}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--prompt":
        print(SYSTEM_PROMPT_JSON_MODE)
    else:
        print("Usage:")
        print("  forge_trajectory.py --methods           # list allowed methods")
        print("  forge_trajectory.py --validate '<json>' # test JSON-RPC valid")
        print("  forge_trajectory.py --prompt            # dump system prompt JSON Mode")
