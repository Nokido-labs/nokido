'''app/forge_cache.py - Cache unifie Nokido (LRU/TTL/LFU).
Consolide les caches faits-main epars (forge_graph_lru.GraphLRUCache, etc.)
derriere une primitive unique. Backend cachebox (Rust, rapide) si dispo,
fallback pur-Python (OrderedDict+lock+TTL) sinon. Expose default_cache
(singleton LRU) + make_cache(policy, maxsize, ttl). Issu veille 2026-06-23.
__FORGE_COLOR__: infra/util : cache generique
'''
from __future__ import annotations
import time
import threading
from collections import OrderedDict

try:
    import cachebox as _cb
    _HAVE = True
except Exception:
    _cb = None
    _HAVE = False

BACKEND = 'cachebox' if _HAVE else 'python'
_MISS = object()


class _PyCache:
    # Fallback pur-Python : LRU + TTL optionnel, thread-safe.
    def __init__(self, maxsize=256, ttl=None):
        self.maxsize = max(1, int(maxsize))
        self.ttl = ttl
        self._d = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            item = self._d.get(key)
            if item is None:
                return default
            val, exp = item
            if exp is not None and exp <= time.time():
                del self._d[key]
                return default
            self._d.move_to_end(key)
            return val

    def set(self, key, value):
        with self._lock:
            exp = (time.time() + self.ttl) if self.ttl else None
            if key in self._d:
                self._d.move_to_end(key)
            elif len(self._d) >= self.maxsize:
                self._d.popitem(last=False)
            self._d[key] = (value, exp)

    def __contains__(self, key):
        return self.get(key, _MISS) is not _MISS

    def __len__(self):
        with self._lock:
            return len(self._d)

    def clear(self):
        with self._lock:
            self._d.clear()

    def delete(self, key):
        with self._lock:
            self._d.pop(key, None)


class _CBAdapter:
    # API uniforme (get/set/__contains__/__len__/clear) sur une instance cachebox.
    def __init__(self, impl):
        self._impl = impl

    def get(self, key, default=None):
        try:
            return self._impl.get(key, default)
        except Exception:
            return default

    def set(self, key, value):
        self._impl[key] = value

    def __contains__(self, key):
        return key in self._impl

    def __len__(self):
        return len(self._impl)

    def clear(self):
        self._impl.clear()

    def delete(self, key):
        try:
            del self._impl[key]
        except Exception:
            pass


def make_cache(policy='lru', maxsize=256, ttl=None):
    # policy in {lru, lfu, ttl}. Backend cachebox si dispo, sinon pur-Python.
    policy = (policy or 'lru').lower()
    if _HAVE:
        if policy == 'lru':
            return _CBAdapter(_cb.LRUCache(maxsize))
        if policy == 'lfu':
            return _CBAdapter(_cb.LFUCache(maxsize))
        if policy == 'ttl':
            return _CBAdapter(_cb.TTLCache(maxsize, ttl or 0))
        raise ValueError('policy inconnue: ' + str(policy))
    return _PyCache(maxsize=maxsize, ttl=ttl)


# Singleton defaut (pattern defaultCache)
default_cache = make_cache('lru', maxsize=1024)
