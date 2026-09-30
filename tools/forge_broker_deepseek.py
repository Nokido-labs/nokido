"""
forge_broker_deepseek.py — Nokido v18.5
Agent: agt_deepseek | DeepSeek V4 Flash + R1 (OSS, code, reasoning)
Specialite: code review, debugging, raisonnement chain-of-thought, 1M tokens
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_broker_base import BrokerBase, _load_secret


class DeepSeekBroker(BrokerBase):
    AGENT_ID = "agt_deepseek"
    AGENT_LABEL = "DeepSeek"
    POLL_S = 20
    TRIGGERS = [r"\[.?->?DEEPSEEK.?\]", r"CODE REVIEW:", r"DEBUG:", r"ANALYSE CODE"]
    SYSTEM = """Tu es DeepSeek, agent IA specialise en code et raisonnement dans Nokido v18.5.
Tu analyses le code avec precision, identifies les bugs, proposes des corrections.
Format: diagnostic + code corrige + explication. Reponds en francais."""

    MODELS = [
        ("deepseek-chat", "https://api.deepseek.com/v1/chat/completions"),
        ("deepseek-coder", "https://api.deepseek.com/v1/chat/completions"),
        ("deepseek-reasoner", "https://api.deepseek.com/v1/chat/completions"),
    ]

    def __init__(self):
        super().__init__()
        self.api_key = _load_secret("DEEPSEEK_API_KEY")
        self.or_key = _load_secret("OPENROUTER_API_KEY")
        self.log.info(f"DeepSeek API: {'OK' if self.api_key else 'ABSENT'}")

    def _call_ds(self, model, prompt, timeout=60):
        if not self.api_key:
            return None
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[: self.MAX_CHARS]}],
                "max_tokens": 1000,
                "temperature": 0.1,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self.log.debug(f"{model}:{e}")
            return None

    def _call_or_deepseek(self, prompt):
        if not self.or_key:
            return None
        for model in ["deepseek/deepseek-r1:free", "deepseek/deepseek-chat:free"]:
            body = json.dumps(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt[:8000]}],
                    "max_tokens": 800,
                }
            ).encode()
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.or_key}",
                    "HTTP-Referer": "https://nokido.local",
                    "X-Title": "Nokido",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())["choices"][0]["message"]["content"].strip()
            except:
                continue
        return None

    def call_llm(self, prompt):
        for model, _ in self.MODELS:
            self.log.info(f"Essai: {model}")
            out = self._call_ds(model, prompt)
            if out:
                return out, model
        self.log.info("Fallback: OpenRouter DeepSeek :free")
        out = self._call_or_deepseek(prompt)
        if out:
            return out, "deepseek-r1:free"
        return "ERR: DeepSeek indisponible.", "none"


if __name__ == "__main__":
    DeepSeekBroker().run()
