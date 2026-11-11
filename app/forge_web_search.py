from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-25 | VER:v_forge_web_search
#FORGE:[score:96|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Centralized Web Search with Free Tier Providers
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:96|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import asyncio
import logging
import os
from typing import List, Dict, Any, Optional

logger = logging.getLogger("Nokido.WebSearch")


async def search_tavily(query: str, api_key: str, max_results: int = 5) -> List[Dict[str, Any]]:
    import aiohttp

    res, _err = await search_tavily_diag(query, api_key, max_results)
    return res


async def search_tavily_diag(query: str, api_key: str, max_results: int = 5) -> tuple:
    """(resultats, erreur NOMMEE ou None) -- l'organe de recherche unique (forge_web_fallback, T2a owner 10/11)
    doit distinguer « rien trouve » d'un echec ; search_tavily, qui avale l'erreur, lui delegue."""
    import aiohttp

    url = "https://api.tavily.com/search"
    payload = {"api_key": api_key, "query": query, "max_results": max_results}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [
                        {"title": r["title"], "content": r["content"], "url": r["url"]} for r in data.get("results", [])
                    ], None
                return [], "tavily: HTTP %s" % resp.status
    except Exception as e:
        logger.debug(f"Tavily search failed: {e}")
        return [], "tavily: %s: %s" % (type(e).__name__, str(e)[:120])


async def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    try:
        from nokido_agent.app.forge_web import web_search

        raw_results = await web_search(query, max_results=max_results, fetch_full=False)
        formatted = []
        for r in raw_results:
            # Format: [Title] Snippet\nURL
            lines = r.split("\n")
            title = lines[0].strip("[]")
            url = lines[-1]
            content = " ".join(lines[1:-1])
            formatted.append({"title": title, "content": content, "url": url})
        return formatted
    except Exception as e:
        logger.debug(f"DuckDuckGo search failed: {e}")
    return []


async def search_searxng(query: str, max_results: int = 5, time_range: str = None, language: str = "all") -> list:
    import urllib.request, json, urllib.parse

    base = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8080")
    params = {k: v for k, v in {"q": query, "format": "json", "language": language}.items()}
    if time_range:
        params["time_range"] = time_range
    url = base + "/search?" + urllib.parse.urlencode(params)
    try:
        r = urllib.request.urlopen(url, timeout=5)
        data = json.loads(r.read())
        return [
            {"title": x.get("title", ""), "content": x.get("content", ""), "url": x.get("url", "")}
            for x in data.get("results", [])[:max_results]
        ]
    except Exception as e:
        logger.debug(f"SearXNG search failed: {e}")
    return []


async def aggregate_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """FACADE de l'organe de recherche unique forge_web_fallback (T2b, decision owner 10/11 ; livrable
    OPENCODE_GPTOSS 560ce6beb). Fin de la cascade parallele SearXNG -> Tavily NON budgete -> DuckDuckGo (CAPTCHA).
    Forme historique conservee : [{title, content, url}]."""
    try:
        from nokido_agent.app.forge_web_fallback import web_search_diag
    except ImportError:  # repli checkout
        from forge_web_fallback import web_search_diag

    d = await web_search_diag(query, max_results=max_results)
    return [{"title": r.get("title") or "", "content": r.get("content") or "", "url": r.get("url") or ""}
            for r in (d.get("results") or []) if isinstance(r, dict)]


if __name__ == "__main__":
    import os

    async def _test():
        res = await aggregate_search("Derniere version de Python 2026")
        for r in res:
            print(f"- {r['title']} ({r['url']})")

    asyncio.run(_test())
