"""NR : repli web gratuit Ollama Cloud quand SearXNG ne trouve rien (decision owner 26/10, « pas d'API payante »).

Mesure 26/10 : moteurs generalistes de SearXNG suspendus (brave 429, duckduckgo/startpage CAPTCHA), aucun
CAPTCHA contourne (politique owner 18/10). La requete part chez Ollama SEULEMENT apres le pare-feu semantique
(regle d'or 4) ; un refus ou une panne est NOMME, jamais lu comme « aucun resultat ».
"""
import asyncio
import json
import sys
import types
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_web_fallback as wf  # noqa: E402


class _Rep:
    def __init__(self, corps):
        self._c = corps

    def read(self):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _poser(monkeypatch, ok=True, cle="cle-factice"):
    monkeypatch.setenv("LAFORGE_WEB_OLLAMA", "1")  # le conftest NR le coupe par defaut
    monkeypatch.setattr(wf, "_searxng_diag", lambda q, n, moteurs: ([], "searxng: moteurs suspendus"))
    monkeypatch.setattr(wf, "_cle_ollama", lambda: cle)
    monkeypatch.setattr(wf, "_pre_flight", lambda q: (ok, "" if ok else "DLP : chemin Windows"))
    envoyes = []

    def faux_urlopen(req, timeout=None):
        envoyes.append(json.loads(req.data))
        return _Rep(json.dumps({"results": [{"title": "T", "url": "https://x.org", "content": "C"}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", faux_urlopen)
    return envoyes


def test_repli_ollama_quand_searxng_ne_trouve_rien(monkeypatch):
    envoyes = _poser(monkeypatch)
    d = asyncio.run(wf.web_search_diag("python asyncio", max_results=3))
    assert d["source"] == "ollama_cloud" and d["results"][0]["url"] == "https://x.org"
    assert envoyes == [{"query": "python asyncio", "max_results": 3}]
    assert any("searxng" in e for e in d["erreurs"])


def test_le_pare_feu_retient_la_requete_et_le_dit(monkeypatch):
    envoyes = _poser(monkeypatch, ok=False)
    d = asyncio.run(wf.web_search_diag("C:\\Users\\x\\secret", max_results=3))
    assert envoyes == [] and d["results"] == []
    assert any("pare-feu" in e for e in d["erreurs"])


def test_interrupteur_coupe_le_repli(monkeypatch):
    envoyes = _poser(monkeypatch)
    monkeypatch.setenv("LAFORGE_WEB_OLLAMA", "0")
    d = asyncio.run(wf.web_search_diag("python", max_results=3))
    assert envoyes == [] and d["source"] is None


def test_sans_cle_au_coffre_le_dit(monkeypatch):
    envoyes = _poser(monkeypatch, cle="")
    d = asyncio.run(wf.web_search_diag("python", max_results=3))
    assert envoyes == [] and any("OLLAMA_API_KEY" in e for e in d["erreurs"])


def test_un_429_est_nomme(monkeypatch):
    import urllib.error

    _poser(monkeypatch)

    def refus(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", refus)
    d = asyncio.run(wf.web_search_diag("python", max_results=3))
    assert d["results"] == [] and any("429" in e for e in d["erreurs"])
