"""NR — la recherche du tableau de bord RAG, et ses trois etats.

Le tableau de bord RAG n'exposait aucune recherche : l'organe de recuperation sans sa
fonction centrale. La route ajoutee proxifie vers le hub (`rag action=search`), le seul
process qui porte le RAGEngine — meme chemin que le TUI, aucun nouveau proxy invente.

Ce qui se verifie ici n'est pas « la route repond » mais qu'elle ne CONFOND PAS :
  - des extraits (200),
  - une requete vide (400 — la faute est cote appelant),
  - un hub injoignable (503 — indisponibilite, surtout PAS une liste vide).
Le dernier point est celui qui compte : un tableau de bord qui affiche « aucun
resultat » quand il n'a pas pu chercher ment a son lecteur, et c'est exactement la
famille d'erreur que le corps paie le plus cher.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

wired = pytest.importorskip("app.web_hub.wired_routes")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    app = fastapi.FastAPI()
    app.include_router(wired.router)
    return TestClient(app, raise_server_exceptions=False)


def _hub_rend(texte):
    async def _faux(_tool, _args=None, timeout=None):
        return {"result": {"content": [{"text": texte}]}}
    return _faux


def test_extraits_rendus(client, monkeypatch):
    monkeypatch.setattr(wired, "_call", _hub_rend("[chunk 1] contenu reel\n[chunk 2] autre"))
    r = client.post("/api/rag/search", json={"q": "memoire", "limit": 3})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and "contenu reel" in d["texte"]
    assert d["limit"] == 3


def test_requete_vide_est_une_faute_d_appelant(client):
    r = client.post("/api/rag/search", json={"q": "   "})
    assert r.status_code == 400
    assert r.json()["raison"] == "requete_vide"


def test_hub_injoignable_rend_503_et_pas_une_liste_vide(client, monkeypatch):
    async def _mort(_tool, _args=None, timeout=None):
        raise ConnectionError("connexion refusee")
    monkeypatch.setattr(wired, "_call", _mort)
    r = client.post("/api/rag/search", json={"q": "memoire"})
    assert r.status_code == 503, "un hub mort doit etre une INDISPONIBILITE"
    d = r.json()
    assert d["ok"] is False and d["raison"] == "hub_injoignable"
    # Contre-epreuve : rien qui puisse se lire comme un resultat.
    assert "texte" not in d


def test_erreur_remontee_par_le_hub_nest_pas_un_succes(client, monkeypatch):
    async def _err(_tool, _args=None, timeout=None):
        return {"error": "GATE_DENIED: ring insuffisant"}
    monkeypatch.setattr(wired, "_call", _err)
    r = client.post("/api/rag/search", json={"q": "memoire"})
    assert r.status_code == 502
    assert r.json()["ok"] is False


def test_limite_bornee(client, monkeypatch):
    vus = {}

    async def _capte(_tool, args=None, timeout=None):
        vus.update(args or {})
        return {"result": {"content": [{"text": "x"}]}}

    monkeypatch.setattr(wired, "_call", _capte)
    client.post("/api/rag/search", json={"q": "a", "limit": 9999})
    assert vus["limit"] == 20, "une limite non bornee laisse l'appelant dimensionner la charge"
    client.post("/api/rag/search", json={"q": "a", "limit": "pas un nombre"})
    assert vus["limit"] == 8, "une limite illisible retombe au defaut, elle ne fait pas 500"


def test_la_page_porte_bien_le_controle(client):
    """Un endpoint sans surface est un endpoint que personne n'atteint."""
    html = (ROOT / "app" / "web_hub" / "rag_dashboard.html").read_text(encoding="utf-8")
    assert 'id="rq-in"' in html and 'id="rq-go"' in html
    assert "/api/rag/search" in html
