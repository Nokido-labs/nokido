"""NR -- l'organe de recherche REVEILLE SearXNG quand il echoue, avant de payer Tavily (10/11 soir).

Mesure : SearXNG :8080 en timeout (Docker endormi), la cascade T2a est passee a Tavily (payant, compteur 8 -> 10)
sans rien reclamer ; seul un `nokido_ensure_service` manuel l'a rendu. Le corps doit traiter ce signal. Contrat :
  1. SearXNG en ERREUR sur toutes les categories -> `_reveiller_searxng()` puis UN rejeu SearXNG ; s'il rend,
     source=searxng et Tavily ne part pas ;
  2. reveil rate -> la cascade continue (Tavily), l'echec du reveil est NOMME dans les erreurs ;
  3. SearXNG qui REPOND sans rien trouver (liste vide, pas d'erreur) -> aucun reveil ;
  4. interrupteur global LAFORGE_WEB_REVEIL=0 -> aucun reveil.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_web_fallback as W  # noqa: E402

_R = {"title": "t", "url": "https://ex.org/a", "content": "c"}


def _brancher(monkeypatch, tmp_path, eveil=True, erreur_searxng=True, reveil_ok=True):
    etat = {"reveille": False, "reveils": 0, "tavily": 0}
    monkeypatch.setenv("LAFORGE_WEB_REVEIL", "1" if eveil else "0")
    monkeypatch.setenv("LAFORGE_WEB_TAVILY", "1")
    monkeypatch.setenv("LAFORGE_WEB_PRIMAIRES", "0")
    monkeypatch.setattr(W, "TAVILY_COMPTEUR", tmp_path / "tavily_budget.json")
    monkeypatch.setattr(W, "sujet_prive", lambda q: False)

    def _sx(query, n, engines="", categories=""):
        if etat["reveille"]:
            return [dict(_R)], None
        return ([], "default/TimeoutError: timed out") if erreur_searxng else ([], None)

    def _reveil():
        etat["reveils"] += 1
        etat["reveille"] = reveil_ok
        return reveil_ok, None if reveil_ok else "reveil searxng: pas pret"

    def _tv(query, n):
        etat["tavily"] += 1
        return [dict(_R)], None

    monkeypatch.setattr(W, "_searxng_diag", _sx)
    monkeypatch.setattr(W, "_reveiller_searxng", _reveil)
    monkeypatch.setattr(W, "_tavily_diag", _tv)
    monkeypatch.setattr(W, "_ollama_web_search", lambda q, n: ([], ""))
    return etat


def test_echec_searxng_reveil_puis_rejeu_sans_tavily(monkeypatch, tmp_path):
    etat = _brancher(monkeypatch, tmp_path)
    d = asyncio.run(W.web_search_diag("pytest-split", 3))
    assert d["source"] == "searxng"
    assert etat["reveils"] == 1 and etat["tavily"] == 0


def test_reveil_rate_continue_tavily_et_le_nomme(monkeypatch, tmp_path):
    etat = _brancher(monkeypatch, tmp_path, reveil_ok=False)
    d = asyncio.run(W.web_search_diag("pytest-split", 3))
    assert d["source"] == "tavily" and etat["tavily"] == 1
    assert any("reveil searxng" in e for e in d["erreurs"])


def test_searxng_repond_vide_pas_de_reveil(monkeypatch, tmp_path):
    etat = _brancher(monkeypatch, tmp_path, erreur_searxng=False)
    asyncio.run(W.web_search_diag("pytest-split", 3))
    assert etat["reveils"] == 0


def test_interrupteur_coupe_pas_de_reveil(monkeypatch, tmp_path):
    etat = _brancher(monkeypatch, tmp_path, eveil=False)
    asyncio.run(W.web_search_diag("pytest-split", 3))
    assert etat["reveils"] == 0
