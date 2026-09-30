"""
app/agents/core.py - Data classes et helpers communs aux agents.

Re-exporte depuis forge_agents.py (source canonique). Ne contient
aucune logique metier, juste les structures de donnees.

Classes re-exportees :
  - AgentRole : enum des roles (ORCHESTRATOR, SENTINEL, INSPECTOR, ...)
  - RoleAssignment : assignation d un role a un modele
  - ScoredModel : modele avec score
  - ModelBenchmark : resultat benchmark
  - RouteResult : resultat d un routage
  - AgentContrib : contribution d un agent a une synthese
  - Distrib : distribution de taches
  - _SettingsProxy : proxy vers Settings (interne)
"""

from __future__ import annotations

try:
    from nokido_agent.app.forge_agents import (
        AgentRole,
        RoleAssignment,
        ScoredModel,
        ModelBenchmark,
        RouteResult,
        AgentContrib,
        Distrib,
    )
except ImportError:
    pass

__all__ = [
    "AgentRole",
    "RoleAssignment",
    "ScoredModel",
    "ModelBenchmark",
    "RouteResult",
    "AgentContrib",
    "Distrib",
]
