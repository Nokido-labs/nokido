"""
app/agents/roles.py - Orchestration des roles et classification.

Classes:
  - RoleOrchestrator : assignation des roles aux modeles (281L, 13 methods)
  - PromptClassifier : classification des prompts par categorie
  - PromptCategory : enum des categories
"""

from __future__ import annotations

try:
    from nokido_agent.app.forge_agents import (
        RoleOrchestrator,
        PromptClassifier,
        PromptCategory,
    )
except ImportError:
    pass

__all__ = [
    "RoleOrchestrator",
    "PromptClassifier",
    "PromptCategory",
]
