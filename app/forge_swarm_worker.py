"""forge_swarm_worker.py — worker éphémère (ForgeSwarm M2).

Un sous-agent "niveau 2" STÉRILE : reçoit UNE tâche, voit un contexte confiné
(M1 `forge_swarm_context`), produit un patch Search/Replace, appliqué + validé
dans un overlay mémoire (`forge_swarm_patch`). Self-heal BORNÉ (`max_retries`)
avec triage par classe d'erreur + early-exit anti-thrashing.

L'inférence est INJECTÉE (`infer_fn(prompt) -> str | awaitable`) → testable avec
un faux LLM, sans dépendre d'un backend (llama.cpp/ollama branchés en M3).
"""

from __future__ import annotations

import inspect

from nokido_agent.app.forge_swarm_context import build_worker_context
from nokido_agent.app.forge_swarm_patch import PatchError, VFSOverlay  # noqa: F401  (VFSOverlay = type attendu)

WORKER_SYSTEM = (
    "Tu es un sous-agent de niveau 2. Applique l'INSTRUCTION sur la CIBLE. "
    "Réponds UNIQUEMENT par un ou des blocs SEARCH/REPLACE (format Aider) : "
    "<<<<<<< SEARCH / ======= / >>>>>>> REPLACE. Aucune justification, aucun texte."
)


def _targets(task: dict) -> list[str]:
    return list(task.get("targets") or task.get("context_files") or [])


def _build_prompt(task: dict, overlay: "VFSOverlay", last_error: str | None) -> str:
    ctx = build_worker_context(
        _targets(task), task.get("reference_files") or [], overlay.root, read_fn=overlay.read
    )
    parts = [WORKER_SYSTEM, "", "## INSTRUCTION", str(task.get("prompt", "")), "", ctx]
    if last_error:
        parts += ["", "## ERREUR PRÉCÉDENTE — corrige-la, ne la répète pas", last_error[:800]]
    return "\n".join(parts)


def _similar(a: str, b: str) -> bool:
    """Anti-thrashing : deux erreurs au même préfixe = on tourne en rond."""
    return a[:120] == b[:120]


async def run_worker(
    task: dict,
    overlay: "VFSOverlay",
    infer_fn,
    max_retries: int = 3,
    emit=None,
) -> dict:
    """Exécute une tâche worker contre `overlay`. Retourne
    {task_id, ok, op, attempts, error?}. Sur succès, l'overlay est muté
    (atomique par op) ; sur échec, l'overlay reste intact (escalade au plan)."""
    tid = task.get("task_id", "?")
    op_kind = task.get("op", "edit_sr")
    tgts = _targets(task)
    if emit:
        emit("agent_start", {"task_id": tid, "op": op_kind, "targets": tgts})

    # Ops sans inférence (contenu déjà fourni) : create/delete/rename direct.
    if op_kind in ("create", "delete", "rename", "noop"):
        try:
            overlay.apply({
                "op": op_kind,
                "target": (tgts[0] if tgts else task.get("target")),
                "content": task.get("content", ""),
                "new_path": task.get("new_path"),
            })
            if emit:
                emit("agent_reply", {"task_id": tid, "op": op_kind, "ok": True})
            return {"task_id": tid, "ok": True, "op": op_kind, "attempts": 0}
        except PatchError as e:
            if emit:
                emit("agent_fail", {"task_id": tid, "error": str(e)})
            return {"task_id": tid, "ok": False, "op": op_kind, "error": str(e), "attempts": 0}

    # edit_sr : boucle d'inférence + self-heal.
    target = tgts[0] if tgts else task.get("target")
    errors: list[str] = []
    attempt = 0
    for attempt in range(1, max_retries + 1):
        out = infer_fn(_build_prompt(task, overlay, errors[-1] if errors else None))
        if inspect.isawaitable(out):
            out = await out
        try:
            overlay.apply({"op": "edit_sr", "target": target, "text": str(out)})
            if emit:
                emit("agent_reply", {"task_id": tid, "attempt": attempt, "ok": True})
            return {"task_id": tid, "ok": True, "op": "edit_sr", "attempts": attempt}
        except PatchError as e:
            err = str(e)
            errors.append(err)
            if emit:
                emit("agent_retry", {"task_id": tid, "attempt": attempt, "error": err[:200]})
            # early-exit anti-thrashing : même erreur que le tour précédent
            if len(errors) >= 2 and _similar(errors[-1], errors[-2]):
                break

    if emit:
        emit("agent_fail", {"task_id": tid, "error": errors[-1] if errors else "?"})
    return {
        "task_id": tid,
        "ok": False,
        "op": "edit_sr",
        "error": errors[-1] if errors else "échec",
        "attempts": attempt,
    }
