# GEMINI TRANSMISSION — FORGE_GRAPH_LRU — 2026-05-06

## OBJET
Mise à jour de `app/forge_graph_lru.py` pour ajouter le support du TTL (Time To Live) requis par GraphLinker.

## CHANGEMENTS
- Implémentation d'une classe `GraphLRUCache` thread-safe.
- Ajout d'un TTL de 120 secondes par défaut.
- Stockage des tuples `(valeur, expiration)`.
- Mise à jour de la méthode `get()` pour invalider les entrées expirées.
- Ajout de statistiques de cache (hits, misses, hit_rate, size, ttl).
- Exposition du singleton via `get_cache()`.

## VALIDATION
Tests unitaires validés via `tests/test_forge_graph_lru.py` :
- `test_lru_basic` : Succès (éviction LRU respectée).
- `test_ttl` : Succès (expiration après 1s vérifiée).
- `test_stats` : Succès.

## CODE COMPLET
```python
"""app/forge_graph_lru.py — LRU cache thread-safe avec TTL pour GraphLinker."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class GraphLRUCache:
    """
    LRU cache pour résultats get_impacted_by_change(). 
    Thread-safe avec TTL (Time To Live).
    """

    def __init__(self, maxsize: int = 256, ttl: int = 120) -> None:
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl     = ttl
        self._lock    = threading.Lock()
        self._hits    = 0
        self._misses  = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            value, expiry = self._cache[key]
            
            # Vérifier l'expiration
            if time.time() > expiry:
                del self._cache[key]
                self._misses += 1
                return None
                
            self._hits += 1
            self._cache.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            
            expiry = time.time() + self._ttl
            self._cache[key] = (value, expiry)
            
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits":     self._hits,
                "misses":   self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
                "size":     len(self._cache),
                "maxsize":  self._maxsize,
                "ttl":      self._ttl
            }


# Singleton partagé
_default_cache = GraphLRUCache()


def get_cache() -> GraphLRUCache:
    """Retourne l'instance singleton du cache LRU."""
    return _default_cache
```
