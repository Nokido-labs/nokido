# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_metrics
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_metrics.py — Mesure des capacités LLM (latence, tokens, qualité)
======================================================================
Branché sur tous les bridges : Ollama, Gemini, LiteLLM.

Format de chaque mesure :
  {
    "ts":           ISO8601,
    "provider":     "ollama|gemini|litellm",
    "model":        "qwen2.5-coder:latest",
    "prompt_tokens": int,
    "output_tokens": int,
    "latency_ms":    float,
    "mode":          "chat|rag|action",
    "session_id":    str,
    "ok":            bool,
    "loopback_ok":   bool,
    "error":         str | None,
  }

Usage :
  from forge_metrics import MetricsCollector, get_collector
  col = get_collector()
  with col.measure("ollama", "qwen2.5", mode="chat") as m:
      response = await ollama_call(...)
      m.set_tokens(prompt=100, output=200)
  # → enregistré automatiquement
"""

import time
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMMetric:
    """Une mesure d'appel LLM."""

    __slots__ = [
        "ts",
        "provider",
        "model",
        "prompt_tokens",
        "output_tokens",
        "latency_ms",
        "mode",
        "session_id",
        "ok",
        "loopback_ok",
        "error",
        "_start",
    ]

    def __init__(self, provider: str, model: str, mode: str, session_id: str) -> None:
        """Init.

        Args:
            provider: Description.
            model: Description.
            mode: Description.
            session_id: Description.
        """
        self.ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self.provider = provider
        self.model = model
        self.mode = mode
        self.session_id = session_id
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.latency_ms = 0.0
        self.ok = True
        self.loopback_ok = True
        self.error: Optional[str] = None
        self._start = time.perf_counter()

    def finish(self, ok: bool = True, error: str = None) -> None:
        """Finish.

        Args:
            ok: Description.
            error: Description.
        """
        self.latency_ms = (time.perf_counter() - self._start) * 1000
        self.ok = ok
        self.error = error

    def set_tokens(self, prompt: int = 0, output: int = 0) -> None:
        """Set tokens.

        Args:
            prompt: Description.
            output: Description.
        """
        self.prompt_tokens = prompt
        self.output_tokens = output

    def estimate_tokens(self, prompt_text: str, output_text: str) -> None:
        """Estimation rapide : ~4 chars / token."""
        self.prompt_tokens = max(1, len(prompt_text) // 4)
        self.output_tokens = max(1, len(output_text) // 4)

    def to_dict(self) -> Dict:
        """To dict."""
        return {
            "ts": self.ts,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.prompt_tokens + self.output_tokens,
            "latency_ms": round(self.latency_ms, 1),
            "tokens_per_sec": round(self.output_tokens / max(self.latency_ms / 1000, 0.001), 1),
            "mode": self.mode,
            "session_id": self.session_id,
            "ok": self.ok,
            "loopback_ok": self.loopback_ok,
            "error": self.error,
        }


class MetricsCollector:
    """
    Collecte et agrège les métriques de tous les providers LLM.
    Thread-safe, async-compatible.
    """

    def __init__(self, max_history: int = 500) -> None:
        """Init.

        Args:
            max_history: Description.
        """
        self._history: List[LLMMetric] = []
        self._max = max_history
        self._log_path = Path(__file__).parent.parent / "logs" / "llm_metrics.jsonl"
        self._log_path.parent.mkdir(exist_ok=True)

    @contextmanager
    def measure(self, provider: str, model: str, mode: str = "chat", session_id: str = "") -> None:
        """
        Context manager pour mesurer un appel LLM.

        with col.measure("ollama", "qwen2.5", mode="rag") as m:
            response = await ollama_call(...)
            m.estimate_tokens(prompt, response)
        """
        m = LLMMetric(provider, model, mode, session_id)
        try:
            yield m
            m.finish(ok=True)
        except Exception as e:
            m.finish(ok=False, error=str(e)[:100])
            raise
        finally:
            self._record(m)

    def record(self, metric: LLMMetric) -> None:
        """Record.

        Args:
            metric: Description.
        """
        self._record(metric)

    def _record(self, m: LLMMetric) -> None:
        """Record.

        Args:
            m: Description.
        """
        if len(self._history) >= self._max:
            self._history.pop(0)
        self._history.append(m)
        # Log JSONL
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── Agrégats ────────────────────────────────────────────────────────────

    def stats(self, provider: str = "", last_n: int = 100) -> Dict:
        """Stats agrégées par provider."""
        items = [m for m in self._history[-last_n:] if (not provider or m.provider == provider) and m.ok]
        if not items:
            return {"provider": provider, "n": 0}

        lats = [m.latency_ms for m in items]
        tokens = [m.output_tokens for m in items]
        tps = [m.output_tokens / max(m.latency_ms / 1000, 0.001) for m in items]
        errors = sum(1 for m in self._history[-last_n:] if (not provider or m.provider == provider) and not m.ok)

        return {
            "provider": provider or "all",
            "n": len(items),
            "errors": errors,
            "latency_ms": {
                "avg": round(sum(lats) / len(lats), 1),
                "min": round(min(lats), 1),
                "max": round(max(lats), 1),
                "p90": round(sorted(lats)[int(len(lats) * 0.9)], 1),
            },
            "tokens_out": {
                "avg": round(sum(tokens) / len(tokens), 1),
                "total": sum(tokens),
            },
            "tokens_per_sec": {
                "avg": round(sum(tps) / len(tps), 1),
                "max": round(max(tps), 1),
            },
        }

    def compare_providers(self) -> Dict:
        """Comparatif tous providers."""
        providers = list({m.provider for m in self._history})
        return {p: self.stats(p) for p in sorted(providers)}

    def best_provider(self, metric: str = "latency") -> str:
        """Retourne le provider le plus rapide ou le plus efficace."""
        comp = self.compare_providers()
        if not comp:
            return "ollama"
        if metric == "latency":
            return min(comp, key=lambda p: comp[p].get("latency_ms", {}).get("avg", 9999))
        if metric == "throughput":
            return max(comp, key=lambda p: comp[p].get("tokens_per_sec", {}).get("avg", 0))
        return "ollama"

    def report(self, last_n: int = 50) -> str:
        """Rapport texte formaté pour la TUI."""
        lines = [f"📊 Métriques LLM (derniers {last_n} appels)\n"]
        comp = self.compare_providers()
        if not comp:
            return "Aucune métrique collectée."
        for prov, stats in comp.items():
            if stats["n"] == 0:
                continue
            lat = stats.get("latency_ms", {})
            tps = stats.get("tokens_per_sec", {})
            lines.append(
                f"  {prov:<15} "
                f"n={stats['n']:>4}  "
                f"lat={lat.get('avg', 0):>7.0f}ms (p90={lat.get('p90', 0):.0f})  "
                f"tok/s={tps.get('avg', 0):>6.1f}  "
                f"err={stats['errors']:>2}"
            )
        best = self.best_provider()
        lines.append(f"\n  ⚡ Meilleur provider (latence) : {best}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_collector: Optional[MetricsCollector] = None


def get_collector() -> MetricsCollector:
    """Get collector."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
