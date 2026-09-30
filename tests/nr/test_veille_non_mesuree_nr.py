# -*- coding: utf-8 -*-
"""Une veille qui n'a pas pu regarder ne rend pas « rien trouve ».

Mesure 2026-08-30 : `_call_search` rendait `[]` aussi bien quand les sources
avaient repondu sans resultat que quand AUCUNE n'avait pu etre interrogee. Les
deux donnaient le statut `degraded`, que `execute_pending` accepte comme
« pret a continuer » -- la chaine allait donc jusqu'a StoreAgent et le job se
lisait « termine » alors que la veille etait aveugle.

Ces deux tests fixent la frontiere, et ils sont HERMETIQUES : aucune source
reelle n'est jointe, tout passe par un faux `forge_watch_agent`.
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.38)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _faux_watch_agent(searxng, academic, ensure=False):
    """Remplace le module que `_call_search` importe DANS la fonction."""
    mod = types.ModuleType("forge_watch_agent")
    mod._ensure_searxng = lambda: ensure
    mod._searxng = searxng
    mod._academic_search = academic
    return mod


def _executor(tmp_path):
    import forge_chain_executor as ce

    return ce.ChainExecutor(db_path=tmp_path / "chain.db")


def test_aucune_source_joignable_leve_au_lieu_de_rendre_un_vide(monkeypatch, tmp_path):
    """Toutes les interrogations echouent : 0 resultat ne dit RIEN du sujet.

    On leve, ce qui remet le node en `retry_pending` puis `failed` via la
    politique de retry deja en place -- au lieu de laisser la chaine conclure.
    """
    def _muet(_kw, _n):
        raise OSError("moteur muet")

    monkeypatch.setitem(sys.modules, "forge_watch_agent",
                        _faux_watch_agent(_muet, _muet))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_watch_agent",
                        _faux_watch_agent(_muet, _muet))
    ex = _executor(tmp_path)
    with pytest.raises(RuntimeError, match="NON MESUREE"):
        asyncio.run(ex._call_search({"keywords": ["un sujet quelconque"]}))


def test_vide_apres_reponse_d_une_source_reste_un_degrade_assume(monkeypatch, tmp_path):
    """Les sources REPONDENT et ne trouvent rien : c'est un resultat.

    La chaine doit continuer (`degraded`), sinon une veille sur un sujet sans
    litterature serait indistinguable d'une panne.
    """
    monkeypatch.setitem(sys.modules, "forge_watch_agent",
                        _faux_watch_agent(lambda _k, _n: [], lambda _k, _n: []))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_watch_agent",
                        _faux_watch_agent(lambda _k, _n: [], lambda _k, _n: []))
    ex = _executor(tmp_path)
    assert asyncio.run(ex._call_search({"keywords": ["sujet sans litterature"]})) == []


def test_une_seule_source_survivante_suffit_a_ne_pas_lever(monkeypatch, tmp_path):
    """SearXNG a terre mais l'academique repond : la veille garde sa couverture.

    C'est le cas que « bloquer des que SearXNG est indisponible » aurait casse :
    `_call_search` a TROIS sources et l'academique ne depend pas de Docker.
    """
    def _muet(_kw, _n):
        raise OSError("searxng down")

    def _academique(_kw, _n):
        return [{"title": "t", "url": "https://arxiv.org/abs/1", "content": "c",
                 "engine": "arxiv_direct"}]

    monkeypatch.setitem(sys.modules, "forge_watch_agent",
                        _faux_watch_agent(_muet, _academique))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_watch_agent",
                        _faux_watch_agent(_muet, _academique))
    ex = _executor(tmp_path)
    res = asyncio.run(ex._call_search({"keywords": ["sujet couvert"]}))
    assert len(res) == 1 and res[0]["engine"] == "arxiv_direct"
