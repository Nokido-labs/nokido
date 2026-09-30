"""
app/agents/ — Facade d'acces unifiee aux modules agentiques Nokido.

OBJECTIF REFACTO (Gemini audit 2026-04):
  Consolider 7 modules `forge_agent*` en un sous-package coherent.

ETAT ACTUEL (facade non-breaking):
  Les imports historiques continuent de fonctionner depuis leurs anciens modules :
    - forge_agents.py (source canonique - 127KB)
    - forge_agent_roles.py (redondance partielle avec forge_agents)
    - forge_agent_authority.py (governance, utilise par mcp_server_tools)
    - forge_agent_benchmarker.py (orphelin)
    - forge_agent_hardware.py (redondance _score_reply)
    - forge_agentic.py (handlers handle_agentic / handle_evolve)
    - forge_autonomous_orchestrator.py (DAG, utilise par forge_desktop)

USAGE RECOMMANDE (nouveau code):
  from app.agents import AgentRole, IntentRouter, RoleOrchestrator, ...

USAGE LEGACY (toujours supporte):
  from forge_agents import AgentRole  # continue de fonctionner
"""

from __future__ import annotations

# Re-exports depuis forge_agents.py (source canonique)
try:
    from nokido_agent.app.forge_agents import (
        AgentRole,
        IntentRouter,
        ModelBenchmark,
        ModelBenchmarker,
        RoleAssignment,
        RoleOrchestrator,
        ArchitectureProfile,
        ArchitectureDetector,
        ScoredModel,
        BenchResult,
        ModelScorer,
        PromptCategory,
        OllamaParallelRunner,
        PromptClassifier,
        AgentPlanner,
        AgentSynthesizer,
        RouteResult,
        SmartRouter,
        init_router,
        get_router,
    )
except ImportError as _e:
    # Facade fonctionne meme si forge_agents echoue (mode degrade)
    import warnings

    warnings.warn(f"app.agents: forge_agents not importable: {_e}")

# Governance (autorite master/dev)
try:
    from nokido_agent.app.forge_agent_authority import (
        acquire_master_dev,
        release_master_dev,
        force_transfer_master,
        set_orchestrator,
        remove_orchestrator,
        check_write_permission,
        get_authority_level,
        authority_status,
        heartbeat,
    )
except ImportError:
    pass

# Orchestrateur autonome (DAG)
try:
    from nokido_agent.app.forge_autonomous_orchestrator import (
        DAGNode,
        DAGGraph,
        DAGBuilder,
        OneMCPMultiplexer,
        AutonomousOrchestrator,
        get_orchestrator,
        run_autonomous,
    )
except ImportError:
    pass

# Handlers agentiques (pour dispatcher)
try:
    from nokido_agent.app.forge_agentic import handle_agentic, handle_evolve
except ImportError:
    pass


__all__ = [
    # Core agents (forge_agents.py)
    "AgentRole",
    "IntentRouter",
    "ModelBenchmark",
    "ModelBenchmarker",
    "RoleAssignment",
    "RoleOrchestrator",
    "ArchitectureProfile",
    "ArchitectureDetector",
    "ScoredModel",
    "BenchResult",
    "ModelScorer",
    "PromptCategory",
    "OllamaParallelRunner",
    "PromptClassifier",
    "AgentPlanner",
    "AgentSynthesizer",
    "RouteResult",
    "SmartRouter",
    "init_router",
    "get_router",
    # Governance (forge_agent_authority.py)
    "acquire_master_dev",
    "release_master_dev",
    "force_transfer_master",
    "set_orchestrator",
    "remove_orchestrator",
    "check_write_permission",
    "get_authority_level",
    "authority_status",
    "heartbeat",
    # Orchestration (forge_autonomous_orchestrator.py)
    "DAGNode",
    "DAGGraph",
    "DAGBuilder",
    "OneMCPMultiplexer",
    "AutonomousOrchestrator",
    "get_orchestrator",
    "run_autonomous",
    # Handlers (forge_agentic.py)
    "handle_agentic",
    "handle_evolve",
]
