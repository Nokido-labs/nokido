#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_langfuse_hook.py — émission fail-open des appels LLM vers Langfuse.

Branche le tracking LLM EXISTANT (forge_agent_proxy._record_provider_call) sur
Langfuse → DAG tool-calls / tokens / latence / modèle. Complète le quota tracker
(forge_token_monitor.log_call) sans le remplacer.

INERTE tant que, au runtime (env py314 du hub) :
  - langfuse n'est pas installé, OU
  - LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY absents de l'env.
→ fail-open TOTAL : aucune exception ne remonte, ne casse jamais le chemin LLM.

SOUVERAINETÉ / égress (Golden Rule #4) : l'I/O LLM est REDACTÉ via
forge_semantic_firewall.redact_for_log (secrets/PII/CB/IBAN → tags HMAC
déterministes) AVANT envoi. Modes via LANGFUSE_IO_MODE :
  - 'redacted' (défaut) : I/O complet mais rédacté
  - 'meta'              : zéro texte (métadonnées seules — souveraineté max)
  - 'raw'               : texte brut (opt-in explicite)
Recommandé : LANGFUSE_HOST self-hosted (sinon défaut cloud.langfuse.com = égress).

Activation : voir [[roadmap_observability_no_blindspots_2026-06-02]].
"""
from __future__ import annotations

import logging
import os
import threading
from nokido_agent.app.forge_secrets import get_secret

logger = logging.getLogger("forge_langfuse_hook")

_client = None
_lock = threading.Lock()
_disabled_reason: str | None = None  # pourquoi inerte (loggé 1×)


def _redact(text):
    if text is None:
        return None
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_for_log
        return redact_for_log(text)
    except Exception:
        return text


def _get_client():
    """Singleton Langfuse, ou None si inerte (keys absentes / sdk absent)."""
    global _client, _disabled_reason
    if _client is not None:
        return _client
    if _disabled_reason is not None:
        return None
    pk = get_secret("LANGFUSE_PUBLIC_KEY")
    sk = get_secret("LANGFUSE_SECRET_KEY")
    if not (pk and sk):
        _disabled_reason = "LANGFUSE_PUBLIC_KEY/SECRET_KEY absents"
        logger.info("[langfuse] inerte: %s", _disabled_reason)
        return None
    with _lock:
        if _client is not None:
            return _client
        try:
            from langfuse import Langfuse
            host = os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"
            _client = Langfuse(public_key=pk, secret_key=sk, host=host)
            logger.info("[langfuse] client actif host=%s", host)
        except Exception as exc:  # noqa: BLE001 - sdk absent/incompatible → inerte
            _disabled_reason = f"langfuse indisponible: {exc}"
            logger.info("[langfuse] inerte: %s", _disabled_reason)
            _client = None
    return _client


def emit(provider, model, input_text, output_text, prompt_tokens,
         completion_tokens, latency_ms, metadata=None) -> None:
    """Émet une génération Langfuse pour un appel LLM terminé. Fail-open."""
    try:
        client = _get_client()
        if client is None:
            return
        mode = (os.environ.get("LANGFUSE_IO_MODE") or "redacted").lower()
        if mode == "meta":
            inp = out = None
        elif mode == "raw":
            inp, out = input_text, output_text
        else:  # redacted (défaut)
            inp, out = _redact(input_text), _redact(output_text)
        meta = {"latency_ms": round(float(latency_ms or 0), 1), "source": "forge_agent_proxy"}
        if metadata:
            meta.update(metadata)
        usage = {"input": int(prompt_tokens or 0), "output": int(completion_tokens or 0)}
        name = f"llm:{provider}"

        # Langfuse v3/v4 (OTEL) : start_generation, fallback start_observation.
        try:
            gen = client.start_generation(name=name, model=model, input=inp, metadata=meta)
        except AttributeError:
            gen = client.start_observation(
                name=name, as_type="generation", model=model, input=inp, metadata=meta
            )
        try:
            gen.update(output=out, usage_details=usage)
        except TypeError:
            gen.update(output=out, usage=usage)
        gen.end()
        # Pas de flush par appel (coûteux) : le client batch + flush en fond.
    except Exception as exc:  # noqa: BLE001 - ne JAMAIS casser le chemin LLM
        logger.debug("[langfuse] emit skip: %s", exc)


def status() -> dict:
    """État du wiring (diagnostic)."""
    return {
        "active": _client is not None,
        "disabled_reason": _disabled_reason,
        "io_mode": (os.environ.get("LANGFUSE_IO_MODE") or "redacted").lower(),
        "host": os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com",
        "keys_present": bool(get_secret("LANGFUSE_PUBLIC_KEY")
                             and get_secret("LANGFUSE_SECRET_KEY")),
    }
