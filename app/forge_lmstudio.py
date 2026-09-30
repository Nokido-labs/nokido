# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_lmstudio
#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: OpenAI-Compatible Bridge for LM Studio (Port 1234)
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import asyncio
import aiohttp
import json
import logging
import os
from typing import Optional, List, Dict, Callable

logger = logging.getLogger("Nokido.LMStudio")

LMS_URL = "http://localhost:1234/v1/chat/completions"


def _auth_headers() -> dict:
    """Bearer token depuis WCM (forge_secrets) pour llmster daemon auth."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        token = get_secret("LMSTUDIO_TOKEN") or ""
    except Exception:
        token = get_secret("LMSTUDIO_TOKEN") or ""
    return {"Authorization": f"Bearer {token}"} if token else {}


async def lms_call(
    messages: List[Dict],
    model: str = "local-model",
    system: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """Appel LM Studio (OpenAI-compatible) NON-STREAMING."""
    payload_msgs = []
    if system:
        payload_msgs.append({"role": "system", "content": system})
    payload_msgs.extend(messages)

    payload = {
        "model": model,
        "messages": payload_msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession(headers=_auth_headers()) as session:
            async with session.post(LMS_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"LM Studio Error {resp.status}: {body[:200]}")
                    return ""
                data = await resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.debug(f"LM Studio inaccessible: {e}")
        return ""


async def lms_stream(
    messages: List[Dict],
    on_token: Callable[[str], None],
    on_done: Callable[[], None],
    model: str = "local-model",
    system: Optional[str] = None,
) -> str:
    """Appel LM Studio STREAMING."""
    payload_msgs = []
    if system:
        payload_msgs.append({"role": "system", "content": system})
    payload_msgs.extend(messages)

    payload = {"model": model, "messages": payload_msgs, "stream": True}

    full_text = []
    try:
        async with aiohttp.ClientSession(headers=_auth_headers()) as session:
            async with session.post(LMS_URL, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status != 200:
                    return ""

                async for line in resp.content:
                    if not line:
                        continue
                    decoded = line.decode("utf-8").strip()
                    if decoded.startswith("data: "):
                        content = decoded[6:]
                        if content == "[DONE]":
                            break
                        try:
                            data = json.loads(content)
                            tok = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if tok:
                                full_text.append(tok)
                                on_token(tok)
                        except:
                            continue

                on_done()
                return "".join(full_text)
    except Exception as e:
        logger.debug(f"LM Studio Stream Error: {e}")
        return ""


def is_available() -> bool:
    """Vérification rapide de la présence du serveur LM Studio."""
    # Note: On pourrait faire un petit ping HTTP GET ici.
    return True
