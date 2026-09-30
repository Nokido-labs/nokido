"""
forge_thought_interceptor.py — Nokido
Capture et indexe la chaîne de raisonnement (CoT) des modèles cloud.
Optimisé pour DeepSeek-R1 qui expose les balises <think>...</think>.
"""

from __future__ import annotations

import re
import time
import logging
from typing import Optional

# Deferred dep — direct LLM call patched in usage:
# from forge_llm_router import LLMRouter as MultiLLMBridge
MultiLLMBridge = None

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


class ForgeThoughtInterceptor:
    """
    Appelle un modèle et sépare la chaîne de raisonnement du contenu final.
    Retourne: {"thought": str | None, "content": str, "model": str, "ms": int}
    """

    def __init__(self, bridge: Optional[MultiLLMBridge] = None):
        self.bridge = bridge or MultiLLMBridge()

    def call_with_thought(
        self,
        model: str,
        prompt: str,
        task_id: str = "unknown",
        max_tokens: int = 2000,
    ) -> dict:
        t0 = time.perf_counter()
        raw = self.bridge.call(model, prompt, max_tokens=max_tokens)
        ms = int((time.perf_counter() - t0) * 1000)

        # Extraire la chaîne de pensée (DeepSeek-R1 / QwQ)
        think_matches = _THINK_RE.findall(raw)
        thought = "\n".join(think_matches).strip() if think_matches else None
        content = _THINK_RE.sub("", raw).strip()

        result = {
            "thought": thought,
            "content": content,
            "model": model,
            "task_id": task_id,
            "ms": ms,
        }
        logger.info(f"[Interceptor] task={task_id} model={model} ms={ms} thought={'yes' if thought else 'no'}")
        return result

    # Alias utilisé dans forge_sanitizer_analyst.py
    def stream_with_thought_capture(
        self,
        model: str,
        prompt: str,
        task_id: str = "unknown",
        max_tokens: int = 2000,
    ) -> dict:
        return self.call_with_thought(model, prompt, task_id, max_tokens)
