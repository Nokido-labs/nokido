"""
web.py — Recherche web pour OctoDevOps
=======================================
- DDGS singleton avec session persistante (une seule connexion)
- Pas d'OpenAI, pas de FAISS — utilise le RAGEngine de Nokido
- Cache LRU des résultats (évite de refaire la même recherche)
- Compatible avec l'interface attendue par Nokido (_web_search_fn)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# DÉPENDANCES
# =============================================================================

try:
    from duckduckgo_search import DDGS

    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    logger.warning("duckduckgo_search non installé — web search désactivé")

try:
    from newspaper import Article

    HAS_NEWSPAPER = True
except ImportError:
    HAS_NEWSPAPER = False

# =============================================================================
# CACHE LRU
# =============================================================================

_CACHE_TTL = 300  # secondes avant expiration d'un résultat
_CACHE_MAX = 64  # nombre max d'entrées en cache
_search_cache: OrderedDict = OrderedDict()  # {hash: (timestamp, results)}


def _cache_key(query: str, max_results: int) -> str:
    return hashlib.md5(f"{query}|{max_results}".encode()).hexdigest()


def _cache_get(key: str) -> Optional[List[str]]:
    if key not in _search_cache:
        return None
    ts, results = _search_cache[key]
    if time.monotonic() - ts > _CACHE_TTL:
        del _search_cache[key]
        return None
    _search_cache.move_to_end(key)
    return results


def _cache_set(key: str, results: List[str]) -> None:
    _search_cache[key] = (time.monotonic(), results)
    _search_cache.move_to_end(key)
    while len(_search_cache) > _CACHE_MAX:
        _search_cache.popitem(last=False)


# =============================================================================
# WEBSEARCHENGINE — singleton avec session DDGS persistante
# =============================================================================


class WebSearchEngine:
    """
    Moteur de recherche web avec session DDGS persistante.
    Une seule instance (singleton via get_web_engine()).
    La session DDGS est créée une fois et réutilisée.
    """

    _instance: Optional["WebSearchEngine"] = None

    def __init__(self):
        self._ddgs: Optional[DDGS] = None
        self._lock = asyncio.Lock()
        self._ready = HAS_DDGS

    @classmethod
    def get(cls) -> "WebSearchEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_ddgs(self) -> DDGS:
        """Retourne la session DDGS, la crée si nécessaire."""
        if self._ddgs is None:
            self._ddgs = DDGS()
        return self._ddgs

    async def search(
        self,
        query: str,
        max_results: int = 5,
        fetch_full: bool = False,
    ) -> List[str]:
        """
        Lance une recherche DDG.
        - Vérifie le cache d'abord (TTL 5 min)
        - Réutilise la session DDGS existante
        - fetch_full=True : télécharge le contenu des pages (lent)
        - fetch_full=False : retourne les snippets (rapide, suffisant)
        """
        if not self._ready:
            return []

        key = _cache_key(query, max_results)
        cached = _cache_get(key)
        if cached is not None:
            logger.debug(f"web_search cache hit : {query[:50]}")
            return cached

        async with self._lock:
            # Double-check après acquisition du lock
            cached = _cache_get(key)
            if cached is not None:
                return cached

            try:
                ddgs = self._get_ddgs()
                results = []
                urls = []

                # Recherche DDG — synchrone dans run_in_executor
                loop = asyncio.get_event_loop()

                def _ddg_search():
                    items = []
                    try:
                        for r in ddgs.text(query, max_results=max_results):
                            items.append(r)
                    except Exception as e:
                        logger.warning(f"DDGS search erreur : {e}")
                        # Recréer la session si elle est morte
                        self._ddgs = None
                    return items

                items = await loop.run_in_executor(None, _ddg_search)

                if fetch_full and HAS_NEWSPAPER:
                    # Téléchargement des articles (plus lent)
                    for item in items:
                        url = item.get("href", "")
                        text = await _fetch_article(url)
                        if text and not text.startswith("Error"):
                            results.append(text)
                        urls.append(url)
                else:
                    # Snippets uniquement (rapide)
                    for item in items:
                        snippet = item.get("body", "") or item.get("title", "")
                        url = item.get("href", "")
                        title = item.get("title", "")
                        if snippet:
                            results.append(f"[{title}] {snippet}\n{url}")

                _cache_set(key, results)
                logger.debug(f"web_search '{query[:40]}' → {len(results)} résultats")
                return results

            except Exception as e:
                logger.error(f"WebSearchEngine.search : {e}")
                self._ddgs = None  # reset session en cas d'erreur
                return []

    def clear_cache(self):
        _search_cache.clear()

    @property
    def ready(self) -> bool:
        return self._ready


# =============================================================================
# FETCH ARTICLE
# =============================================================================


async def _fetch_article(url: str) -> str:
    """Télécharge et parse le contenu d'une page (via newspaper3k)."""
    if not HAS_NEWSPAPER or not url:
        return ""
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            article = Article(url)
            article.download()
            article.parse()
            return article.text[:2000]
        except Exception as e:
            return f"Error fetching {url}: {e}"

    return await loop.run_in_executor(None, _fetch)


# =============================================================================
# INTERFACE PUBLIQUE
# =============================================================================


def get_web_engine() -> WebSearchEngine:
    """Retourne le singleton WebSearchEngine."""
    return WebSearchEngine.get()


async def web_search(
    query: str,
    max_results: int = 5,
    fetch_full: bool = False,
) -> List[str]:
    """
    Interface principale — compatible avec _web_search_fn dans Nokido.
    Utilise le singleton (session DDGS persistante, cache LRU).
    """
    return await get_web_engine().search(query, max_results, fetch_full)
