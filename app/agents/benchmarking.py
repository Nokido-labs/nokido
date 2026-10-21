"""
app/agents/benchmarking.py - Benchmarks et scoring des modeles.

Classes:
  - ModelBenchmarker : benchmarks de debit/latence
  - ModelScorer : scoring qualite des reponses
  - _score_reply : fonction de scoring locale
"""

from __future__ import annotations

try:
    from nokido_agent.app.forge_agents import (
        ModelBenchmarker,
        ModelScorer,
    )
except ImportError:
    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/agents/benchmarking.py', 17, exc_info=True)

__all__ = [
    "ModelBenchmarker",
    "ModelScorer",
]
