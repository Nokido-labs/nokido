"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_context_steadiness
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_context_steadiness.py
=================================
CONTEXT_STEADINESS_V1 — Stabilite de contexte entre etapes LLM.
Injecte un header STATUS_CHECK dans chaque prompt.
Resumes incrementaux pour ne pas depasser max_history_tokens=4000.
"""

import time, threading

MAX_HISTORY_TOKENS = 4000
CHARS_PER_TOKEN = 3.5  # estimation Python dense

_state_lock = threading.Lock()
_state: dict = {
    "current_task": "",
    "step_n": 0,
    "total_steps": 0,
    "last_mcp_output": "",
    "history": [],  # liste de (step, task, result_short)
    "started_at": None,
}


def update_state(task: str = "", step: int = 0, total: int = 0, last_output: str = "") -> None:
    """Met à jour le contexte courant.

    Args:
        task (str): La tâche en cours.
        step (int): Le numéro de l'étape actuelle.
        total (int): Le nombre total d'étapes.
        last_output (str): La dernière sortie à afficher.

    Returns:
        None
    """
    with _state_lock:
        if task:
            _state["current_task"] = task
        if step:
            _state["step_n"] = step
        if total:
            _state["total_steps"] = total
        if last_output:
            _state["last_mcp_output"] = last_output[:200]
            _state["history"].append(
                {
                    "ts": time.strftime("%H:%M:%S"),
                    "step": _state["step_n"],
                    "task": _state["current_task"][:60],
                    "result": last_output[:100],
                }
            )
            # Incremental_Update : garder seulement l'historique récent
            _trim_history()
        if not _state["started_at"]:
            _state["started_at"] = time.strftime("%H:%M:%S")


def _trim_history() -> None:
    """Supprime l'historique ancien pour rester sous max_history_tokens."""
    while True:
        total_chars = sum(len(str(h)) for h in _state["history"])
        if total_chars / CHARS_PER_TOKEN <= MAX_HISTORY_TOKENS:
            break
        if len(_state["history"]) <= 2:
            break
        _state["history"].pop(0)  # supprimer le plus ancien


def get_status_header() -> str:
    """
    Genere le header STATUS_CHECK a injecter dans les prompts LLM.
    Format compact pour ne pas polluer le contexte.
    """
    with _state_lock:
        task = _state["current_task"] or "?"
        step_n = _state["step_n"] or 0
        total = _state["total_steps"] or "?"
        last = _state["last_mcp_output"] or "none"
        return f"[STATUS_CHECK: tache={task} | etape={step_n}/{total} | dernier_resultat={last[:80]}]\n"


def inject_header(prompt: str, task: str = "", step: int = 0, total: int = 0) -> str:
    """
    Injecte le STATUS_CHECK en tete du prompt.
    Met a jour le state avant injection.
    """
    if task or step:
        update_state(task=task, step=step, total=total)
    header = get_status_header()
    return header + prompt


def get_summary() -> str:
    """Resume incremental de l'historique pour contexte long."""
    with _state_lock:
        if not _state["history"]:
            return ""
        lines = [f"  {h['ts']} step{h['step']}: {h['task']} → {h['result']}" for h in _state["history"][-5:]]
        return "Historique recent:\n" + "\n".join(lines)


def reset() -> None:
    """Remet le contexte a zero (nouveau batch)."""
    with _state_lock:
        _state.update(
            {
                "current_task": "",
                "step_n": 0,
                "total_steps": 0,
                "last_mcp_output": "",
                "history": [],
                "started_at": None,
            }
        )
