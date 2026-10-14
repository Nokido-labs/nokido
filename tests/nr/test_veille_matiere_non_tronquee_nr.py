# -*- coding: utf-8 -*-
"""NR -- la matiere d'une veille n'est plus tronquee en silence (owner 2026-10-13 : « toute la substantifique
moelle, sans limite de caracteres non encore corrigee »).

Mesure du 13/10, avant la veille sur kaonomi-net/mari : pour un depot GitHub, la matiere ingeree EST la
description + le README, coupee a 4000 caracteres sans un mot (le README de mari en depasse 6000 rien que dans
son debut) ; les resumes d'articles (OpenAlex, arXiv) etaient coupes a 1500. L'ingestion decoupe deja en morceaux
(MarkdownChunker) et son seul plafond (400 morceaux) se DIT dans le journal : couper avant ne servait qu'a perdre.
"""
from __future__ import annotations

import inspect
import json

import nokido_agent.app.forge_watch_agent as W


def test_le_readme_entier_d_un_depot_est_la_matiere(monkeypatch):
    readme = ("# MARI\n\n" + "Doors, Signals, Triggers, Blackboard. " * 300).encode("utf-8")
    assert len(readme) > 10000

    def faux_gh_get(path, accept="application/vnd.github+json"):
        if path.startswith("/search/repositories"):
            return json.dumps({"items": [{"full_name": "kaonomi-net/mari", "description": "distributed AI and MAS",
                                          "html_url": "https://github.com/kaonomi-net/mari"}]}).encode("utf-8")
        return readme

    monkeypatch.setattr(W, "_gh_get", faux_gh_get)
    res = W._github_search("mari orleans multi-agent", n=1)
    assert len(res) == 1
    contenu = res[0]["content"]
    assert len(contenu) >= len(readme), "le README a ete tronque (%d < %d)" % (len(contenu), len(readme))
    assert "distributed AI and MAS\n\n# MARI" in contenu, "separateur : vrai saut de ligne, pas un antislash-n"


def test_les_resumes_d_articles_ne_sont_plus_coupes():
    for fonction in (W._openalex_search, W._arxiv_search):
        src = inspect.getsource(fonction)
        assert "[:1500]" not in src, "%s coupe encore le resume a 1500 caracteres" % fonction.__name__
