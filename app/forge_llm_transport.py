# -*- coding: utf-8 -*-
"""
forge_llm_transport.py — Socle commun de transport LLM Nokido v18.5
====================================================================
Centralise les appels HTTP (urllib) vers tous les providers.
Gère les retries, les timeouts adaptatifs et le tracking d'usage.
"""

from __future__ import annotations
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Nokido.Transport")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# ── Pricing table (April 2026) ──────────────────────────────────────────────
PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 5.00),
    "llama-3.3-70b": (0.59, 0.79),
    "llama-3.1-8b": (0.05, 0.08),
    "mistral-large": (2.00, 6.00),
    "mistral-small": (0.20, 0.60),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}


def _calc_cost(model: str, prompt_tok: int, completion_tok: int) -> float:
    key = next((k for k in PRICING if k in model), None)
    if not key:
        return 0.0
    pin, pout = PRICING[key]
    return round((prompt_tok * pin + completion_tok * pout) / 1_000_000, 8)


class LLMTransport:
    """
    V2 "Resilient Membrane" — Gestionnaire de transport unifié.
    Supporte le mode Air-Gap et la cascade adaptative Cloud -> Local.
    """

    def __init__(self, timeout: float = 30.0):
        self.default_timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        self.airgap_mode = os.environ.get("LAFORGE_AIRGAP", "0") == "1"

    def _check_airgap(self, url: str) -> bool:
        """Bloque l'accès si le mode Air-Gap est actif et l'URL n'est pas locale."""
        if self.airgap_mode:
            is_local = "127.0.0.1" in url or "localhost" in url
            if not is_local:
                logger.warning(f"AIR-GAP BLOCK: Tentative d'accès à {url} refusée.")
                return False
        return True

    def _get_mood_factor(self) -> float:
        """Récupère l'énergie système pour adapter la stratégie."""
        try:
            from nokido_agent.app.forge_system_mood import get_current_mood

            return get_current_mood().energy
        except:
            return 0.5  # Default neutral

    def _track_usage(
        self,
        agent_id: str,
        model: str,
        provider: str,
        prompt_tok: int,
        completion_tok: int,
        latency_ms: float,
        source: str = "transport",
    ) -> None:
        """Persister l'usage tokens et le coût dans la base de données."""
        try:
            # RACCORDE au recorder canonique (A3, 2026-09-12) :
            # UNIQUE_WRITER(token_usage) = app/forge_token_monitor.log_call.
            # Le cout reste calcule ICI, par la table de prix de CE module, et
            # transmis tel quel : le recalculer chez le recorder aurait modifie
            # des valeurs comptables sous couvert de plomberie. Le raccordement
            # est donc strictement NEUTRE -- aucune valeur ecrite ne change,
            # seul le chemin d'ecriture est unifie.
            from nokido_agent.app.forge_token_monitor import log_call

            log_call(
                agent_id=agent_id,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tok,
                completion_tokens=completion_tok,
                latency_ms=round(latency_ms, 1),
                source=source,
                cost_usd=_calc_cost(model, prompt_tok, completion_tok),
            )
        except Exception as e:
            logger.debug(f"Usage tracking fail: {e}")

    def call_mistral(self, api_key: str, model: str, messages: List[Dict], **kwargs) -> Optional[str]:
        t0 = time.time()
        url = "https://api.mistral.ai/v1/chat/completions"

        # V2 : Air-Gap & Cascade Mood
        if not self._check_airgap(url) or self._get_mood_factor() < 0.2:
            return self.call_ollama(model="mistral", prompt=str(messages), **kwargs)

        payload = {"model": model, "messages": messages, "max_tokens": kwargs.get("max_tokens", 800)}
        headers = {**self.headers, "Authorization": f"Bearer {api_key}"}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=self.default_timeout) as r:
                data = json.loads(r.read())
            text = data["choices"][0]["message"]["content"].strip()
            u = data.get("usage", {})
            self._track_usage(
                "SYSTEM",
                model,
                "mistral",
                u.get("prompt_tokens", 0),
                u.get("completion_tokens", 0),
                (time.time() - t0) * 1000,
            )
            return text
        except Exception as e:
            logger.warning(f"Mistral fail -> local: {e}")
            return self.call_ollama(model="mistral", prompt=str(messages), **kwargs)

    def call_gemini(self, api_key: str, model: str, prompt: str, **kwargs) -> Optional[str]:
        t0 = time.time()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        # V2 : Air-Gap & Cascade Mood
        if not self._check_airgap(url) or self._get_mood_factor() < 0.2:
            return self.call_ollama(model="llama3", prompt=prompt, **kwargs)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": kwargs.get("max_tokens", 1000),
                "temperature": kwargs.get("temperature", 0.7),
            },
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=self.headers)
            with urllib.request.urlopen(req, timeout=self.default_timeout) as r:
                data = json.loads(r.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            u = data.get("usageMetadata", {})
            self._track_usage(
                "SYSTEM",
                model,
                "google",
                u.get("promptTokenCount", 0),
                u.get("candidatesTokenCount", 0),
                (time.time() - t0) * 1000,
            )
            return text
        except Exception as e:
            logger.warning(f"Gemini fail -> local: {e}")
            return self.call_ollama(model="llama3", prompt=prompt, **kwargs)

    def call_ollama(self, model: str, prompt: str, host: str = "http://127.0.0.1:11434", **kwargs) -> Optional[str]:
        """Appel API Ollama locale."""
        t0 = time.time()
        url = f"{host}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": kwargs.get("max_tokens", 1000)},
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=self.headers)
            with urllib.request.urlopen(req, timeout=self.default_timeout) as r:
                data = json.loads(r.read())
            text = data.get("response", "").strip()
            # Usage gratuit (local), on log 0 cost
            self._track_usage("SYSTEM", model, "ollama", 0, 0, (time.time() - t0) * 1000)
            return text
        except Exception as e:
            logger.error(f"Ollama call fail: {e}")
            return None

    def call_llamacpp(self, prompt: str, host: str = "http://127.0.0.1:8080", **kwargs) -> Optional[str]:
        """Appel Llama.cpp (Server mode)."""
        t0 = time.time()
        url = f"{host}/completion"
        payload = {
            "prompt": prompt,
            "n_predict": kwargs.get("max_tokens", 1000),
            "temperature": kwargs.get("temperature", 0.7),
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=self.headers)
            with urllib.request.urlopen(req, timeout=self.default_timeout * 2) as r:
                data = json.loads(r.read())
            text = data.get("content", "").strip()
            self._track_usage("SYSTEM", "llama.cpp", "local", 0, 0, (time.time() - t0) * 1000)
            return text
        except Exception as e:
            logger.error(f"Llama.cpp call fail: {e}")
            return None

    def call_qwen_local(self, prompt: str, **kwargs) -> Optional[str]:
        """Appel instance Qwen intégrée à Nokido."""
        # On assume ici que Qwen est exposé via Ollama ou un endpoint local spécifique
        # Ajustable selon ton implémentation exacte
        return self.call_ollama(model="qwen2.5", prompt=prompt, **kwargs)

    def call_groq(self, api_key: str, model: str, messages: List[Dict], **kwargs) -> Optional[str]:
        t0 = time.time()
        url = "https://api.groq.com/openai/v1/chat/completions"

        # V2 : Air-Gap & Cascade Mood
        if not self._check_airgap(url) or self._get_mood_factor() < 0.2:
            return self.call_llamacpp(prompt=str(messages), **kwargs)

        payload = {"model": model, "messages": messages, "max_tokens": kwargs.get("max_tokens", 800)}
        headers = {**self.headers, "Authorization": f"Bearer {api_key}"}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=self.default_timeout) as r:
                data = json.loads(r.read())
            text = data["choices"][0]["message"]["content"].strip()
            u = data.get("usage", {})
            self._track_usage(
                "SYSTEM",
                model,
                "groq",
                u.get("prompt_tokens", 0),
                u.get("completion_tokens", 0),
                (time.time() - t0) * 1000,
            )
            return text
        except Exception as e:
            logger.warning(f"Groq fail -> Llama.cpp: {e}")
            return self.call_llamacpp(prompt=str(messages), **kwargs)
