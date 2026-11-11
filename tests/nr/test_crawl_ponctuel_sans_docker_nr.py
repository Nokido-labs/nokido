# -*- coding: utf-8 -*-
"""NR 2026-11-04 (owner : « pourquoi docker est encore allume, il ne tourne pas ! ») -- un appel `crawl` ponctuel
d'AGY sur une page claude.ai privee a reveille Docker (docker.wanted + crawl4ai.wanted) puis echoue en 2 s : Docker
est reste ~30 min (TTL 900 + grace 900) sans servir. Le crawl ne fait que RECLAMER Docker et bascule aussitot sur le
repli urllib : il ne l'attend jamais.

Contrat :
  1. une page derriere une connexion (claude.ai) est refusee AVANT tout reseau et tout reveil (qualite `refus`) ;
  2. `reveiller_docker=False` : crawl4ai absent -> repli, AUCUNE reclamation de Docker ;
  3. defaut inchange (veilles) : crawl4ai absent -> reclamation posee ;
  4. l'outil hub `crawl` (ponctuel) passe reveiller_docker=False.
"""
import ast
import time
from pathlib import Path

import pytest

from nokido_agent.app import forge_crawl_tool as C
from nokido_agent.app import forge_docker_agent as DA

RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture
def isole(monkeypatch):
    appels = []
    monkeypatch.setattr(DA, "demander_crawl4ai", lambda par="?", lancer=True: appels.append((par, lancer)) or True)
    monkeypatch.setattr(C, "_url_interdite", lambda url: "")
    monkeypatch.setattr(C, "_robots_decision", lambda url: {"autorise": True, "motif": ""})
    monkeypatch.setattr(C, "_fulltext_url", lambda url: url)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def pas_de_reseau(*a, **k):
        raise OSError("reseau coupe (test)")
    monkeypatch.setattr(C.urllib.request, "urlopen", pas_de_reseau)
    return appels


def test_page_claude_ai_refusee_sans_reveil(isole):
    r = C.crawl_url_detail("https://claude.ai/artifact/UJyFwyM56n45yfUpmCF9cv")
    assert r["qualite"] == "refus", r
    assert isole == []


def test_ponctuel_ne_reclame_pas_docker(isole):
    C.crawl_url_detail("https://example.org/page", 2, reveiller_docker=False)
    assert isole == []


def test_defaut_veille_reclame_toujours(isole):
    C.crawl_url_detail("https://example.org/page", 2)
    assert isole and isole[0][1] is True


def test_outil_hub_crawl_passe_reveiller_false():
    arbre = ast.parse((RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8"))
    h = next(n for n in ast.walk(arbre) if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_crawl")
    src = ast.unparse(h)
    assert "reveiller_docker=False" in src, src[:400]
