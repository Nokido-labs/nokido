"""
forge_agent_lats.py — LATS-style wrapper généralisé pour tout agent Nokido.

Phase 9 (2026-05-24) reflexe de survie. Inspire Language Agent Tree Search
mais minimaliste : try -> evaluate -> rollback -> retry-with-context jusqu'a
max_retries. Pour SWE-bench un vrai LATS existe deja (forge_swebench_lats_*).
Ici on offre le pattern a TOUS les agents (pas seulement bench).

Boucle :
  1. snapshot etat (git diff + cwd + env tag)
  2. agent_fn(task, context_enriched) -> resultat
  3. eval_fn(resultat) -> {ok, grade, hints}
  4. si grade=PROMOTED -> release(dopamine) + return resultat
  5. si grade=REJECTED -> rollback (git stash) + release(cortisol)
     + enrichir context avec hints + retry (jusqu'a max_retries)
  6. si max atteint -> release(cortisol level=1.0) + return echec graceful

Le hook eval_fn est pluggable : par defaut accepte tout (PASS). Pour vrai
LATS, brancher forge_scorecard.evaluate_code().

Integration hormones :
  - SUCCESS  -> dopamine level=resultat.confidence
  - RETRY    -> cortisol level=0.5  (stress moyen, on persiste)
  - FAILURE  -> cortisol level=1.0  (echec final, alerte)

Usage :
    from forge_agent_lats import run_with_lats
    res = run_with_lats(
        agent_fn=lambda task, ctx: my_agent.run(task, ctx),
        task="implement feature X",
        eval_fn=my_eval,                   # default: accept all
        max_retries=3,
        agent_name="agt_planner",
    )
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("forge_agent_lats")

ROOT = Path(__file__).resolve().parent.parent


def _git(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), *cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        errors="replace")
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _snapshot_state() -> dict[str, Any]:
    rc, head, _ = _git(["rev-parse", "HEAD"])
    rc2, status, _ = _git(["status", "--porcelain"])
    return {
        "head": head if rc == 0 else "unknown",
        "dirty": bool(status) if rc2 == 0 else None,
        "ts": time.time(),
    }


# Phase 16 (2026-05-24) — remplace git stash global (race garantie inter-agents
# selon critique 5-voix LLM) par git worktree isole par agent. Plan agent design.
import shutil
import tempfile
import uuid
from contextlib import contextmanager

# Phase 23A (2026-05-24) hardening : critique Plan-securite a montre que
# tempfile.gettempdir() (= the user AppData\Local\Temp) = TOCTOU +
# symlink hostile possible. Nouveau : ROOT/sandbox/lats_worktrees/ (ACL
# heritee de sandbox/ deja restreint Nokido user) + reject pre-existing
# symlink + os.makedirs strict.
WORKTREE_ROOT = ROOT / "sandbox" / "lats_worktrees"


def _worktree_create(agent_name: str) -> Path:
    # Phase 23A : strict create + symlink reject
    if WORKTREE_ROOT.exists() and WORKTREE_ROOT.is_symlink():
        raise RuntimeError(f"WORKTREE_ROOT {WORKTREE_ROOT} is a symlink — refuse")
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    wt_path = WORKTREE_ROOT / f"{agent_name}-{uuid.uuid4().hex[:8]}"
    # Si le chemin existe deja (collision uuid extreme OU attaquant pre-cree
    # un symlink), refuse plutot que de l'utiliser (worktree add aurait fail
    # mais autant le dire explicitement).
    if wt_path.exists() or wt_path.is_symlink():
        raise RuntimeError(f"worktree path {wt_path} pre-exists — refuse (TOCTOU)")
    rc, _, err = _git(["worktree", "add", "--detach", str(wt_path), "HEAD"], timeout=30.0)
    if rc != 0:
        raise RuntimeError(f"worktree add failed: {err}")
    # Verif post-create : le dossier doit etre un vrai dir, pas un symlink
    if wt_path.is_symlink():
        # symlink est apparu pendant 'git worktree add' (race) — destroy + refuse
        try:
            _git(["worktree", "remove", "--force", str(wt_path)], timeout=15.0)
        except Exception:
            pass
        raise RuntimeError("worktree path became symlink after create — TOCTOU")
    return wt_path


def _worktree_destroy(wt_path: Path) -> None:
    rc, _, err = _git(["worktree", "remove", "--force", str(wt_path)], timeout=30.0)
    if rc != 0:
        logger.warning("worktree remove failed: %s — fallback rmtree", err)
        shutil.rmtree(wt_path, ignore_errors=True)
    _git(["worktree", "prune"], timeout=10.0)


@contextmanager
def _isolated_worktree(agent_name: str):
    wt = _worktree_create(agent_name)
    try:
        yield wt
    finally:
        _worktree_destroy(wt)


# Phase 37 step 2 (2026-05-25) — Ring Buffer Rewind integration (NANO-inspired).
# start_recording avant boucle, push events via callback ctx["_lats_rb_push"],
# sur REJECTED dump_window pour enrichir ctx["_lats_rewind"] retry, teardown
# stop_recording dans finally.
def _rb_start(agent_name: str, trace_id: str):
    try:
        from nokido_agent.app.forge_ring_buffer import start_recording

        start_recording(agent_id=agent_name, trace_id=trace_id, window_s=60.0)
    except Exception:
        pass


def _rb_push(trace_id: str, kind: str, payload: dict) -> bool:
    try:
        from nokido_agent.app.forge_ring_buffer import push as _push

        return _push(trace_id, kind, payload)
    except Exception:
        return False


def _rb_dump(trace_id: str, since_ts: float | None = None) -> list[dict]:
    try:
        from nokido_agent.app.forge_ring_buffer import dump_window

        return dump_window(trace_id, since_ts=since_ts)
    except Exception:
        return []


def _rb_stop(trace_id: str) -> int:
    try:
        from nokido_agent.app.forge_ring_buffer import stop_recording

        return stop_recording(trace_id)
    except Exception:
        return 0


def _git_reset_clean(wt_path: Path) -> None:
    """Reset hard + clean -fdx dans le worktree. Utilise entre 2 attempts
    LATS au lieu de detruire+recreer le worktree (plus rapide ~50ms vs 500ms)."""
    import subprocess as _sp

    _sp.run(["git", "-C", str(wt_path), "reset", "--hard", "HEAD"], capture_output=True, timeout=10)
    _sp.run(["git", "-C", str(wt_path), "clean", "-fdx"], capture_output=True, timeout=10)


def _release_hormone(hormone: str, level: float, payload: dict, receptors: list[str]) -> None:
    try:
        from nokido_agent.app.forge_hormones import release

        release(hormone, level=level, payload=payload, receptors=receptors)
    except Exception as exc:
        logger.debug("hormone release skipped: %s", exc)


def _default_eval(result: Any) -> dict[str, Any]:
    """Eval permissif par defaut : tout PASS sauf si result est None/error."""
    if result is None:
        return {"ok": False, "grade": "REJECTED", "hints": ["null result"]}
    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "grade": "REJECTED", "hints": [str(result["error"])[:200]]}
    return {"ok": True, "grade": "PROMOTED", "hints": []}


def run_with_lats(
    agent_fn: Callable[[str, dict], Any],
    task: str,
    eval_fn: Callable[[Any], dict[str, Any]] | None = None,
    max_retries: int = 3,
    agent_name: str = "anonymous",
    initial_context: dict | None = None,
    rollback_on_reject: bool = True,
) -> dict[str, Any]:
    """Run agent_fn avec retry+rollback inspire LATS.

    Args:
        agent_fn(task, ctx) -> Any : la fonction agent.
        task : description tache (string).
        eval_fn(result) -> {ok, grade, hints} : evaluation. None = permissif.
        max_retries : 0 = pas de retry (1 tentative seule). 3 = jusqu'a 4 essais.
        agent_name : pour logs et receptors hormones.
        initial_context : dict passe a agent_fn comme ctx la 1ere fois.
        rollback_on_reject : git stash on REJECTED (default True).

    Returns:
        {ok, attempts, final_result, history: [{attempt, result, eval, hormone}]}
    """
    eval_fn = eval_fn or _default_eval
    ctx = dict(initial_context or {})
    history: list[dict[str, Any]] = []
    snap_before = _snapshot_state()
    receptors_ok = [agent_name, "orchestrator"]
    receptors_warn = [agent_name, "orchestrator", "supervisor"]
    # Phase 37 step 2 ring buffer rewind init
    trace_id = ctx.get("_lats_trace_id") or f"lats-{agent_name}-{uuid.uuid4().hex[:8]}"
    ctx["_lats_trace_id"] = trace_id
    ctx["_lats_rb_push"] = lambda kind, payload: _rb_push(trace_id, kind, payload)
    _rb_start(agent_name, trace_id)
    # Phase 16 worktree isolation : 1 worktree par appel run_with_lats. Agents
    # parallele ne se marchent plus dessus (vs git stash global). agent_fn doit
    # lire ctx["cwd"] pour ses subprocess (sinon isolation rompue silencieusement).
    _git(["worktree", "prune"], timeout=5.0)  # cleanup zombies sessions crashees
    wt_ctx = None
    wt_path = None
    if rollback_on_reject:
        try:
            wt_ctx = _isolated_worktree(agent_name)
            wt_path = wt_ctx.__enter__()
            ctx["cwd"] = str(wt_path)
        except RuntimeError as exc:
            logger.warning("worktree setup failed (%s) — fallback no-isolation", exc)
            wt_ctx = None

    try:
        for attempt in range(1, max_retries + 2):  # 1 essai initial + max_retries retries
            t0 = time.monotonic()
            try:
                result = agent_fn(task, ctx)
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
                _rb_push(trace_id, "exception", {"type": type(exc).__name__, "msg": str(exc)[:500], "attempt": attempt})
            ev = eval_fn(result)
            rec = {
                "attempt": attempt,
                "duration_s": round(time.monotonic() - t0, 2),
                "grade": ev.get("grade"),
                "hints": ev.get("hints", []),
                "result_preview": str(result)[:300],
            }
            history.append(rec)
            if ev.get("ok"):
                _release_hormone(
                    "dopamine",
                    level=0.7,
                    payload={"agent": agent_name, "task": task[:200], "attempt": attempt},
                    receptors=receptors_ok,
                )
                return {
                    "ok": True,
                    "attempts": attempt,
                    "final_result": result,
                    "snapshot_before": snap_before,
                    "history": history,
                }
            # REJECTED — rollback worktree + enrich context + retry
            if attempt > max_retries:
                break
            if rollback_on_reject and wt_path is not None:
                _git_reset_clean(wt_path)
                rec["rolled_back"] = True
            # Phase 37 step 2 : dump ring buffer window pour enrichir contexte retry
            try:
                rewind = _rb_dump(trace_id, since_ts=t0)
                ctx["_lats_rewind"] = rewind
                rec["rewind_events"] = len(rewind)
            except Exception:
                pass
            # enrich context with failure feedback (inside for body, post-rollback)
            prev_failures = ctx.setdefault("_lats_prev_failures", [])
            prev_failures.append(
                {
                    "attempt": attempt,
                    "hints": ev.get("hints", []),
                    "result_preview": rec["result_preview"],
                }
            )
            _release_hormone(
                "cortisol",
                level=0.5,
                payload={"agent": agent_name, "task": task[:200], "attempt": attempt, "hints": ev.get("hints", [])},
                receptors=receptors_warn,
            )
        # All retries exhausted (out of for, still in try)
        _release_hormone(
            "cortisol",
            level=1.0,
            payload={"agent": agent_name, "task": task[:200], "attempts": attempt, "exhausted": True},
            receptors=receptors_warn,
        )
    finally:
        if wt_ctx is not None:
            try:
                wt_ctx.__exit__(None, None, None)
            except Exception as exc:
                logger.warning("worktree teardown err: %s", exc)
        # Phase 37 step 2 : libérer le ring buffer
        try:
            captured = _rb_stop(trace_id)
            logger.debug("ring buffer trace=%s captured=%d events", trace_id, captured)
        except Exception:
            pass
    return {
        "ok": False,
        "attempts": attempt,
        "final_result": history[-1]["result_preview"] if history else None,
        "snapshot_before": snap_before,
        "history": history,
        "reason": "max_retries exhausted",
    }


if __name__ == "__main__":
    # smoke
    import json

    def fake_agent(task, ctx):
        attempt = len(ctx.get("_lats_prev_failures", [])) + 1
        if attempt < 2:
            return {"error": "synthetic fail"}
        return {"ok": True, "data": f"success at attempt {attempt}"}

    res = run_with_lats(fake_agent, "test_task", max_retries=3, agent_name="smoke", rollback_on_reject=False)
    print(json.dumps(res, indent=2, default=str))
