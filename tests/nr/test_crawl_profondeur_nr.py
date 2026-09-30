# -*- coding: utf-8 -*-
"""La veille doit savoir par quel chemin son texte est arrive.

Mesure 2026-08-30 : `crawl_url` ne rendait qu'une chaine, et le ChainExecutor
posait `crawled = True` aussi bien pour un crawl navigateur que pour un repli
urllib. Or sur une page rendue en JavaScript, urllib rend le chrome de
navigation la ou Crawl4AI rend la page entiere : « profond » et « degrade »
etaient indiscernables.

Ces tests fixent la frontiere sans joindre aucun reseau.
"""
import asyncio
import email.message
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.74)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_429_repete_rend_une_erreur_et_jamais_None(monkeypatch):
    """Trois 429 d'affilee tombaient hors de la boucle SANS return.

    La fonction rendait alors None en se declarant `-> str` : un appelant qui
    teste `md.startswith("ERR:")` levait un AttributeError, donc une panne de
    crawl se presentait comme un bug de l'appelant -- au moment precis ou la
    source nous limite.
    """
    import forge_crawl_tool as fct

    def _429(*_a, **_kw):
        raise urllib.error.HTTPError("http://exemple.test/p", 429, "Too Many Requests",
                                     email.message.Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", _429)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    out = fct.crawl_url("http://exemple.test/p")
    assert isinstance(out, str), "crawl_url doit TOUJOURS rendre une chaine"
    assert out.startswith("ERR:") and "429" in out

    det = fct.crawl_url_detail("http://exemple.test/p")
    assert det["backend"] == "urllib" and det["qualite"] == "erreur"


def _faux_watch_agent(monkeypatch):
    mod = types.ModuleType("forge_watch_agent")
    mod._is_binary_payload = lambda _t: False
    mod._is_boilerplate = lambda _t: False
    monkeypatch.setitem(sys.modules, "forge_watch_agent", mod)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_watch_agent", mod)


def test_le_node_enregistre_le_backend_et_distingue_profond_de_degrade(monkeypatch, tmp_path):
    """Deux resultats, deux chemins : le node doit les distinguer, pas les fondre."""
    import forge_chain_executor as ce
    import forge_crawl_tool as fct

    _faux_watch_agent(monkeypatch)
    par_url = {
        "http://profond.test": {"text": "P" * 900, "backend": "crawl4ai",
                                "qualite": "full", "chars": 900, "variante": "origine"},
        "http://plat.test": {"text": "D" * 900, "backend": "urllib",
                             "qualite": "degraded", "chars": 900, "variante": "origine"},
    }
    monkeypatch.setattr(fct, "crawl_url_detail",
                        lambda url, _t=15: par_url[url], raising=False)

    ex = ce.ChainExecutor(db_path=tmp_path / "chain.db")
    refined = [{"url": u, "content": "snippet"} for u in par_url]
    out = asyncio.run(ex._call_crawl({"id": "n", "chain_id": "c"}, {"refined": refined}))

    par = {r["url"]: r for r in out}
    assert par["http://profond.test"]["crawl_backend"] == "crawl4ai"
    assert par["http://profond.test"]["crawl_quality"] == "full"
    assert par["http://plat.test"]["crawl_backend"] == "urllib"
    assert par["http://plat.test"]["crawl_quality"] == "degraded"
    # Les deux ont bien du contenu : c'est justement pour ca que `crawled` seul
    # ne suffisait pas a les distinguer.
    assert all(r.get("crawled") for r in out)


def test_un_contenu_rejete_par_le_filtre_n_est_pas_une_panne_du_crawler(monkeypatch, tmp_path):
    """`rejete` doit se distinguer de `degraded` : le garde a protege, il n'a pas echoue."""
    import forge_chain_executor as ce
    import forge_crawl_tool as fct

    mod = types.ModuleType("forge_watch_agent")
    mod._is_binary_payload = lambda _t: False
    mod._is_boilerplate = lambda _t: True          # tout est du chrome
    monkeypatch.setitem(sys.modules, "forge_watch_agent", mod)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_watch_agent", mod)
    monkeypatch.setattr(fct, "crawl_url_detail",
                        lambda _u, _t=15: {"text": "C" * 900, "backend": "urllib",
                                           "qualite": "degraded", "chars": 900,
                                           "variante": "origine"}, raising=False)

    ex = ce.ChainExecutor(db_path=tmp_path / "chain.db")
    out = asyncio.run(ex._call_crawl({"id": "n", "chain_id": "c"},
                                     {"refined": [{"url": "http://x.test", "content": "snip"}]}))
    assert out[0]["crawl_quality"] == "rejete"
    assert not out[0].get("crawled")
    assert out[0]["content"] == "snip", "le snippet d'origine doit etre conserve"
