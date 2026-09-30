"""
app/agents/architecture.py - Detection des architectures LLM (llama2/mistral/qwen/...).

Classes:
  - ArchitectureDetector : detection automatique depuis nom/template
  - ArchitectureProfile : profil d une architecture
"""

from __future__ import annotations

try:
    from nokido_agent.app.forge_agents import (
        ArchitectureDetector,
        ArchitectureProfile,
    )
except ImportError:
    pass

__all__ = [
    "ArchitectureDetector",
    "ArchitectureProfile",
]
