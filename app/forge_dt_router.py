"""forge_dt_router.py — DT router: SpikeRouter SNN -> cognitive pipeline hookup."""

import time
import importlib
from dataclasses import dataclass
from typing import Any

_SPIKE_KINDS = {"reasoning", "strategy", "ctf"}


@dataclass
class DTResult:
    backend: str
    strategy: str
    confidence: float
    latency_ms: int


def _ollama_fallback(task: str) -> DTResult:
    t0 = time.monotonic()
    try:
        import requests

        r = requests.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": "laforge-qwen:latest",
                "messages": [{"role": "user", "content": task}],
                "stream": False,
                "options": {"num_predict": 64},
            },
            timeout=30,
        )
        content = r.json().get("message", {}).get("content", "")
        strategy = content.strip().split("\n")[0][:80] if content else "direct"
    except Exception:
        strategy = "direct"
    return DTResult(
        backend="ollama_fallback",
        strategy=strategy,
        confidence=0.5,
        latency_ms=int((time.monotonic() - t0) * 1000),
    )


def _spike_route(task: str, context: dict) -> DTResult:
    t0 = time.monotonic()
    try:
        mod = importlib.import_module("forge_spike_router")
        router = mod.SpikeRouter()
        result = router.route(task, context=context)
        strategy = str(result.get("strategy", "spike_default"))
        confidence = float(result.get("confidence", 0.75))
        return DTResult(
            backend="spike_router",
            strategy=strategy,
            confidence=confidence,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception:
        return None


def dt_route(task: str, task_kind: str, context: dict) -> DTResult:
    """Route a task through SpikeRouter SNN if applicable, else Ollama fallback."""
    if task_kind in _SPIKE_KINDS:
        result = _spike_route(task, context)
        if result is not None:
            return result
    return _ollama_fallback(task)


if __name__ == "__main__":
    print(dt_route("test reasoning task", "reasoning", {}))
