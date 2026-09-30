"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_performance_tuner
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_performance_tuner.py
================================
PERFORMANCE_TUNER_V1 — minimize_latency
Connection pooling + DNS prefetch + MCP definition caching.
"""

import time, threading
from typing import Optional

# ── Connection Pool HTTP ──────────────────────────────────────────────────────
_pool = None
_pool_lock = threading.Lock()


def get_http_session() -> object:
    """Pool de connexions HTTP persistantes (keep-alive)."""
    global _pool
    with _pool_lock:
        if _pool is None:
            try:
                import urllib3

                _pool = urllib3.PoolManager(
                    num_pools=5,
                    maxsize=3,
                    timeout=urllib3.Timeout(connect=3.0, read=30.0),
                    retries=urllib3.Retry(3, backoff_factor=0.3),
                    headers={"Connection": "keep-alive"},
                )
            except ImportError:
                _pool = None
    return _pool


# ── DNS Prefetch ──────────────────────────────────────────────────────────────
_dns_cache: dict = {}


def prefetch_dns(hosts: list) -> None:
    """Résout les DNS en arrière-plan pour éviter la latence au premier appel."""
    import socket, threading

    def _resolve(host) -> None:
        """Resolve.

        Args:
            host: Description.
        """
        try:
            result = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            _dns_cache[host] = result[0][4][0]
        except Exception:
            pass

    threads = [threading.Thread(target=_resolve, args=(h,), daemon=True) for h in hosts]
    for t in threads:
        t.start()


# ── MCP Definition Cache ──────────────────────────────────────────────────────
_mcp_cache: dict = {}
_mcp_cache_ttl = 300  # 5 minutes


def get_cached_mcp_def(tool_name: str) -> Optional[dict]:
    """Get cached mcp def.

    Args:
        tool_name: Description.
    """
    entry = _mcp_cache.get(tool_name)
    if entry and time.time() - entry["ts"] < _mcp_cache_ttl:
        return entry["def"]
    return None


def cache_mcp_def(tool_name: str, definition: dict) -> None:
    """Cache mcp def.

    Args:
        tool_name: Description.
        definition: Description.
    """
    _mcp_cache[tool_name] = {"def": definition, "ts": time.time()}


# ── Timeout adaptatif ─────────────────────────────────────────────────────────
PROVIDER_TIMEOUTS = {
    "gemini": 25,  # rapide (70ms connect)
    "groq_70b": 20,  # très rapide (53ms connect)
    "deepseek_direct": 35,  # un peu plus lent (281ms connect)
    "llamacpp_local": 45,  # local, dépend charge CPU
    "laforge": 10,  # si Ollama absent → fail fast
    "llamacpp": 10,  # idem
    "default": 30,
}


def get_timeout(provider: str) -> int:
    """Get timeout.

    Args:
        provider: Description.
    """
    return PROVIDER_TIMEOUTS.get(provider, PROVIDER_TIMEOUTS["default"])


# ── Init au démarrage ─────────────────────────────────────────────────────────
def init_performance() -> None:
    """Lance le prefetch DNS et warm-up pool au démarrage."""
    prefetch_dns(
        [
            "api.deepseek.com",
            "generativelanguage.googleapis.com",
            "api.groq.com",
            "codeberg.org",
            "github.com",
        ]
    )
    get_http_session()
    print("[PERF] Connection pool + DNS prefetch initialisés")
