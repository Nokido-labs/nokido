# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_ollama
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_ollama.py — Client Ollama (call + stream)
=================================================
Extrait de Nokido.py — v17 refactor.
Fonctions de module (pas de couplage avec l'UI).

Usage :
  from forge_ollama import ollama_call, ollama_stream
"""


import asyncio
import aiohttp
import json
import logging
import os
from typing import Callable, Dict, List, Optional

# Reuse KV/prompt-cache local (net-new veille DualPath 2026-07-02, actionnable
# post-P1 2026-07-07) : keep_alive explicite sur TOUS les appels Ollama = le
# modele reste charge entre appels enchaines (zero cold-reload ~10-120s APU).
_KEEP_ALIVE = os.environ.get("LAFORGE_OLLAMA_KEEP_ALIVE", "10m")

logger = logging.getLogger("Nokido.Ollama")

# Semaphore de concurrence Ollama (max 3 appels paralleles)
_ollama_semaphore = None

_ollama_semaphore = None


def _get_ollama_semaphore() -> asyncio.Semaphore:
    """Get ollama semaphore."""
    global _ollama_semaphore
    if _ollama_semaphore is None:
        _ollama_semaphore = asyncio.Semaphore(3)
    return _ollama_semaphore


async def ollama_call(
    model: str,
    messages: List[Dict],
    system: Optional[str] = None,
    max_tokens: int = 512,
    timeout: float = 120.0,
) -> str:
    """
    Appel Ollama NON-STREAMING — retourne le texte complet.
    Idéal pour le scoring parallèle et la classification LLM.
    Utilise le sémaphore global pour limiter la concurrence.
    """
    from nokido_agent.app.forge_app_context import get_settings as _gset

    settings = _gset()
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    settings = _ac.settings
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    # ── llama-cpp-python en priorité si disponible ──────────────────────────
    try:
        from nokido_agent.app import forge_context as _fc_lc

        _lc_engine = _fc_lc.get_llm_engine()
        if _lc_engine and _lc_engine.enabled and __import__("forge_llamacpp").is_available():
            _task_msg = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
            _sys_msg = next((m["content"] for m in msgs if m["role"] == "system"), None)
            _result = await __import__("forge_llamacpp").llamacpp_call(
                messages=[{"role": "user", "content": _task_msg}],
                system=_sys_msg,
                max_tokens=max_tokens,
            )
            if _result:
                return _result
    except Exception as _lce:
        logger.debug(f"[ollama_call] llamacpp skip: {_lce}")

    async with _get_ollama_semaphore():
        # Liste de modèles à essayer en ordre (principal + fallbacks)
        _models_to_try = [model]
        # Ajouter des fallbacks courants si le modèle principal échoue
        _FALLBACKS = [
            "mistral:7b",
            "mistral:latest",
            "qwen2:7b",
            "qwen3:8b",
            "qwen2.5-coder:latest",
            "starcoder2:latest",
        ]
        for _fb in _FALLBACKS:
            if _fb != model:
                _models_to_try.append(_fb)

        _last_err = None
        for _attempt_model in _models_to_try:
            try:
                async with aiohttp.ClientSession() as session:
                    _payload: dict = {
                        "model": _attempt_model,
                        "messages": msgs,
                        "stream": False,
                        "keep_alive": _KEEP_ALIVE,
                        "options": {"num_predict": max_tokens},
                    }
                    if "qwen3" in _attempt_model:
                        _payload["think"] = False  # top-level, NOT inside options
                    async with session.post(
                        settings.ollama_url,
                        json=_payload,
                        timeout=aiohttp.ClientTimeout(total=timeout, connect=8),
                    ) as resp:
                        if resp.status == 404:
                            # Modèle non disponible → essayer le suivant
                            body = await resp.text()
                            _last_err = f"Modèle '{_attempt_model}' introuvable dans Ollama"
                            logger.warning(f"Ollama 404 pour {_attempt_model}, essai suivant")
                            continue
                        if resp.status != 200:
                            body = await resp.text()
                            raise RuntimeError(f"Ollama HTTP {resp.status}: {body[:200]}")
                        data = await resp.json()
                        if _attempt_model != model:
                            logger.info(f"Fallback Ollama: {model} → {_attempt_model}")
                        return data.get("message", {}).get("content", "")
            except aiohttp.ClientConnectorError as _cce:
                _last_err = f"Ollama inaccessible ({settings.ollama_url}): {_cce}"
                break  # Ollama hors ligne — pas la peine d'essayer les fallbacks
            except RuntimeError:
                raise
            except Exception:
                continue

    # ── Fallback 0 : llama.cpp si disponible ────────────────────────────────
    try:
        from nokido_agent.app.forge_llamacpp import get_llamacpp_bridge as _get_lc

        _lc = _get_lc()
        if _lc.enabled:
            # 2026-10-01 : `run_until_complete` dans une fonction async levait toujours (et
            # l'accesseur importe n'existait pas) : ce repli n'avait jamais tourne.
            _lc_ok = _lc.is_available()
            if _lc_ok:
                _task_lc = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
                _ctx_lc = next((m["content"] for m in msgs if m["role"] == "system"), "")
                _ans_lc = await _lc.propose(_task_lc, rag_ctx=_ctx_lc, max_tokens=max_tokens)
                if _ans_lc:
                    logger.info("[ollama_call] → llama.cpp fallback OK")
                    return _ans_lc
    except Exception as _lce:
        logger.debug(f"[ollama_call] llama.cpp fallback: {_lce}")

    # ── Fallback Gemini si Ollama hors ligne ───────────────────────────────
    try:
        from nokido_agent.app.forge_gemini_bridge import get_gemini_bridge as _gg2

        _gem2 = _gg2()
        if _gem2.api_key:
            _task2 = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
            _ctx2 = next((m["content"] for m in msgs if m["role"] == "system"), "")
            _ans2 = await _gem2.propose(_task2, rag_ctx=_ctx2[:1000], max_tokens=max_tokens)
            if _ans2:
                try:
                    import builtins as _bi3

                    _bi3._nokido_last_model = f"✨ {_gem2.model}"
                except Exception:
                    pass
                return _ans2
    except Exception as _ge2:
        logger.debug(f"[ollama_call] Gemini fallback: {_ge2}")

    raise RuntimeError(
        f"{_last_err or 'Ollama indisponible'}\nLance : ollama serve  — ou configure GEMINI_API_KEY dans Nokido.env"
    )


async def ollama_stream(
    model: str, messages: List[Dict], on_token: Callable[[str], None], on_done: Callable[[], None]
) -> str:
    """Appel Ollama STREAMING — affichage token par token dans l'UI."""
    from nokido_agent.app.forge_app_context import get_settings as _gset

    settings = _gset()
    full = []
    _FALLBACKS_S = [
        "mistral:7b",
        "mistral:latest",
        "qwen2:7b",
        "qwen3:8b",
        "qwen2.5-coder:latest",
        "starcoder2:latest",
    ]
    _models_s = [model] + [f for f in _FALLBACKS_S if f != model]
    _last_err_s = None

    async with _get_ollama_semaphore():
        for _sm in _models_s:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        settings.ollama_url,
                        json={"model": _sm, "messages": messages, "stream": True,
                              "keep_alive": _KEEP_ALIVE},
                        timeout=aiohttp.ClientTimeout(total=300, connect=10),
                    ) as resp:
                        if resp.status == 404:
                            _last_err_s = f"Modèle '{_sm}' introuvable"
                            logger.warning(f"Ollama stream 404 pour {_sm}, essai suivant")
                            continue
                        if resp.status != 200:
                            body = await resp.text()
                            raise RuntimeError(f"Ollama HTTP {resp.status}: {body[:200]}")
                        if _sm != model:
                            on_token(f"[fallback→{_sm}] ")
                        async for line in resp.content:
                            if not line:
                                continue
                            line = line.decode("utf-8", errors="replace").strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            tok = data.get("message", {}).get("content", "")
                            if tok:
                                full.append(tok)
                                on_token(tok)
                            if data.get("done"):
                                break
                        on_done()
                        return "".join(full)
            except aiohttp.ClientConnectorError as e:
                _last_err_s = f"Impossible de joindre Ollama : {e}"
                break  # Ollama completement hors ligne — inutile d'essayer les fallbacks
            except RuntimeError:
                raise
            except Exception:
                continue

    # Extraire task + context des messages pour les bridges alternatifs
    _task = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    _ctx = next((m["content"] for m in messages if m["role"] == "system"), "")

    # ── Fallback 0 : llama.cpp ────────────────────────
    try:
        from nokido_agent.app.forge_llamacpp import get_llamacpp_bridge as _get_lc2, is_available as _lc_avail

        _lc2 = _get_lc2()
        # 2026-10-01 : `await` sur is_available (synchrone) et `.stream` (inexistant sur le pont)
        # levaient toujours. Meme forme que les replis LiteLLM / Gemini ci-dessous.
        if _lc2.enabled and _lc_avail():
            on_token("[llama.cpp] ")
            _ans_lc2 = await _lc2.propose(_task, rag_ctx=_ctx[:500] if _ctx else "", max_tokens=800)
            if _ans_lc2:
                on_token(_ans_lc2)
                on_done()
                return _ans_lc2
    except Exception as _lce2:
        logger.debug(f"[ollama_stream] llama.cpp fallback: {_lce2}")

    # ── Fallback 1 : LiteLLM ───────────────────────────
    try:
        from nokido_agent.app.forge_litellm_bridge import get_litellm_bridge as _get_ll

        _ll = _get_ll()
        if _ll.enabled and _ll._check_litellm():
            on_token(f"[LiteLLM:{_ll.model}] ")
            _answer = await _ll.propose(_task, rag_ctx=_ctx, max_tokens=800)
            if _answer:
                on_token(_answer)
                on_done()
                return _answer
    except Exception as _le:
        logger.debug(f"[ollama_stream] LiteLLM fallback: {_le}")

    # ── Fallback 2 : Gemini ───────────────────────────
    try:
        from nokido_agent.app.forge_gemini_bridge import get_gemini_bridge as _get_gem

        _gem = _get_gem()
        if _gem.api_key:
            on_token(f"[Gemini:{_gem.model}] ")
            _answer = await _gem.propose(_task, rag_ctx=_ctx, max_tokens=800)
            if _answer:
                on_token(_answer)
                on_done()
                return _answer
    except Exception as _ge:
        logger.debug(f"[ollama_stream] Gemini fallback: {_ge}")

    raise RuntimeError(
        f"{_last_err_s or 'Ollama indisponible'}\n"
        f"Lance : ollama pull {model}\n"
        f"Ou configure LITELLM_MODEL / GEMINI_API_KEY dans Nokido.env"
    )
