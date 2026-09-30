# -*- coding: utf-8 -*-
"""
forge_separation.py — Invariant separation_of_powers enforcement.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/integrity : invariant separation_of_powers"  # organe declare le 2026-09-06 (audit de raccordement)

import os
import sqlite3
import logging
from pathlib import Path
from typing import Any, Tuple

logger = logging.getLogger(__name__)

def normalize_agent(name: str) -> str:
    """Normalizes agent names (e.g. agt_claude -> CLAUDE)."""
    if not name:
        return ""
    name = name.upper().strip()
    if name.startswith("AGT_"):
        name = name[4:]
    return name

def _sep_deny(actor: str, reason: str) -> Tuple[bool, str]:
    """Emet le deny vers le capteur d'alignement (P1) puis renvoie (False, reason).
    emit(actor, invariant, verdict, ...) ; import direct (tools/ dans le path au
    runtime hub) ; fallback silencieux."""
    try:
        from nokido_agent.tools.forge_alignment_trace import emit
        emit(str(actor), "separation_of_powers", "deny", reason=reason[:200])
    except Exception:
        pass
    return False, reason


# Lignage par agent (collusion-by-lineage : 2 agents de meme lignee ne se valident pas).
# Local volontairement absent (modeles locaux divers = juges legitimement diversifies).
_LINEAGE = {"CLAUDE": "anthropic", "AGY": "google", "GEMINI": "google",
            "CODEX": "openai", "COPILOT": "openai"}


def _lineage(agent_normalized: str):
    return _LINEAGE.get(agent_normalized)


def enforce_separation(actor_agent: str, action: str, target: Any,
                       ring: int | None = None) -> Tuple[bool, str]:
    """
    Enforces the separation of powers invariant.
    An agent cannot validate/score its own work, and cannot edit its own judge.
    
    Args:
        actor_agent: Name of the agent performing the action (e.g. 'CLAUDE', 'GEMINI').
        action: The type of action ('governed_edit', 'validate_task', 'task.result', 'task.review').
        target: The target of the action (file path for governed_edit, task_id/dict for tasks).
        
    Returns:
        (True, "") if allowed, (False, reason) if denied.
    """
    actor_normalized = normalize_agent(actor_agent)
    
    if action == "governed_edit":
        # Target is file path.
        path_str = str(target).replace("\\", "/").lower()
        # forge_alignment_invariants RETIRE : c'est le DASHBOARD des invariants (trace
        # l'enforcement), PAS un module qui SCORE les agents. L'y inclure bloquait la
        # maintenance legitime du dashboard (faux-positif revele au reload). Aligne sur
        # forge_governed_edit.JUDGE_MODULES (source des vrais modules-juges).
        forbidden_keywords = [
            "forge_trust_score",
            "forge_pool_registry",
            "forge_scorecard",
            "forge_meta_evolution",
            "forge_agents",
            "forge_evolutionary_stack",
            "forge_orchestration_gate",
        ]
        if any(kw in path_str for kw in forbidden_keywords):
            # TRANSPORTER L'IDENTITE, JAMAIS LA RECALCULER (mesure 2026-09-07).
            # `ring` = ring DEJA RESOLU par l'appelant (le hub l'a fait, avec le
            # jeton et le magasin) ; None = non transmis, et ca se dit.
            #
            # Ce bloc appelait `resolve_identity(actor_agent, local=True)` -- sans
            # jeton et sans magasin. Or le videur n'accorde `via="token"` que si on
            # lui passe les DEUX (`if agent and token and agent_tokens`). Prive
            # d'eux, il retombe sur `via="header"` et applique le plancher
            # anti-spoof `_HEADER_FLOOR_RING = 4` : le chiffre affiche mesurait la
            # pauvrete de l'appel, pas l'appelant.
            #
            # Consequence mesuree : un agent de ring 1 AUTHENTIFIE (jeton a bail de
            # 30 min, `forge_agent_credential.etat()` -> mode COURT ; et
            # `nokido_hub._resolve_ring` refuse en `bad_token` tout jeton non
            # apparie AVANT d'appeler le videur, donc un appel qui aboutit est
            # authentifie par construction) se voyait refuser au nom d'un « ring 4 »
            # qui n'a jamais ete le sien. Un garde qui accuse a faux se fait
            # desarmer -- d'ou la correction, immediate.
            #
            # LA REGLE DE FOND NE BOUGE PAS : `ring > 0` refuse. Meme un ring 1
            # prouve ne peut pas editer un module juge ; seul le ring 0 le peut.
            # Rendre la mesure honnete ne desserre aucun droit.
            _ring = None
            if ring is not None:
                try:
                    _ring = int(ring)
                except (TypeError, ValueError):
                    _ring = None   # illisible -> non transmis, jamais un chiffre invente
            if _ring is not None:
                if _ring > 0:
                    return _sep_deny(actor_agent, f"Agent '{actor_agent}' (ring {_ring}) is forbidden from editing judge module '{target}'")
                # ring 0 : le seul habilite a maintenir un juge -> on laisse passer.
            elif actor_normalized not in ("SYSTEM", "NOKIDO", "LOCAL"):
                # Ring NON TRANSMIS : fail-closed, et le motif le DIT au lieu
                # d'afficher un plancher comme s'il s'agissait d'une mesure.
                return _sep_deny(actor_agent, f"Agent '{actor_agent}' (ring non transmis) is forbidden from editing judge module '{target}'")
                    
    elif action in ("validate_task", "task.review"):
        # Target is task_id (str) or task dict
        to_agent = None
        if isinstance(target, dict):
            to_agent = target.get("to_agent") or target.get("agent")
        elif isinstance(target, str):
            db_path = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sandbox" / "tasks.db"))
            if db_path.exists():
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT agent FROM tasks WHERE id=?", (target,))
                    row = cursor.fetchone()
                    if row:
                        to_agent = row[0]
                    conn.close()
                except Exception:
                    pass
                    
        if to_agent:
            to_normalized = normalize_agent(to_agent)
            if actor_normalized == to_normalized:
                return _sep_deny(actor_agent, f"Agent '{actor_agent}' cannot validate or review its own task work (separation of powers)")
            a_lin, t_lin = _lineage(actor_normalized), _lineage(to_normalized)
            if a_lin and t_lin and a_lin == t_lin:
                return _sep_deny(actor_agent, f"Agent '{actor_agent}' ({a_lin}) cannot validate same-lineage agent '{to_agent}' ({t_lin}) (collusion-by-lineage)")
                
    elif action == "task.result":
        # Target is task_id (str) or task dict.
        # We ensure the worker is not the same as the creator/validator of the task.
        from_agent = None
        to_agent = None
        if isinstance(target, dict):
            from_agent = target.get("from_agent")
            to_agent = target.get("to_agent") or target.get("agent")
        elif isinstance(target, str):
            db_path = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sandbox" / "tasks.db"))
            if db_path.exists():
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT from_agent, agent FROM tasks WHERE id=?", (target,))
                    row = cursor.fetchone()
                    if row:
                        from_agent, to_agent = row[0], row[1]
                    conn.close()
                except Exception:
                    pass
                    
        if from_agent and to_agent:
            from_normalized = normalize_agent(from_agent)
            to_normalized = normalize_agent(to_agent)
            if from_normalized == to_normalized:
                return _sep_deny(actor_agent, f"Creator/Validator '{from_agent}' cannot be the same as worker '{to_agent}' (separation of powers)")
                
    return True, ""
