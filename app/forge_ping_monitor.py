# -*- coding: utf-8 -*-
"""
forge_ping_monitor.py — Ping providers en parallèle (asyncio.gather)
====================================================================
Session 5 — 2026-04-27
Remplace le ping séquentiel (>30s pour 9 providers) par gather (~3s).
"""

from __future__ import annotations
import asyncio, time
from typing import Optional


async def ping_all_providers(providers: list, timeout: float = 5.0) -> dict:
    """
    Ping N providers en parallèle.
    providers: [{"name": str, "url": str, "headers": dict}]
    Retourne: {name: {"ok": bool, "ttft_ms": float|None, "status": int|None}}
    """
    try:
        import aiohttp
    except ImportError:
        return {p["name"]: {"ok": False, "ttft_ms": None, "error": "aiohttp absent"} for p in providers}

    async def _ping_one(session, p: dict):
        t0 = asyncio.get_event_loop().time()
        try:
            async with session.get(
                p["url"], headers=p.get("headers", {}), timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                ttft = (asyncio.get_event_loop().time() - t0) * 1000
                ok = resp.status < 400
                try:
                    from nokido_agent.app.forge_trust_score import TrustScoreRegistry

                    if ok:
                        TrustScoreRegistry.get().record_success(p["name"], ttft)
                    else:
                        TrustScoreRegistry.get().record_failure(p["name"])
                except Exception:
                    pass
                return p["name"], {"ok": ok, "ttft_ms": round(ttft, 1), "status": resp.status}
        except Exception as e:
            try:
                from nokido_agent.app.forge_trust_score import TrustScoreRegistry

                TrustScoreRegistry.get().record_failure(p["name"])
            except Exception:
                pass
            return p["name"], {"ok": False, "ttft_ms": None, "error": str(e)[:80]}

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[_ping_one(session, p) for p in providers])
    return dict(results)


def ping_all_sync(providers: list, timeout: float = 5.0) -> dict:
    """Wrapper synchrone compatible avec le hub."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, ping_all_providers(providers, timeout)).result()
        return loop.run_until_complete(ping_all_providers(providers, timeout))
    except RuntimeError:
        return asyncio.run(ping_all_providers(providers, timeout))


# ── F32 provider_health — score composite 0.0..1.0 (TTL 30s) ─────────────────
import threading as _threading

_HEALTH_CACHE: dict = {}
_HEALTH_LOCK = _threading.Lock()

_LATENCY_BUDGET_MS: dict = {
    "groq": 2000,
    "ollama": 60000,
    "llamacpp": 20000,
    "gemini": 8000,
    "mistral": 5000,
    "hf": 3000,
    "lmstudio": 20000,
    "default": 10000,
}

# Endpoints de ping par provider (HEAD / GET rapide)
_PROVIDER_PING_URLS: dict = {
    "ollama": {"name": "ollama", "url": "http://127.0.0.1:11434/"},
    "llamacpp": {"name": "llamacpp", "url": "http://127.0.0.1:8091/health"},
    "lmstudio": {"name": "lmstudio", "url": "http://127.0.0.1:1234/v1/models"},
    "groq": {"name": "groq", "url": "https://api.groq.com/"},
    "gemini": {"name": "gemini", "url": "https://generativelanguage.googleapis.com/"},
    "mistral": {"name": "mistral", "url": "https://api.mistral.ai/"},
    "hf": {"name": "hf", "url": "https://huggingface.co/"},
}


def get_provider_health(providers: list[str], timeout: float = 3.0) -> dict[str, float]:
    """
    Retourne health_score 0.0..1.0 par provider.
    score = ok * min(1.0, budget_ms / measured_latency_ms)
    Cache TTL 30s, thread-safe.
    """
    now = time.time()
    result: dict[str, float] = {}
    to_ping: list[dict] = []

    with _HEALTH_LOCK:
        for p in providers:
            cached = _HEALTH_CACHE.get(p)
            if cached and (now - cached["ts"]) < 30:
                result[p] = cached["score"]
            elif p in _PROVIDER_PING_URLS:
                to_ping.append(_PROVIDER_PING_URLS[p])
            else:
                result[p] = 0.5  # provider inconnu → score neutre

    if to_ping:
        raw = ping_all_sync(to_ping, timeout=timeout)
        with _HEALTH_LOCK:
            for entry in to_ping:
                name = entry["name"]
                r = raw.get(name, {})
                ok = r.get("ok", False)
                lat = r.get("ttft_ms") or 0.0
                budget = _LATENCY_BUDGET_MS.get(name, _LATENCY_BUDGET_MS["default"])
                score = (min(1.0, budget / lat) if lat > 0 else 1.0) if ok else 0.0
                _HEALTH_CACHE[name] = {"score": score, "ts": time.time()}
                result[name] = score

    return result
