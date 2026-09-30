"""
app/agents/routing.py - Routage intelligent des prompts vers les agents.

Classes:
  - SmartRouter : routeur principal (412L, 8 methods)
  - IntentRouter : classification d intention
  - init_router, get_router : factory + singleton
"""

from __future__ import annotations

try:
    from nokido_agent.app.forge_agents import (
        SmartRouter,
        IntentRouter,
        init_router,
        get_router,
    )
except ImportError:
    pass

__all__ = [
    "SmartRouter",
    "IntentRouter",
    "init_router",
    "get_router",
]
