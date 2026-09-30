"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_agent_benchmarker
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
forge_agents.py — Intelligence et routage des agents pour La Forge
===================================================================
Fusion de : roles.py · scoring.py · routage.py

Organisation :
  § 1 RÔLES        : AgentRole, system prompts, IntentRouter, RoleOrchestrator
  § 2 SCORING      : ArchitectureProfile, ModelScorer, benchmark dynamique
  § 3 ROUTAGE      : SmartRouter, PromptClassifier, AgentPlanner, OllamaParallelRunner

Les trois modules sont regroupés car ils forment un pipeline cohérent :
  AgentRole → ModelScorer (qui modèle pour ce rôle ?) → SmartRouter (exécution)

Usage dans Nokido.py :
    from forge_agents import (
        AgentRole, RoleOrchestrator, IntentRouter,
        ROLE_META, ROLE_SYSTEM_PROMPTS,
        ModelScorer, ArchitectureProfile,
        SmartRouter, OllamaParallelRunner, PromptClassifier,
        AgentPlanner, PromptCategory, RouteResult,
        init_router, get_router,
    )
"""


from app.core.settings import get_settings as _forge_settings  # noqa: F401


# IntentRouter importé depuis forge_agents


# =============================================================================
# BENCHMARK DYNAMIQUE
# =============================================================================

# ModelBenchmark importé depuis forge_agents


# ModelBenchmarker importé depuis forge_agents


# =============================================================================
# ASSIGNATION DES RÔLES
# =============================================================================

# RoleAssignment importé depuis forge_agents


# RoleOrchestrator importé depuis forge_agents


# =============================================================================
# § 2 — SCORING ET ARCHITECTURE  (ex-scoring.py)
# =============================================================================

# Import des rôles depuis roles.py (déjà dans le projet)
