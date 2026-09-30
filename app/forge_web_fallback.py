"""
forge_web_fallback.py - Fallback SearXNG: engines generaux -> duckduckgo -> vide
Pas de LLM externe. Tout local.
"""

from __future__ import annotations
import asyncio, json, urllib.request, urllib.parse, logging, time
from typing import List, Dict

logger = logging.getLogger("Nokido.WebFallback")
SEARXNG_URL = "http://127.0.0.1:8080"
SEARXNG_TIMEOUT = 5


def _searxng_sync(query: str, max_results: int, engines: str = "") -> List[Dict]:
    params: Dict = {"q": query, "format": "json"}
    if engines:
        params["engines"] = engines
    url = SEARXNG_URL + "/search?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"}), timeout=SEARXNG_TIMEOUT
        ) as r:
            return [
                x for x in json.loads(r.read()).get("results", [])[:max_results] if x.get("title") or x.get("content")
            ]
    except Exception as e:
        logger.debug(f"[searxng/{engines or 'default'}] {e}")
        return []


async def web_search_with_fallback(
    query: str,
    max_results: int = 5,
) -> List[Dict]:
    """
    Cascade :
      1. SearXNG engines par defaut
      2. SearXNG engine=duckduckgo (toujours ok)
      3. [] si tout echoue
    100% local, zero token externe.
    """
    loop = asyncio.get_event_loop()

    # Niveau 1 : engines par defaut
    t0 = time.monotonic()
    results = await loop.run_in_executor(None, _searxng_sync, query, max_results, "")
    ms = round((time.monotonic() - t0) * 1000)
    if results:
        for r in results:
            r["_source"] = "searxng"
        logger.info(f"[web] default OK n={len(results)} {ms}ms")
        return results

    logger.warning(f"[web] default vide ({ms}ms) -> DDG fallback")

    # Niveau 2 : DuckDuckGo explicite
    results = await loop.run_in_executor(None, _searxng_sync, query, max_results, "duckduckgo")
    if results:
        for r in results:
            r["_source"] = "duckduckgo"
        logger.info(f"[web] DDG OK n={len(results)}")
        return results

    return []


def format_results(results: List[Dict], max_chars: int = 400) -> str:
    if not results:
        return "Aucun resultat web disponible."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"[{i}] {r.get('title', '')[:80]}\n"
            f"{r.get('content', '')[:max_chars]}\n"
            f"{r.get('url', '')[:120]} [{r.get('_source', '?')}]"
        )
    return "\n\n".join(lines)
