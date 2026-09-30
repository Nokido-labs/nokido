# -*- coding: utf-8 -*-
"""forge_intention_gate.py — Gate d'intention (Agent Policier, moitié 2/2).

DÉRIVE DE SCOPE DÉCLARÉ : détecte un tool_call HORS du périmètre que l'agent a
lui-même DÉCLARÉ (forge_tool_scope, SCOPE_SET), même quand la capacité est
RBAC-autorisée. Niche distincte du RBAC (forge_mcp_rbac = ce que l'admin autorise ;
ici = l'agent fait-il ce qu'il a ANNONCÉ ?). Analogie J-space Anthropic : capter la
dérive d'intention avant l'action.

Réutilise (anti-dup, zéro réinvention) :
  - forge_tool_scope.active_tools_for(agent) = périmètre déclaré (set de tools + CORE).
  - forge_intention_journal.record = trace SSoT append-only.

Rollout : WARN-mode par défaut (LAFORGE_INTENTION_GATE_MODE=warn|error|off).
  warn  : log + trace, N'A JAMAIS bloqué (transition non-cassante).
  error : bloque le tool_call en dérive.
  off   : gate désactivé.
Fail-open partout : toute erreur interne -> aligned (ne casse JAMAIS le dispatch).

Pure : check_scope_drift(active_tools=...) injectable pour tests. Le câblage au
waist dispatch (forge_mcp_registry) est une étape SÉPARÉE (CRITICAL_FILE + reload).
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Set

logger = logging.getLogger("Nokido.IntentionGate")


def _mode() -> str:
    m = (os.environ.get("LAFORGE_INTENTION_GATE_MODE", "warn") or "warn").strip().lower()
    return m if m in ("warn", "error", "off") else "warn"


def _rolescope_enabled() -> bool:
    """Fallback scope-défaut dérivé du système actif ? Défaut OFF (rollout non-cassant).
    ON => un agent sans SCOPE_SET est quand même gaté sur son périmètre de profil
    (ferme le bypass opt-out : ne pas déclarer de scope n'exonère plus du gate)."""
    from nokido_agent.app.forge_drapeau_env import actif as _drapeau

    return _drapeau("LAFORGE_INTENTION_GATE_ROLESCOPE", False)


def check_scope_drift(
    agent: str,
    tool_name: str,
    active_tools: Optional[Set[str]] = None,
    record_journal: bool = True,
) -> dict:
    """Verdict de dérive d'un tool_call vs le scope déclaré de l'agent.

    active_tools : override explicite (tests) ; sinon lu via forge_tool_scope.
    Retour : {aligned, drift, blocked, tool, mode, reason}.
    - mode=off                     -> aligned (gate désactivé).
    - agent sans scope déclaré     -> aligned (no_declared_scope).
    - tool dans le scope (ou CORE) -> aligned (in_scope).
    - sinon                        -> drift ; blocked seulement si mode=error.
    """
    mode = _mode()
    tool_name = str(tool_name or "")
    if mode == "off":
        return {"aligned": True, "drift": False, "blocked": False,
                "tool": tool_name, "mode": mode, "reason": "gate_off"}

    source = "declared"
    if active_tools is None:
        try:
            from nokido_agent.app import forge_tool_scope

            if _rolescope_enabled():
                active_tools, _src = forge_tool_scope.expected_scope_for(agent)
                source = _src or "declared"
            else:
                active_tools = forge_tool_scope.active_tools_for(agent)
        except Exception as e:  # fail-open : indispo -> pas de gate
            logger.debug("[intention_gate] scope lookup indispo (fail-open): %s", e)
            active_tools = None

    if not active_tools:
        return {"aligned": True, "drift": False, "blocked": False,
                "tool": tool_name, "mode": mode, "reason": "no_declared_scope"}

    if tool_name in active_tools:
        return {"aligned": True, "drift": False, "blocked": False,
                "tool": tool_name, "mode": mode, "reason": "in_scope",
                "scope_source": source}

    # ── DÉRIVE ────────────────────────────────────────────────────────────────
    blocked = mode == "error"
    verdict = {
        "aligned": False,
        "drift": True,
        "blocked": blocked,
        "tool": tool_name,
        "mode": mode,
        "reason": f"tool '{tool_name}' hors scope ({source}) de {agent}",
        "scope_source": source,
    }
    logger.warning("[intention_gate][%s] DERIVE agent=%s tool=%s (hors scope declare)",
                   mode.upper(), agent, tool_name)
    if record_journal:
        try:
            from nokido_agent.app import forge_intention_journal as _ij

            _ij.record(agent=agent, intent_type="intention_gate:drift",
                       target=tool_name, payload={"mode": mode, "blocked": blocked})
        except Exception:
            pass  # trace best-effort, ne casse jamais
    return verdict


def gate_tool_call(agent: str, tool_name: str, active_tools: Optional[Set[str]] = None) -> tuple:
    """Interface dispatch (à câbler dans forge_mcp_registry) : (allow, reason).

    WARN/off : allow toujours True (observabilité seule). error : block sur dérive.
    """
    v = check_scope_drift(agent, tool_name, active_tools=active_tools)
    if v["drift"] and v["blocked"]:
        return False, v["reason"]
    return True, v["reason"]
