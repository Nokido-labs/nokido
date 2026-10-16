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


# UNE ERREUR N'EST PAS « AUCUN RESULTAT » (15/10). Mesure : `web_search` a repondu « Aucun
# resultat » alors que SearXNG etait ETEINT (connexion refusee), puis encore juste apres son
# reveil (ping OK, recherches vides) : l'appelant concluait a l'absence de resultats -- UNKNOWN
# lu comme NO. `_searxng_diag` rend (resultats, erreur) ; `web_search_diag` porte les erreurs ;
# les signatures historiques (`_searxng_sync`, `web_search_with_fallback`) sont gardees.
def _searxng_diag(query: str, max_results: int, engines: str = "") -> tuple:
    """(resultats, erreur) : erreur = None si SearXNG a REPONDU (meme une liste vide)."""
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
            ], None
    except Exception as e:  # noqa: BLE001 - rendu comme erreur NOMMEE, jamais comme liste vide muette
        logger.warning(f"[searxng/{engines or 'default'}] {type(e).__name__}: {e}")
        return [], "%s/%s: %s" % (engines or "default", type(e).__name__, str(e)[:120])


def _searxng_sync(query: str, max_results: int, engines: str = "") -> List[Dict]:
    return _searxng_diag(query, max_results, engines)[0]


async def web_search_diag(query: str, max_results: int = 5) -> Dict:
    """{"results": [...], "erreurs": [...], "source": ...} -- meme cascade, erreurs NOMMEES.

    `results` vide ET `erreurs` vide = SearXNG a repondu sans rien trouver ; `erreurs` non vide
    = on n'a PAS pu chercher (moteur eteint, delai, refus) : ce n'est jamais « aucun resultat »."""
    loop = asyncio.get_event_loop()
    erreurs: List[str] = []
    for moteurs, source in (("", "searxng"), ("duckduckgo", "duckduckgo")):
        res, err = await loop.run_in_executor(None, _searxng_diag, query, max_results, moteurs)
        if err:
            erreurs.append(err)
        if res:
            for r in res:
                r["_source"] = source
            return {"results": res, "erreurs": erreurs, "source": source}
    return {"results": [], "erreurs": erreurs, "source": None}


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
