"""
forge_hormones_subscriber.py — Helper API pour daemons qui consomment hormones.

Phase 10 (2026-05-24) — recepteurs actifs. Sans daemons qui SUBSCRIBE, le
systeme endocrinien forge_hormones reste purement publish (1/2 boucle).
Ce module fournit l'API cote consumer.

2 patterns :

1. SYNC polling : `get_dose(hormone, role=None)` -> float 0..1 (somme des
   levels decayes ciblant role, capped 1.0). Utilisable a chaque tick
   daemon pour ajuster comportement.
2. BLOCKING wait : `wait_for_hormone(hormone, role=None, min_level=0.5,
   timeout_s=30)` -> rec or None. Reveille daemon quand hormone passe seuil.

Backend : poll hub :8766 /api/hormones/{active,receptors/<role>}. Lazy,
re-attempt si hub down (fail-safe). Cache court 2s pour eviter spam.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("forge_hormones_subscriber")

HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766")
_HTTP_TIMEOUT_S = 3.0
_CACHE_TTL_S = 2.0

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _hub_get(path: str) -> dict[str, Any] | None:
    url = HUB_URL.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_S) as resp:
            if not (200 <= resp.status < 300):
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _cached_fetch(key: str, fetch_fn) -> list[dict[str, Any]]:
    now = time.time()
    if key in _cache:
        ts, data = _cache[key]
        if now - ts < _CACHE_TTL_S:
            return data
    data = fetch_fn() or []
    _cache[key] = (now, data)
    return data


def active(hormone: str | None = None) -> list[dict[str, Any]]:
    def _fetch():
        path = "/api/hormones/active"
        if hormone:
            path += f"?hormone={hormone}"
        r = _hub_get(path)
        if r and r.get("ok"):
            return r.get("active") or []
        return []

    key = f"active:{hormone or '*'}"
    return _cached_fetch(key, _fetch)


def receptors_for(role: str) -> list[dict[str, Any]]:
    def _fetch():
        r = _hub_get(f"/api/hormones/receptors/{role}")
        if r and r.get("ok"):
            return r.get("active") or []
        return []

    return _cached_fetch(f"recept:{role}", _fetch)


def get_dose(hormone: str, role: str | None = None) -> float:
    """Somme des current_level des events de cette hormone (filtrable role)."""
    events = active(hormone)
    if role:
        events = [r for r in events if role in (r.get("receptors") or [])]
    return min(1.0, sum(r.get("current_level", 0.0) for r in events))


def system_state() -> dict[str, Any]:
    r = _hub_get("/api/hormones/active")
    return (r or {}).get("state", {})


def wait_for_hormone(
    hormone: str,
    role: str | None = None,
    min_level: float = 0.5,
    timeout_s: float = 30.0,
    poll_s: float = 1.0,
) -> dict[str, Any] | None:
    """Blocking poll jusqu'a apparition d'un event hormone >= min_level. None si timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        # Force fresh fetch (skip cache for blocking wait)
        _cache.pop(f"active:{hormone}", None)
        if role:
            _cache.pop(f"recept:{role}", None)
        evts = receptors_for(role) if role else active(hormone)
        for e in evts:
            if e.get("hormone") != hormone:
                continue
            if e.get("current_level", 0.0) >= min_level:
                return e
        time.sleep(poll_s)
    return None


if __name__ == "__main__":
    # smoke
    print("system_state:", json.dumps(system_state(), indent=2))
    print("adrenaline dose:", get_dose("adrenaline"))
    print("active adrenaline:", json.dumps(active("adrenaline"), indent=2))
