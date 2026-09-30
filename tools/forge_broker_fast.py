"""
forge_broker_fast.py — Nokido v18.5
Agent: agt_groq | Groq LPU 315-700TPS
Specialite: classification rapide, routing, scoring CerberusGuard, < 500ms
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_broker_base import BrokerBase, _load_secret


class FastBroker(BrokerBase):
    AGENT_ID = "agt_groq"
    AGENT_LABEL = "Groq-Fast"
    POLL_S = 8
    TRIGGERS = []
    SYSTEM = "Tu es un agent ultra-rapide Nokido. Reponds en 1-3 phrases max. Pas de preambule."

    # Endpoints multi-providers — SambaNova en premier si disponible
    ENDPOINTS = [
        (
            "sambanova",
            "Meta-Llama-3.3-70B-Instruct",
            "https://api.sambanova.ai/v1/chat/completions",
            "SAMBANOVA_API_KEY",
        ),
        (
            "groq",
            "llama-3.3-70b-versatile",
            "https://api.groq.com/openai/v1/chat/completions",
            "GROQ_API_KEY",
        ),
        (
            "groq",
            "llama-3.1-8b-instant",
            "https://api.groq.com/openai/v1/chat/completions",
            "GROQ_API_KEY",
        ),
        (
            "groq",
            "qwen/qwen3-32b",
            "https://api.groq.com/openai/v1/chat/completions",
            "GROQ_API_KEY",
        ),
    ]
    # Compat legacy
    MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"]
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        super().__init__()
        self.groq_key = _load_secret("GROQ_API_KEY")
        self.samba_key = _load_secret("SAMBANOVA_API_KEY")
        gstatus = "OK" if self.groq_key else "ABSENT"
        sstatus = "OK" if self.samba_key else "ABSENT"
        self.log.info(f"Groq API: {gstatus} | SambaNova: {sstatus}")
        self.log.info(f"Endpoints: {[e[0] + '/' + e[1][:15] for e in self.ENDPOINTS]}")

    def _call(self, model, prompt, max_tokens=500, timeout=15):
        return self._call_endpoint(self.URL, self.groq_key, model, prompt, max_tokens, timeout)

    def _call_endpoint(self, url, key, model, prompt, max_tokens=500, timeout=15):
        if not key:
            return None
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:6000]}],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            }
        ).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": "curl/7.88.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            self._last_ptok = data.get("usage", {}).get("prompt_tokens", 0)
            self._last_ctok = data.get("usage", {}).get("completion_tokens", 0)
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body_err = e.read().decode()[:80]
            self.log.debug(f"{model}: HTTP {e.code} {body_err}")
            return None
        except Exception as e:
            self.log.debug(f"{model}: {e}")
            return None

    def call_llm(self, prompt):
        for provider, model, url, key_name in self.ENDPOINTS:
            key = self.samba_key if provider == "sambanova" else self.groq_key
            if not key:
                continue
            self.log.info(f"Essai: {provider}/{model}")
            out = self._call_endpoint(url, key, model, prompt)
            if out:
                return (
                    out,
                    f"{provider}/{model}",
                    getattr(self, "_last_ptok", 0),
                    getattr(self, "_last_ctok", 0),
                )
        return "ERR: tous les providers Fast indisponibles.", "none", 0, 0


if __name__ == "__main__":
    FastBroker().run()
