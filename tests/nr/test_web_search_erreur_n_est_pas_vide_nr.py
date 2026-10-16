"""NR - une recherche web qui n'a pas pu se faire n'est pas « aucun resultat » (15/10).

Mesure du 15/10 : `web_search` a repondu « Aucun resultat » alors que SearXNG etait ETEINT
(connexion refusee), puis encore juste apres son reveil : `_searxng_sync` changeait TOUTE
exception en liste vide, journalisee en debug. L'appelant concluait a l'absence -- UNKNOWN lu
comme NO. `web_search_diag` nomme l'erreur ; les signatures historiques restent. Reseau simule.
"""
from __future__ import annotations

import asyncio
import io
import json
import urllib.error

import pytest

from nokido_agent.app import forge_web_fallback as W


class _Rep(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reponse(resultats):
    return lambda *_a, **_k: _Rep(json.dumps({"results": resultats}).encode("utf-8"))


def _leve(exc):
    def urlopen(*_a, **_k):
        raise exc
    return urlopen


def test_moteur_eteint_rend_une_erreur_nommee_pas_un_vide(monkeypatch):
    monkeypatch.setattr(W.urllib.request, "urlopen", _leve(urllib.error.URLError(ConnectionRefusedError())))
    d = asyncio.run(W.web_search_diag("q"))
    assert d["results"] == [] and len(d["erreurs"]) == 2
    assert all("URLError" in e for e in d["erreurs"])


def test_reponse_vide_n_est_pas_une_erreur(monkeypatch):
    monkeypatch.setattr(W.urllib.request, "urlopen", _reponse([]))
    d = asyncio.run(W.web_search_diag("q"))
    assert d == {"results": [], "erreurs": [], "source": None}


def test_resultats_rendus_avec_leur_source(monkeypatch):
    monkeypatch.setattr(W.urllib.request, "urlopen", _reponse([{"title": "t", "url": "u", "content": "c"}]))
    d = asyncio.run(W.web_search_diag("q"))
    assert d["source"] == "searxng" and d["results"][0]["_source"] == "searxng"


@pytest.mark.parametrize("exc", [urllib.error.URLError(ConnectionRefusedError()), TimeoutError("lent")])
def test_signatures_historiques_gardees(monkeypatch, exc):
    monkeypatch.setattr(W.urllib.request, "urlopen", _leve(exc))
    assert W._searxng_sync("q", 5) == []
    assert asyncio.run(W.web_search_with_fallback("q")) == []
    res, err = W._searxng_diag("q", 5)
    assert res == [] and err
