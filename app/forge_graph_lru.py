'''app/forge_graph_lru.py - LRU+TTL cache pour GraphLinker.
Delegue le stockage a forge_cache (primitive unifiee, backend cachebox si dispo,
fallback pur-Python sinon). Conserve les compteurs hits/misses pour stats().
Consolidation veille 2026-06-23 (ex-OrderedDict fait-main -> forge_cache).
'''
from __future__ import annotations
import threading
from typing import Any
from nokido_agent.app.forge_cache import make_cache, BACKEND


class GraphLRUCache:
    '''LRU cache TTL pour get_impacted_by_change(). API preservee: get/set/invalidate/clear/stats.'''

    def __init__(self, maxsize: int = 256, ttl: int = 120) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._backend = make_cache('ttl', maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str):
        val = self._backend.get(key, None)
        with self._lock:
            if val is None:
                self._misses += 1
            else:
                self._hits += 1
        return val

    def set(self, key: str, value: Any) -> None:
        self._backend.set(key, value)

    def invalidate(self, key: str) -> None:
        self._backend.delete(key)

    def clear(self) -> None:
        self._backend.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': round(self._hits / total, 3) if total else 0.0,
                'size': len(self._backend),
                'maxsize': self._maxsize,
                'ttl': self._ttl,
                'backend': BACKEND,
            }


# Singleton partage
_default_cache = GraphLRUCache()


def get_cache() -> GraphLRUCache:
    '''Retourne l instance singleton du cache LRU.'''
    return _default_cache
