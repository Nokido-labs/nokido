"""NR -- T2b-a : `forge_web_search.aggregate_search` est une FACADE de l'organe de recherche (10/11 soir).

Decision owner 10/11 : UN organe (forge_web_fallback), les autres chemins deviennent des facades. Avant :
aggregate_search refaisait sa cascade SearXNG -> Tavily (NON budgete, NON filtre sujets prives) -> DuckDuckGo
(CAPTCHA mesure). Livrable OPENCODE_GPTOSS 560ce6beb (sans le NR exige : ecrit par le verificateur). Contrats :
  1. aggregate_search delegue a web_search_diag et rend [{title, content, url}] (cles internes retirees) ;
  2. search_searxng / search_tavily / search_duckduckgo ne sont PLUS appeles ;
  3. resultats vides -> [].
"""
# pylint: disable=import-error,wrong-import-position
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_web_fallback as W  # noqa: E402
import forge_web_search as S  # noqa: E402


def _brancher(monkeypatch, results):
    async def _diag(query, max_results=5):
        return {"results": results, "erreurs": [], "source": "searxng"}

    def _interdit(*a, **k):
        raise AssertionError("chemin parallele appele : la facade doit passer par l'organe")

    monkeypatch.setattr(W, "web_search_diag", _diag)
    try:  # la facade importe d'abord par le paquet : autre objet module, meme double
        from nokido_agent.app import forge_web_fallback as WP
        monkeypatch.setattr(WP, "web_search_diag", _diag)
    except ImportError:
        pass
    for nom in ("search_searxng", "search_tavily", "search_duckduckgo"):
        monkeypatch.setattr(S, nom, _interdit)


def test_facade_delegue_a_l_organe(monkeypatch):
    """Delegation a web_search_diag, forme historique {title, content, url}."""
    _brancher(monkeypatch, [{"title": "t", "content": "c", "url": "u", "_source": "searxng"}])
    assert asyncio.run(S.aggregate_search("q", 3)) == [{"title": "t", "content": "c", "url": "u"}]


def test_facade_vide(monkeypatch):
    """Rien trouve -> liste vide."""
    _brancher(monkeypatch, [])
    assert not asyncio.run(S.aggregate_search("q", 3))
