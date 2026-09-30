"""
forge_mcp_rbac.py — RBAC mapping outils MCP → ring minimal (Phase 35).

Reuse forge_integrity.IntegrityRing existant. Mapping declaratif tool_name
-> ring requis. Helper `check_tool_capability(tool, agent, ring)` appele
dans forge_mcp_registry.dispatch() pour early-return 403 si insuffisant.

Phase 35 step 2 (2026-05-25) :
- Mode WARN (default) : log denial mais AUTORISE (transition non-cassante)
- Mode ENFORCE : bloque vraiment (env LAFORGE_RBAC_MODE=enforce)
- Mapping etendu 60+ tools MCP (handle_*)

Pattern : agent JWT scoped Phase 23C donne ring derive. dispatch check
RBAC tool-level avant execution. Defense in depth :
  - Couche 1 (Phase 23C) : JWT scope global (services:start, admin:*)
  - Couche 2 (Phase 35) : ring minimum pour outil specifique
  - Couche 3 (forge_integrity SCOPE_REQUIRED_RING) : fs/rag/sql/tasks ops fines
"""

from __future__ import annotations

import logging
import os
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

_MODE = os.environ.get("LAFORGE_RBAC_MODE", "enforce").lower()
_ENFORCE = _MODE != "warn"

logger = logging.getLogger("forge_mcp_rbac")

try:
    from nokido_agent.app.forge_integrity import IntegrityRing

    _RING_OK = True
except ImportError:
    _RING_OK = False

    # Fallback aligne convention Nokido : ring INFERIEUR = PLUS de droits
    class IntegrityRing:  # type: ignore
        MASTER = -1
        SYSTEM = 0
        DEV = 1
        TRUSTED = 2
        COLLAB = 3
        UNTRUSTED = 4


# Convention Nokido (forge_integrity) : ring INFERIEUR = PLUS de droits.
# Tool _TOOL_REQUIRED_RING[name] = ring MAXIMUM acceptable (= droits minimum).
# Verification : agent_ring <= required_ring = autorise.
# Phase 35 step 2 : mapping etendu 60+ tools handle_* (grep forge_mcp_registry).
# COMPLETUDE MESUREE LE 2026-09-12. Le registre expose 81 handlers `handle_*` ;
# 71 figuraient ici. Les 14 manquants n'etaient pas « refuses par defaut » mais
# AUTORISES : `check_tool_capability(..., permissive_unknown=True)` rend
# (True, "tool_unmapped_permissive_default"), et le dispatch l'appelle sans
# desarmer ce defaut. Seul `_get_ring_needed` (defaut 2) les rattrapait — une
# defense en profondeur, pas une declaration.
#
# Chaque valeur ci-dessous est le plafond EFFECTIF mesure ce jour-la, de sorte
# que cette declaration ne change AUCUN comportement : elle rend explicite ce
# qui etait deja applique.
#
# ⚠️ DEUX DIVERGENCES A ARBITRER PAR L'OWNER, rendues visibles et non tranchees
# ici : `governed_edit` et `agy_config` sont plafonnes a 3 parce que la table
# `forge_tools` de RAG/embeddings.db le dit, alors que l'intention codee dans
# `_get_ring_needed` vaut respectivement 1 et 1-si-action=write. Les resserrer
# couperait les agents de ring 3 qui s'en servent aujourd'hui ; les laisser
# entérine un assouplissement venu d'une base que le client peut ecrire.
_TOOL_REQUIRED_RING: dict[str, int] = {
    # --- les 14 completes le 2026-09-12 (plafond effectif mesure) ---
    "absorb_rfc_knowledge": 2,
    "agy_add_dir": 2,
    "agy_config": 3,          # divergence : intention codee = 1 si action=write
    "agy_run": 2,
    "delegate_to_local_scout": 2,
    "docker_action": 2,
    "governed_edit": 3,       # divergence : intention codee = 1
    "introspect": 2,
    "md": 2,
    "query_documentation": 2,
    "query_json": 2,
    "query_local_json": 2,
    "search_local_file": 2,
    "tool_scope": 2,
    # UNTRUSTED max (ring 4) : read-only / safe / monitoring
    "read": int(IntegrityRing.UNTRUSTED),
    "read_function_body": int(IntegrityRing.UNTRUSTED),
    "rag": int(IntegrityRing.UNTRUSTED),
    "query": int(IntegrityRing.UNTRUSTED),
    "graph_ppr": int(IntegrityRing.UNTRUSTED),
    "graph_edge_score": int(IntegrityRing.UNTRUSTED),
    "blackboard_read_zone": int(IntegrityRing.UNTRUSTED),
    "get_file_skeleton": int(IntegrityRing.UNTRUSTED),
    "get_function_dependencies": int(IntegrityRing.UNTRUSTED),
    "forge_stats": int(IntegrityRing.UNTRUSTED),
    "biblio": int(IntegrityRing.UNTRUSTED),
    "web_search": int(IntegrityRing.UNTRUSTED),
    "web_search_rag": int(IntegrityRing.UNTRUSTED),
    "research_agent": int(IntegrityRing.UNTRUSTED),
    "whoami": int(IntegrityRing.UNTRUSTED),
    "list_providers": int(IntegrityRing.UNTRUSTED),
    "task_status": int(IntegrityRing.UNTRUSTED),
    "quota_status": int(IntegrityRing.UNTRUSTED),
    "quota_model": int(IntegrityRing.UNTRUSTED),
    "quota_report": int(IntegrityRing.UNTRUSTED),
    "get_mode": int(IntegrityRing.UNTRUSTED),
    "search_recent": int(IntegrityRing.UNTRUSTED),
    "event_history": int(IntegrityRing.UNTRUSTED),
    "event_fetch_archived": int(IntegrityRing.UNTRUSTED),
    "agent_recv": int(IntegrityRing.UNTRUSTED),
    "poll": int(IntegrityRing.UNTRUSTED),
    # COLLAB max (ring 3) : agents externes, action legere
    "ask": int(IntegrityRing.COLLAB),
    "ask_agent": int(IntegrityRing.COLLAB),
    "ask_claude": int(IntegrityRing.COLLAB),
    "ask_gemini": int(IntegrityRing.COLLAB),
    "agent_debate": int(IntegrityRing.COLLAB),
    "event": int(IntegrityRing.COLLAB),
    "event_publish": int(IntegrityRing.COLLAB),
    "task": int(IntegrityRing.COLLAB),
    "task_assign": int(IntegrityRing.COLLAB),
    "task_claim": int(IntegrityRing.COLLAB),
    "task_result": int(IntegrityRing.COLLAB),
    "skill": int(IntegrityRing.COLLAB),
    "plan": int(IntegrityRing.COLLAB),
    "hub": int(IntegrityRing.COLLAB),
    "netcfg": int(IntegrityRing.COLLAB),
    "route_dt": int(IntegrityRing.COLLAB),
    "route_task": int(IntegrityRing.COLLAB),
    "notify": int(IntegrityRing.COLLAB),
    "agent_send": int(IntegrityRing.COLLAB),
    "memory": int(IntegrityRing.COLLAB),
    "crawl": int(IntegrityRing.COLLAB),
    "emit_telemetry": int(IntegrityRing.COLLAB),
    "index_result": int(IntegrityRing.COLLAB),
    # TRUSTED max (ring 2) : workflows TUI/audit/orchestration
    "orchestrate": int(IntegrityRing.TRUSTED),
    "react_orchestrate": int(IntegrityRing.TRUSTED),
    "loop_orchestrate": int(IntegrityRing.TRUSTED),
    "bundle": int(IntegrityRing.TRUSTED),
    "bundle_read": int(IntegrityRing.TRUSTED),
    "cross_platform_fs": int(IntegrityRing.TRUSTED),
    "graph_cve_propagate": int(IntegrityRing.TRUSTED),
    "blackboard_propose_fact": int(IntegrityRing.TRUSTED),
    "auto_test": int(IntegrityRing.TRUSTED),
    "auto_ingest": int(IntegrityRing.TRUSTED),
    "browser": int(IntegrityRing.TRUSTED),
    "github": int(IntegrityRing.TRUSTED),
    "execute": int(IntegrityRing.TRUSTED),
    "set_mode": int(IntegrityRing.TRUSTED),
    "write": int(IntegrityRing.TRUSTED),
    "trigger_autonomous_evolution": int(IntegrityRing.TRUSTED),
    "ps_run": int(IntegrityRing.TRUSTED),
    "ps_agent": int(IntegrityRing.TRUSTED),
    # DEV max (ring 1) : execution code arbitraire (Claude MCP token requis)
    # Phase 35 step 2 : relaxe `run` à TRUSTED (ring 2) car nombreux agents
    # legit (Claude/Gemini ring TRUSTED) en ont besoin. `trusted_script` reste
    # DEV (path privilégié). manage_forge_lifecycle DEV.
    "run": int(IntegrityRing.TRUSTED),
    "trusted_script": int(IntegrityRing.DEV),
    "manage_forge_lifecycle": int(IntegrityRing.DEV),
    "secret": int(IntegrityRing.DEV),
}


def check_tool_capability(
    tool_name: str, agent: Optional[str], ring: int, permissive_unknown: bool = True
) -> tuple[bool, str]:
    """Verifie si agent (ring N) peut invoquer tool_name.

    Convention Nokido : ring INFERIEUR = PLUS de droits.
    Autorise si agent_ring <= required_ring (max admis pour le tool).

    Mode (env LAFORGE_RBAC_MODE) — DEFAUT REEL : `enforce`.
      enforce (DEFAUT) : bloque vraiment, return False
      warn             : log denial mais retourne True (transition compat)
      audit            : log denial AND True (alias warn pour observabilite)

    ⚠️ Cette docstring affirmait « warn (default) ». C'est FAUX depuis que
    `_MODE = os.environ.get("LAFORGE_RBAC_MODE", "enforce")` : le code bloque
    par defaut. Corrige le 2026-09-12 apres mesure (`_ENFORCE is True` avec la
    variable d'environnement NON definie). Une docstring qui decrit un garde
    comme plus permissif qu'il ne l'est fait renoncer a s'en servir.

    Returns: (allowed: bool, reason: str)
    """
    required = _TOOL_REQUIRED_RING.get(tool_name)
    if required is None:
        if permissive_unknown:
            return True, "tool_unmapped_permissive_default"
        return False, f"tool '{tool_name}' not in RBAC mapping"
    if int(ring) <= int(required):
        return True, "ring_sufficient"
    reason = f"insufficient ring (got {ring}, max {required}) for tool '{tool_name}' agent={agent}"
    # Mode warn/audit : log mais ne bloque pas (transition non-cassante)
    if not _ENFORCE:
        logger.warning("[RBAC WARN-only mode] would deny: %s", reason)
        return True, f"warn_mode_allowed ({reason})"
    return False, reason


def tool_required_ring(tool_name: str) -> int | None:
    return _TOOL_REQUIRED_RING.get(tool_name)


def list_tools_by_ring() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for tool, ring in _TOOL_REQUIRED_RING.items():
        out.setdefault(int(ring), []).append(tool)
    return {k: sorted(v) for k, v in sorted(out.items())}


if __name__ == "__main__":
    import json

    print(json.dumps(list_tools_by_ring(), indent=2))
