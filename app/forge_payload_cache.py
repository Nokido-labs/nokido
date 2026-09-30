"""
forge_payload_cache.py — Payloads JWT pré-forgés en mémoire
============================================================
Principe : pré-assembler les trames fréquentes au boot du hub.
Comme des paquets IP pré-assemblés dans un buffer réseau.

Patterns pré-forgés :
  - inbox_signal  : signal léger "va lire ta boîte" (TTL 15s → refresh auto)
  - ack           : accusé de réception (TTL 15s)
  - notify_agent  : notification standard (TTL 300s)
  - ping          : keepalive (TTL 30s)

Refresh automatique avant expiration.
Accès O(1) via dict en mémoire.
"""

__FORGE_COLOR__ = "immunitaire/secret : payloads JWT pre-forges en memoire"  # organe declare le 2026-09-06 (audit de raccordement)

import time, threading, logging
from typing import Dict, Optional

logger = logging.getLogger("Nokido.PayloadCache")

_cache: Dict[str, dict] = {}  # {key: {token, forged_at, ttl}}
_lock = threading.Lock()
_initialized = False

AGENTS = ["agt_gemini", "agt_codex", "agt_claude", "agt_cline"]
INTENTS = {
    "inbox_signal": 15,  # TTL court — signal éphémère
    "ack": 15,
    "ping": 30,
    "notify_agent": 300,  # TTL long — réutilisable
}


def _forge_all() -> None:
    """Pré-forge tous les tokens fréquents."""
    try:
        from nokido_agent.app.forge_jwt_router import forge_frame_token
    except ImportError:
        return
    with _lock:
        for to_agent in AGENTS:
            for intent, ttl in INTENTS.items():
                key = f"hub→{to_agent}:{intent}"
                try:
                    token = forge_frame_token(
                        from_agent="hub",
                        to_agent=to_agent,
                        intent=intent,
                    )
                    _cache[key] = {
                        "token": token,
                        "forged_at": int(time.time()),
                        "ttl": ttl,
                    }
                except Exception as e:
                    logger.debug(f"PayloadCache skip {key}: {e}")


def _refresh_expired() -> None:
    """Refresh les tokens qui expirent dans < 5s."""
    try:
        from nokido_agent.app.forge_jwt_router import forge_frame_token
    except ImportError:
        return
    now = int(time.time())
    to_refresh = []
    with _lock:
        for key, entry in _cache.items():
            age = now - entry["forged_at"]
            if age >= entry["ttl"] - 5:  # refresh 5s avant expiration
                to_refresh.append(key)
    for key in to_refresh:
        parts = key.split("→")[1].split(":")  # "agt_gemini:inbox_signal"
        to_agent, intent = parts[0], parts[1]
        try:
            token = forge_frame_token(from_agent="hub", to_agent=to_agent, intent=intent)
            with _lock:
                _cache[key] = {"token": token, "forged_at": now, "ttl": INTENTS.get(intent, 30)}
        except Exception:
            pass


def get(to_agent: str, intent: str) -> Optional[str]:
    """
    Retourne un token pré-forgé. O(1), thread-safe.
    Si absent ou expiré → forge à la volée et met en cache.
    """
    global _initialized
    if not _initialized:
        init()
    key = f"hub→{to_agent}:{intent}"
    with _lock:
        entry = _cache.get(key)
    if entry:
        age = int(time.time()) - entry["forged_at"]
        if age < entry["ttl"] - 2:
            return entry["token"]
    # Forge à la volée si absent/expiré
    try:
        from nokido_agent.app.forge_jwt_router import forge_frame_token

        token = forge_frame_token(from_agent="hub", to_agent=to_agent, intent=intent)
        ttl = INTENTS.get(intent, 30)
        with _lock:
            _cache[key] = {"token": token, "forged_at": int(time.time()), "ttl": ttl}
        return token
    except Exception:
        return ""


def init() -> None:
    """Initialise et lance le refresh daemon."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    _forge_all()

    # Daemon de refresh en arrière-plan
    def _refresh_loop():
        while True:
            time.sleep(10)
            _refresh_expired()

    t = threading.Thread(target=_refresh_loop, daemon=True, name="PayloadCacheRefresh")
    t.start()
    logger.info(f"PayloadCache: {len(_cache)} tokens pré-forgés")


def stats() -> dict:
    """Stats du cache pour monitoring."""
    now = int(time.time())
    with _lock:
        return {
            "total": len(_cache),
            "entries": {
                k: {"age_s": now - v["forged_at"], "ttl": v["ttl"], "valid": (now - v["forged_at"]) < v["ttl"]}
                for k, v in _cache.items()
            },
        }
