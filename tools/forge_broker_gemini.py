"""
forge_broker_gemini.py — Nokido v18.5
Agent: agt_gemini | Google Gemini 2.5 Flash/Pro + cascade 9 tiers
Specialite: raisonnement, long contexte, multimodal
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_broker_base import BrokerBase, _load_secret


class GeminiBroker(BrokerBase):
    AGENT_ID = "agt_gemini"
    AGENT_LABEL = "Gemini"
    POLL_S = 15
    TRIGGERS = [r"\[.?->?GEMINI.?\]", r"MISSION\s*:", r"POUR GEMINI", r"\[CLAUDE.*GEMINI\]"]
    SYSTEM = """Tu es Gemini, agent IA dans Nokido v18.5. Reponds directement et techniquement.
Outils MCP: run(python|ps1), write, read, query(sql|semantic), hub(notify|poll|send|recv), web_search.
Format plan JSON si demande: [{"step":N,"action":"...","tool":"...","args":{},"risk":"safe|medium|destructive"}]
Reponds en francais. Pas de preambule. Vas droit au but."""

    MODEL_CASCADE = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-pro",
        "gemini-2.5-pro-preview-05-06",
    ]
    FALLBACKS = ["__grok__", "__mistral__", "__openrouter__", "__cohere__", "__groq__"]

    _cached_model = None
    _cached_ts = 0.0
    CACHE_TTL = 300

    def __init__(self):
        super().__init__()
        self.api_key = _load_secret("GEMINI_API_KEY")
        self.groq_key = _load_secret("GROQ_API_KEY")
        self.mistral_key = _load_secret("MISTRAL_API_KEY")
        self.xai_key = _load_secret("XAI_API_KEY")
        self.or_key = _load_secret("OPENROUTER_API_KEY")
        self.cohere_key = _load_secret("COHERE_API_KEY")
        self.log.info(f"Gemini API: {'OK' if self.api_key else 'ABSENT'}")
        self.log.info(f"Cascade: {self.MODEL_CASCADE + self.FALLBACKS}")

    def _call_gemini(self, model, prompt, timeout=60):
        if not self.api_key:
            return None
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.api_key}"
        )
        payload = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt[: self.MAX_CHARS]}]}],
                "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7},
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                ],
            }
        ).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Capturer usage tokens
            usage = data.get("usageMetadata", {})
            self._last_ptok = usage.get("promptTokenCount", 0)
            self._last_ctok = usage.get("candidatesTokenCount", 0)
            return text
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.log.info(f"  {model}: quota 429")
            else:
                self.log.debug(f"  {model}: HTTP {e.code}")
            return None
        except Exception as e:
            self.log.debug(f"  {model}: {e}")
            return None

    def _call_groq(self, prompt):
        if not self.groq_key:
            return None
        body = json.dumps(
            {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                "max_tokens": 800,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.groq_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self.log.debug(f"groq:{e}")
            return None

    def _call_mistral(self, prompt):
        if not self.mistral_key:
            return None
        body = json.dumps(
            {
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": prompt[:8000]}],
                "max_tokens": 800,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.mistral.ai/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.mistral_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self.log.debug(f"mistral:{e}")
            return None

    def _call_or(self, prompt):
        if not self.or_key:
            return None
        for model in [
            "google/gemma-4-26b-a4b-it:free",
            "nousresearch/hermes-3-llama-3.1-405b:free",
        ]:
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
        now = time.time()
        if self.__class__._cached_model and (now - self.__class__._cached_ts) < self.CACHE_TTL:
            m = self.__class__._cached_model
            out = (
                self._call_gemini(m, prompt)
                if not m.startswith("__")
                else self._call_groq(prompt)
                if m == "__groq__"
                else self._call_mistral(prompt)
                if m == "__mistral__"
                else None
            )
            if out:
                return out, m
            self.__class__._cached_model = None
        for m in self.MODEL_CASCADE:
            self.log.info(f"Essai: {m}")
            out = self._call_gemini(m, prompt)
            if out:
                self.__class__._cached_model = m
                self.__class__._cached_ts = now
                return out, m, getattr(self, "_last_ptok", 0), getattr(self, "_last_ctok", 0)
        for fb in self.FALLBACKS:
            self.log.info(f"Essai: {fb}")
            out = (
                self._call_groq(prompt)
                if fb == "__groq__"
                else self._call_mistral(prompt)
                if fb == "__mistral__"
                else self._call_or(prompt)
                if fb == "__openrouter__"
                else None
            )
            if out:
                self.__class__._cached_model = fb
                self.__class__._cached_ts = now
                return out, fb, getattr(self, "_last_ptok", 0), getattr(self, "_last_ctok", 0)
        return "ERR: tous les modeles en quota.", ""

    def call_llm_stream(self, prompt: str):
        """Streaming Gemini via streamGenerateContent SSE."""
        if not self.api_key:
            yield from ((c, "none", i == 0) for i, c in enumerate([""]))
            return
        import json
        import urllib.request

        model = self.__class__._cached_model or "gemini-2.5-flash"
        if model.startswith("__"):
            model = "gemini-2.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:streamGenerateContent?key={self.api_key}&alt=sse"
        )
        payload = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt[: self.MAX_CHARS]}]}],
                "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7},
            }
        ).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                buffer = b""
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if line.startswith(b"data: "):
                            data_str = line[6:].decode("utf-8", "replace")
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                text = data["candidates"][0]["content"]["parts"][0].get("text", "")
                                if text:
                                    yield text, model, False
                            except:
                                pass
            yield "", model, True  # signal fin
        except Exception as e:
            self.log.debug(f"stream:{e}")
            # Fallback non-streaming
            reply, mdl, ptok, ctok = self.call_llm(prompt)
            yield reply, mdl, True


if __name__ == "__main__":
    GeminiBroker().run()
