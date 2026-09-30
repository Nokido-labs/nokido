# -*- coding: utf-8 -*-
"""
forge_trust_score.py — Score de confiance 0-100 par provider LLM
=================================================================
Session 5 — 2026-04-27

Formula : score = 0.5*ttft_norm + 0.3*uptime + 0.2*cost_norm
- ttft_norm : 0ms=100, 10000ms=0 (EMA lissé)
- uptime    : 100 - 100*(failures/calls)
- cost_norm : 0 USD/1k=100, 10 USD/1k=0

Utilisé par §ROUTE:BEST dans LLMRouter._select_slot().
Singleton thread-safe. Persisté en mémoire, reset au restart.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ProviderStats:
    name: str
    ttft_ms: float = 5000.0  # Time To First Token mesuré (EMA)
    uptime_pct: float = 100.0  # 0-100
    cost_per_1k: float = 0.0  # USD, 0 = gratuit
    failures: int = 0
    calls: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def score(self) -> float:
        """Score 0-100, plus haut = meilleur provider."""
        ttft_score = max(0.0, 100.0 - (self.ttft_ms / 100.0))
        uptime_score = self.uptime_pct
        cost_score = max(0.0, 100.0 - (self.cost_per_1k * 10.0))
        return round(0.5 * ttft_score + 0.3 * uptime_score + 0.2 * cost_score, 1)


class TrustScoreRegistry:
    """Registre singleton thread-safe des scores providers."""

    _instance: Optional["TrustScoreRegistry"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._stats: Dict[str, ProviderStats] = {}
        self._mu = threading.Lock()

    @classmethod
    def get(cls) -> "TrustScoreRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def record_success(self, provider: str, ttft_ms: float):
        """Appeler après chaque réponse réussie avec le TTFT mesuré."""
        with self._mu:
            s = self._get_or_create(provider)
            s.ttft_ms = 0.7 * s.ttft_ms + 0.3 * ttft_ms  # EMA(0.3)
            s.calls += 1
            s.last_updated = time.time()
            if s.calls > 0:
                s.uptime_pct = 100.0 * (1 - s.failures / s.calls)

    def record_failure(self, provider: str):
        """Appeler après chaque échec (timeout, 429, erreur)."""
        with self._mu:
            s = self._get_or_create(provider)
            s.failures += 1
            s.calls += 1
            s.last_updated = time.time()
            if s.calls > 0:
                s.uptime_pct = 100.0 * (1 - s.failures / s.calls)

    def set_cost(self, provider: str, cost_per_1k: float):
        with self._mu:
            self._get_or_create(provider).cost_per_1k = cost_per_1k

    def best_provider(self, candidates: list) -> str:
        """Retourne le provider avec le meilleur score parmi les candidats."""
        with self._mu:
            scored = [(p, self._get_or_create(p).score) for p in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else (candidates[0] if candidates else "ollama_local")

    def score(self, provider: str) -> float:
        with self._mu:
            return self._get_or_create(provider).score

    def summary(self) -> list:
        with self._mu:
            return sorted(
                [
                    {
                        "provider": s.name,
                        "score": s.score,
                        "ttft_ms": round(s.ttft_ms, 1),
                        "uptime_pct": round(s.uptime_pct, 1),
                        "cost_per_1k": s.cost_per_1k,
                        "calls": s.calls,
                        "failures": s.failures,
                    }
                    for s in self._stats.values()
                ],
                key=lambda x: x["score"],
                reverse=True,
            )

    def _get_or_create(self, provider: str) -> ProviderStats:
        if provider not in self._stats:
            self._stats[provider] = ProviderStats(name=provider)
        return self._stats[provider]


# Coûts connus (USD/1k tokens, 0 = gratuit)
_KNOWN_COSTS = {
    "github_gpt41_mini": 0.0,
    "github_gpt4o_mini": 0.0,
    "github_llama_70b": 0.0,
    "github_deepseek_v3": 0.0,
    "github_codestral": 0.0,
    "openrouter_gpt_oss": 0.0,
    "openrouter_glm_air": 0.0,
    "openrouter_qwen_coder": 0.0,
    "hf_llama": 0.0,
    "hf_qwen_coder": 0.0,
    "ollama_local": 0.0,
    "llamacpp_local": 0.0,
    "lmstudio_native": 0.0,
    "groq_fast": 0.0,
    "gemini_flash": 0.0,
    "gemini_pro": 0.035,
    "mistral_small": 0.002,
    "mistral_large": 0.008,
    "deepseek_chat": 0.001,
    "deepseek_coder": 0.001,
    "xai_grok3": 0.003,
    "xai_grok3_mini": 0.001,
}


def init_costs():
    """Initialise les coûts connus au démarrage."""
    reg = TrustScoreRegistry.get()
    for provider, cost in _KNOWN_COSTS.items():
        reg.set_cost(provider, cost)
