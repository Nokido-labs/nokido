"""forge_swarm_orchestrator.py — orchestrateur Map-Reduce (ForgeSwarm M5).

Assemble TOUT : validator (M0) → DAGRunner (existant) pilotant les workers (M2)
contre un overlay partagé (patch) → commit ATOMIQUE (M5). C'est le `run_forge_swarm`
appelé par le verbe MCP `forge_spawn_swarm` (M6).

    res = await run_forge_swarm(plan, root, infer_fn, import_graph=..., emit=...)

Pipeline :
  1. MAP    : `plan` est déjà le DAG (produit par GOAP en amont).
  2. GATE   : validate_swarm_plan (refus déterministe avant de brûler l'APU).
  3. SWARM  : DAGRunner(executor=worker).run → rounds //, deps respectées, overlay partagé.
              Fail-fast : un consommateur dont une dépendance échoue est SKIP.
  4. REDUCE : tous OK → overlay.commit (disque, all-or-nothing). Un seul échec →
              overlay.discard (rollback total, zéro état partiel) + escalade.

Le commit GIT final reste à l'appelant (agent principal, ring autorisé).
"""

from __future__ import annotations

from pathlib import Path

from nokido_agent.app.forge_dag_runner import DAGRunner
from nokido_agent.app.forge_swarm_patch import VFSOverlay
from nokido_agent.app.forge_swarm_validator import validate_swarm_plan
from nokido_agent.app.forge_swarm_worker import run_worker


def _is_fail(result) -> bool:
    if isinstance(result, str):  # DAGRunner encode exceptions/timeout en str "ERR:"/"TIMEOUT:"
        return True
    return isinstance(result, dict) and not result.get("ok")


async def run_forge_swarm(
    plan: list[dict],
    root: str | Path,
    infer_fn,
    *,
    import_graph: dict | None = None,
    emit=None,
    dry_run: bool = False,
    timeout_per_step: float = 120.0,
) -> dict:
    """Exécute l'essaim. Retourne {ok, stage, touched?, failed?, results?, errors?}."""
    root = Path(root)

    # 2. GATE déterministe
    ok, errs = validate_swarm_plan(plan, root, import_graph)
    if not ok:
        if emit:
            emit("swarm_rejected", {"errors": errs})
        return {"ok": False, "stage": "validate", "errors": errs}

    if emit:
        emit("swarm_start", {"tasks": [t.get("task_id") for t in plan], "n": len(plan)})

    overlay = VFSOverlay(root)
    failed: set[str] = set()
    # DAGRunner clé sur step["id"] -> on aligne id = task_id.
    steps = [{**t, "id": t.get("task_id", f"s{i}")} for i, t in enumerate(plan)]

    async def _exec(step: dict):
        sid = step["id"]
        if any(d in failed for d in step.get("deps", [])):
            failed.add(sid)
            return {"task_id": sid, "ok": False, "skipped": True, "error": "dépendance échouée"}
        try:
            r = await run_worker(step, overlay, infer_fn, emit=emit)
        except BaseException:
            # Un pas coupe par le timeout du DAGRunner (CancelledError) ou qui leve ne revient
            # jamais ici. Sans cette marque il manquait a `failed` : ok=False avec failed=[]
            # (essaim local du 26/09, 10 TIMEOUT), et ses DEPENDANTS s'executaient sur un
            # overlay prive du patch dont ils dependent (DAGRunner le range quand meme `done`).
            failed.add(sid)
            raise
        if not r.get("ok"):
            failed.add(sid)
        return r

    run = await DAGRunner(_exec).run(steps, timeout_per_step=timeout_per_step)
    results = run.get("results", {})

    # 4. REDUCE -- un echec se lit sur les RESULTATS, pas seulement sur ce que _exec a vu :
    # TIMEOUT/ERR arrivent en chaine, et un pas jamais execute (DAG bloque) n'est pas prouve.
    echecs = set(failed) | {sid for sid, r in results.items() if _is_fail(r)}
    echecs |= {s["id"] for s in steps if s["id"] not in results}
    if echecs:
        overlay.discard()
        if emit:
            emit("swarm_fail", {"failed": sorted(echecs)})
        return {"ok": False, "stage": "execute", "failed": sorted(echecs), "results": results,
                "errors": run.get("errors") or {}}

    touched = overlay.commit(dry_run=dry_run)
    if emit:
        emit("swarm_done", {"touched": touched, "n": len(plan)})
    return {"ok": True, "stage": "done", "touched": touched, "results": results}
