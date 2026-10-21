"""
app/agents/ollama_runner.py - Execution parallele de modeles Ollama.

Classe:
  - OllamaParallelRunner : orchestration d appels Ollama en parallele (157L)
"""

from __future__ import annotations

try:
    from nokido_agent.app.forge_agents import OllamaParallelRunner
except ImportError:
    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/agents/ollama_runner.py', 12, exc_info=True)

__all__ = [
    "OllamaParallelRunner",
]
