"""
forge_broker_local.py — Nokido v18.5
Agent: agt_local | Ollama + llama.cpp (100% local, zero cloud, RGPD absolu)
Specialite: vie privee totale, offline, code rapide (qwen2.5-coder), vision (llava)
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_broker_base import BrokerBase


class LocalBroker(BrokerBase):
    AGENT_ID = "agt_local"
    AGENT_LABEL = "Ollama-Local"
    POLL_S = 10
    TRIGGERS = [r"\[.?->?LOCAL.?\]", r"OFFLINE:", r"PRIVE:", r"\[LOCAL\]"]
    SYSTEM = "Tu es un agent IA local dans Nokido v18.5. Reponds techniquement et concisement en francais."

    OLLAMA_URL = "http://localhost:11434"
    LLAMACPP_URL = "http://127.0.0.1:8090"

    # Priorite modeles par use case
    MODELS_PRIORITY = [
        ("ollama", "qwen2.5-coder:32b-instruct-q4_K_M"),  # Code: meilleur
        ("ollama", "deepseek-r1:14b"),  # Reasoning
        ("ollama", "qwen3:8b"),  # General
        ("llamacpp", "gemma4"),  # Rapide local
        ("ollama", "qwen2.5-coder:7b-instruct-q4_K_M"),  # Code leger
    ]

    def __init__(self):
        super().__init__()
        self._check_backends()

    def _check_backends(self):
        for url, name in [
            (self.OLLAMA_URL + "/api/tags", "Ollama"),
            (self.LLAMACPP_URL + "/health", "llama.cpp"),
        ]:
            try:
                with urllib.request.urlopen(url, timeout=2):
                    self.log.info(f"{name}: UP")
            except:
                self.log.warning(f"{name}: DOWN")

    def _call_ollama(self, model, prompt, timeout=120):
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt[: self.MAX_CHARS],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 800},
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.OLLAMA_URL}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read()).get("response", "").strip()
        except Exception as e:
            self.log.debug(f"ollama {model}:{e}")
            return None

    def _call_llamacpp(self, prompt, timeout=60):
        body = json.dumps(
            {
                "model": "gemma4",
                "messages": [{"role": "user", "content": prompt[: self.MAX_CHARS]}],
                "stream": False,
                "max_tokens": 800,
                "temperature": 0.1,
                "thinking": False,
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.LLAMACPP_URL}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self.log.debug(f"llamacpp:{e}")
            return None

    def call_llm(self, prompt):
        for backend, model in self.MODELS_PRIORITY:
            self.log.info(f"Essai: {backend}/{model}")
            if backend == "ollama":
                out = self._call_ollama(model, prompt)
            else:
                out = self._call_llamacpp(prompt)
            if out:
                return out, f"{backend}/{model}"
        return "ERR: tous les modeles locaux indisponibles.", "none"


if __name__ == "__main__":
    LocalBroker().run()
