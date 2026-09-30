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

    url = "https://api.tavily.com/search"
    payload = {"api_key": api_key, "query": query, "max_results": max_results}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [
                        {"title": r["title"], "content": r["content"], "url": r["url"]} for r in data.get("results", [])
                    ]
    except Exception as e:
        logger.debug(f"Tavily search failed: {e}")
    return []


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
    """SearXNG -> Tavily -> DuckDuckGo"""
    tavily_key = get_secret("TAVILY_API_KEY")
    results = []

    results = await search_searxng(query, max_results)
    if not results and tavily_key:
        results = await search_tavily(query, tavily_key, max_results)
    if not results:
        results = await search_duckduckgo(query, max_results)

    return results


if __name__ == "__main__":
    import os

    async def _test():
        res = await aggregate_search("Derniere version de Python 2026")
        for r in res:
            print(f"- {r['title']} ({r['url']})")

    asyncio.run(_test())
