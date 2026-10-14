"""NR -- la veille ne devient plus aveugle quand les moteurs web renvoient des CAPTCHA (2026-10-13).

Veille Hamilton : brave, duckduckgo, startpage, karmasearch en circuit ouvert ; la requete repartait quand meme vers
eux (categories=general), 0 resultat, circuit GLOBAL ouvert -> 29/29 resultats OpenAlex hors sujet. Et la chaine
n'interrogeait jamais GitHub ni les URL donnees dans le theme, que l'autre version de l'etape connaissait.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import types

import nokido_agent.app.forge_chain_executor as CE
import nokido_agent.app.forge_watch_agent as W


class _Rep(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _searxng_servi(monkeypatch, corps, moteurs, cb=None):
    urls = []

    def _urlopen(req, timeout=None):
        urls.append(getattr(req, "full_url", str(req)))
        return _Rep(json.dumps(corps).encode())

    monkeypatch.setattr(W.urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(W, "_moteurs_searxng", lambda: list(moteurs))
    monkeypatch.setattr(W, "_ENGINE_CB", dict(cb or {}))
    monkeypatch.setattr(W, "_academic_search", lambda q, n=8: [])
    return urls


def test_un_moteur_en_circuit_ouvert_est_ecarte_de_la_requete(monkeypatch):
    ouvert = {"searxng:brave": {"fails": 3, "opened_until_ts": time.time() + 600}}
    urls = _searxng_servi(monkeypatch, {"results": [{"url": "https://example.org/apollo", "title": "AGC",
                                                     "content": "executive"}], "unresponsive_engines": []},
                          ["brave", "github", "wikipedia"], ouvert)
    res = W._searxng("Apollo Guidance Computer", 4)
    assert res, "les moteurs encore fermes doivent continuer de servir"
    assert "engines=github%2Cwikipedia" in urls[0] and "brave" not in urls[0]


def test_config_illisible_retombe_sur_categories_general(monkeypatch):
    urls = _searxng_servi(monkeypatch, {"results": [], "unresponsive_engines": []}, [])
    W._searxng("Apollo Guidance Computer", 4)
    assert "categories=general" in urls[0]


def test_zero_resultat_de_moteurs_qui_repondent_n_ouvre_pas_le_circuit_global(monkeypatch):
    _searxng_servi(monkeypatch, {"results": [], "unresponsive_engines": []}, ["github", "wikipedia"])
    for _ in range(6):
        W._searxng("requete tres pointue", 4)
    assert not W._engine_open("searxng"), "le web n'a rien n'est pas SearXNG en panne"


def test_zero_resultat_tous_moteurs_muets_compte_une_panne(monkeypatch):
    _searxng_servi(monkeypatch, {"results": [], "unresponsive_engines": [["github", "timeout"],
                                                                        ["wikipedia", "CAPTCHA"]]},
                   ["github", "wikipedia"])
    W._searxng("Apollo", 4)
    assert W._ENGINE_CB["searxng"]["fails"] == 1


def test_les_moteurs_viennent_de_config_actifs_et_dans_les_categories(monkeypatch):
    conf = {"engines": [{"name": "brave", "enabled": True, "categories": ["general"]},
                        {"name": "github", "enabled": True, "categories": ["it", "repos"]},
                        {"name": "deezer", "enabled": True, "categories": ["music"]},
                        {"name": "bing", "enabled": False, "categories": ["general"]}]}
    monkeypatch.setattr(W.urllib.request, "urlopen", lambda req, timeout=None: _Rep(json.dumps(conf).encode()))
    monkeypatch.setattr(W, "_MOTEURS_SEARXNG", {"ts": 0.0, "noms": []})
    assert W._moteurs_searxng() == ["brave", "github"]


def _faux_module(monkeypatch, nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, "nokido_agent.app." + nom, mod)
    return mod


def test_la_chaine_interroge_github_et_met_les_url_du_theme_en_tete(monkeypatch):
    appels = []

    def _gh(q, n=4, leve=False):
        appels.append(leve)
        return [{"title": "o/r", "url": "https://github.com/o/r", "content": "readme", "engine": "github_api"}]

    _faux_module(monkeypatch, "forge_watch_agent", _ensure_searxng=lambda: True, _searxng=lambda q, n=8: [],
                 _academic_search=lambda q, n=8: [], _github_search=_gh)
    ctx = {"theme": "Hamilton AGC https://en.wikipedia.org/wiki/Apollo_Guidance_Computer",
           "keywords_verified": ["hamilton agc"]}
    res = asyncio.run(CE.ChainExecutor._call_search(object.__new__(CE.ChainExecutor), ctx))
    assert res[0]["url"] == "https://en.wikipedia.org/wiki/Apollo_Guidance_Computer"
    assert res[0]["engine"] == "theme_url"
    assert any(r["url"] == "https://github.com/o/r" for r in res)
    assert appels == [True], "GitHub doit lever sur API injoignable (non-mesure), pas rendre []"


def test_une_cible_du_theme_non_crawlee_n_est_pas_ingeree_avec_son_texte_provisoire(monkeypatch):
    _faux_module(monkeypatch, "forge_crawl_tool",
                 crawl_url_detail=lambda url, t=15: {"text": "", "backend": "aucun", "qualite": "vide"})
    _faux_module(monkeypatch, "forge_watch_agent", _is_binary_payload=lambda md: False,
                 _is_boilerplate=lambda md: False)
    ex = object.__new__(CE.ChainExecutor)
    ex.update_context = lambda *a, **k: None
    refined = [{"url": "https://x.org/y", "content": "cible donnee dans le theme: AGC", "engine": "theme_url"},
               {"url": "https://a.org/b", "content": "abstract", "engine": "openalex"}]
    out = asyncio.run(CE.ChainExecutor._call_crawl(ex, {"chain_id": "wj_t"}, {"refined": refined}))
    assert out[0]["content"] == "", "le texte provisoire ne doit jamais etre ingere a la place de la page"
    assert out[1]["content"] == "abstract"


def test_refine_garde_les_cibles_donnees_devant_des_articles_mieux_cotes(monkeypatch):
    # Chaine B du 13/10 : cinq fichiers AGC NOMMES evinces par des articles arxiv (confiance +2.5 sur un theme
    # « academique »), ensuite rejetes au crawl -- un seul fichier sur cinq ingere.
    monkeypatch.setattr(W, "_llm_local", lambda prompt, *a, **k: "ERR:no_llm")
    theme = "Apollo Guidance Computer Luminary099 Executive Waitlist restart"
    base = "https://raw.githubusercontent.com/x/Apollo-11/master/Luminary099/F%d.agc"
    cibles = [{"title": base % i, "url": base % i, "content": "cible donnee dans le theme: " + theme,
               "engine": "theme_url"} for i in range(5)]
    articles = [{"title": "Apollo Guidance Computer executive waitlist restart scheduling 2026 %d" % i,
                 "url": "https://arxiv.org/abs/2601.0000%d" % i,
                 "content": "Apollo Guidance Computer Executive Waitlist restart", "engine": "arxiv"} for i in range(6)]
    out = asyncio.run(CE.ChainExecutor._call_llm_step(object.__new__(CE.ChainExecutor), {"id": "n"}, "refine",
                                                      {"theme": theme, "search_results": articles + cibles}))
    assert [r["url"] for r in out] == [c["url"] for c in cibles]
