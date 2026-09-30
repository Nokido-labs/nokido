"""
forge_broker_mistral.py — Nokido v18.5
Agent: agt_mistral | Mistral Large + Codestral (EU/RGPD, function calling)
Specialite: souverainete EU, function calling, structured output, code FIM
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_broker_base import BrokerBase, _load_secret


class MistralBroker(BrokerBase):
    AGENT_ID = "agt_mistral"
    AGENT_LABEL = "Mistral-EU"
    POLL_S = 20
    TRIGGERS = [r"\[.?->?MISTRAL.?\]", r"FUNCTION CALL:", r"EU:", r"RGPD"]
    SYSTEM = """Tu es Mistral, agent IA souverain europeen dans Nokido v18.5.
Tu privilegies la precision, la conformite RGPD et les reponses structurees.
Function calling et JSON mode sont tes points forts. Reponds en francais."""

    MODELS = [
        "mistral-large-latest",
        "mistral-small-latest",
        "codestral-latest",
        "open-mistral-nemo",
    ]

    def __init__(self):
        super().__init__()
        self.api_key = _load_secret("MISTRAL_API_KEY")
        self.log.info(f"Mistral API: {'OK' if self.api_key else 'ABSENT'}")
        self.log.info(f"Models: {self.MODELS}")

    def _call(self, model, prompt, timeout=45):
        if not self.api_key:
            return None
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[: self.MAX_CHARS]}],
                "max_tokens": 800,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.mistral.ai/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self.log.debug(f"{model}:{e}")
            return None

    def call_llm(self, prompt):
        for model in self.MODELS:
            self.log.info(f"Essai: {model}")
            out = self._call(model, prompt)
            if out:
                return out, model
        return "ERR: Mistral indisponible.", "none"


if __name__ == "__main__":
    MistralBroker().run()
