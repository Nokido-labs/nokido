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
    pass

__all__ = [
    "ModelBenchmarker",
    "ModelScorer",
]
