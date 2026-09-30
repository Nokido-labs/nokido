"""
forge_hybrid_bridge.py — Nokido · Bridge LLM multi-provider
=============================================================
Drop-in replacement pour MultiLLMBridge (spec Engrid).
Route les appels vers le bon provider selon l'ID modèle.

Providers supportés (clés dans Nokido.env) :
    ollama/   → Ollama local (pas de clé)
    openrouter/deepseek/deepseek-r1 → OpenRouter (OPENROUTEUR_API_KEY)
    google/   → Gemini (GEMINI_API_KEY)
    groq/     → Groq (GROQ_API_KEY)
    deepseek/ → DeepSeek direct (DEEPSEEK_API_KEY)

Usage :
    bridge = MultiLLMBridge()
    response = bridge.call("openrouter/deepseek/deepseek-r1", "Analyse ce code...")
    response = bridge.call("ollama/qwen2.5-coder:7b", "Résume ceci...")
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Chargement des clés depuis Nokido.env ─────────────────────────────────


def _load_env() -> dict[str, str]:
    env_path = Path(__file__).resolve().parent.parent / "Nokido.env"
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().split("#")[0].strip()
    return result


_ENV = _load_env()


def _key(name: str) -> str:
    return _ENV.get(name, os.environ.get(name, ""))


OLLAMA_URL = _ENV.get("OLLAMA_URL", "http://localhost:11434/api/chat")
OR_API_KEY = _key("OPENROUTEUR_API_KEY") or _key("OPENROUTER_API_KEY")
GEMINI_KEY = _key("GEMINI_API_KEY")
GROQ_KEY = _key("GROQ_API_KEY")
DS_KEY = _key("DEEPSEEK_API_KEY")
TIMEOUT = 60


# ══════════════════════════════════════════════════════════════════════════════
# CALLERS PAR PROVIDER
# ══════════════════════════════════════════════════════════════════════════════


def _post_json(url: str, payload: dict, headers: dict, timeout: int = TIMEOUT) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def _call_ollama(model: str, prompt: str, max_tokens: int = 600) -> str:
    """Appel Ollama local — modèle sous forme 'qwen2.5-coder:7b'."""
    # Nettoyer le préfixe ollama/
    model = model.replace("ollama/", "")
    url = OLLAMA_URL.replace("/api/chat", "/api/generate")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": max_tokens},
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
        return resp.get("response", "").strip()
    except Exception as e:
        raise RuntimeError(f"Ollama/{model}: {e}") from e


def _call_openrouter(model: str, prompt: str, max_tokens: int = 600) -> str:
    """OpenRouter — supporte deepseek-r1, claude, gemini, etc."""
    if not OR_API_KEY:
        raise RuntimeError("OPENROUTEUR_API_KEY manquante dans Nokido.env")
    # Normaliser l'ID modèle pour OpenRouter
    # "openrouter/deepseek/deepseek-r1" → "deepseek/deepseek-r1"
    model_id = model.replace("openrouter/", "")
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {OR_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Nokido-labs/nokido",
        "X-Title": "Nokido",
    }
    data = _post_json("https://openrouter.ai/api/v1/chat/completions", payload, headers)
    return data["choices"][0]["message"]["content"].strip()


def _call_gemini(model: str, prompt: str, max_tokens: int = 600) -> str:
    """Gemini via Google AI API."""
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY manquante dans Nokido.env")
    # model: "google/gemini-2.0-flash-exp" → "gemini-2.0-flash-exp"
    model_id = model.split("/")[-1]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1},
    }
    data = _post_json(url, payload, {"Content-Type": "application/json"})
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_groq(model: str, prompt: str, max_tokens: int = 600) -> str:
    """Groq — rapide, gratuit pour llama/mixtral."""
    if not GROQ_KEY:
        raise RuntimeError("GROQ_API_KEY manquante dans Nokido.env")
    model_id = model.split("/")[-1]
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "LaForge/1.0 (github.com/Nokido-labs/nokido)",
    }
    data = _post_json("https://api.groq.com/openai/v1/chat/completions", payload, headers)
    return data["choices"][0]["message"]["content"].strip()


def _call_deepseek(model: str, prompt: str, max_tokens: int = 600) -> str:
    """DeepSeek direct (API compatible OpenAI)."""
    if not DS_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY manquante dans Nokido.env")
    model_id = model.split("/")[-1]
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {DS_KEY}",
        "Content-Type": "application/json",
    }
    data = _post_json("https://api.deepseek.com/v1/chat/completions", payload, headers)
    return data["choices"][0]["message"]["content"].strip()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


def _route(model_id: str, prompt: str, max_tokens: int = 600) -> str:
    """
    Route l'appel vers le provider correct selon le préfixe du model_id.

    Préfixes reconnus :
        ollama/               → Ollama local
        openrouter/           → OpenRouter
        google/ gemini/       → Gemini
        groq/                 → Groq
        deepseek/             → DeepSeek direct
        meta-llama/ llama     → Groq (llama disponible sur Groq)
        cloud                 → OpenRouter deepseek-r1 (défaut cloud)
    """
    m = model_id.lower()

    if m.startswith("ollama/") or m == "local":
        return _call_ollama(model_id, prompt, max_tokens)

    if m.startswith("openrouter/"):
        return _call_openrouter(model_id, prompt, max_tokens)

    if m.startswith("google/") or m.startswith("gemini/") or "gemini" in m:
        return _call_gemini(model_id, prompt, max_tokens)

    if m.startswith("groq/"):
        return _call_groq(model_id, prompt, max_tokens)

    if m.startswith("deepseek/"):
        # Essai direct, fallback OpenRouter
        try:
            return _call_deepseek(model_id, prompt, max_tokens)
        except Exception:
            return _call_openrouter(f"openrouter/{model_id}", prompt, max_tokens)

    if m.startswith("meta-llama/") or m.startswith("llama"):
        # Groq a llama-3.3-70b
        return _call_groq(f"groq/{model_id.split('/')[-1]}", prompt, max_tokens)

    if m == "cloud":
        # Défaut cloud = DeepSeek R1 via OpenRouter
        return _call_openrouter("openrouter/deepseek/deepseek-r1", prompt, max_tokens)

    # Dernier recours : Ollama local
    logger.warning(f"[Bridge] Provider inconnu pour {model_id!r} → fallback Ollama")
    return _call_ollama(model_id, prompt, max_tokens)


# ══════════════════════════════════════════════════════════════════════════════
# MULTILLIB BRIDGE — interface publique
# ══════════════════════════════════════════════════════════════════════════════


class MultiLLMBridge:
    """
    Interface unifiée multi-provider.
    Compatible avec la spec Engrid (forge_engrid_engine.py).
    """

    def __init__(self, default_model: str = "ollama/qwen2.5-coder:7b"):
        self.default_model = default_model
        self._stats: dict[str, int] = {}  # provider → nb d'appels

    def call(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 600,
        retry: int = 2,
    ) -> str:
        """
        Appel synchrone vers le provider approprié.
        Retry automatique en cas d'erreur réseau (pas sur les 4xx).
        """
        t0 = time.perf_counter()
        last_err = None

        for attempt in range(retry + 1):
            try:
                result = _route(model_id, prompt, max_tokens)
                elapsed = (time.perf_counter() - t0) * 1000
                provider = model_id.split("/")[0]
                self._stats[provider] = self._stats.get(provider, 0) + 1
                logger.info(f"[Bridge] {model_id.split('/')[-1]} {elapsed:.0f}ms attempt={attempt}")
                return result
            except RuntimeError as e:
                # 4xx → pas de retry
                if "HTTP 4" in str(e):
                    raise
                last_err = e
                if attempt < retry:
                    time.sleep(1.5**attempt)

        raise RuntimeError(f"Bridge échec après {retry + 1} tentatives: {last_err}")

    def call_with_fallback(
        self,
        model_id: str,
        prompt: str,
        fallback_model: str = "ollama/qwen2.5-coder:7b",
        max_tokens: int = 600,
    ) -> str:
        """Essaie model_id, puis fallback_model si échec."""
        try:
            return self.call(model_id, prompt, max_tokens)
        except Exception as e:
            logger.warning(f"[Bridge] {model_id} échoué ({e}), fallback → {fallback_model}")
            return self.call(fallback_model, prompt, max_tokens)

    def stats(self) -> dict:
        return dict(self._stats)

    def available_providers(self) -> list[str]:
        providers = ["ollama"]
        if OR_API_KEY:
            providers.append("openrouter")
        if GEMINI_KEY:
            providers.append("gemini")
        if GROQ_KEY:
            providers.append("groq")
        if DS_KEY:
            providers.append("deepseek")
        return providers
