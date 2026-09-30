# -*- coding: utf-8 -*-
"""NR — le tier 1 Crawl4AI doit pouvoir s'executer, et son contrat etre respecte.

TROIS DEFAUTS MESURES LE 2026-09-05, empiles, qui rendaient la veille AVEUGLE en lui
laissant l'air de tourner — la degradation exacte que `forge_crawl_tool` redoutait
dans son propre commentaire depuis le 2026-08-24.

1. **`import urllib.error` dans le CORPS de `crawl_url_detail`.** En Python, un import
   local rend le nom local a TOUTE la fonction : l'usage du tier 1, ~50 lignes plus
   haut, levait `UnboundLocalError: cannot access local variable 'urllib'` a CHAQUE
   appel. Le crawl basculait donc toujours en repli `urllib`+trafilatura, meme avec le
   conteneur repondant `200` sur `/health`.
2. **Contrat d'API perime.** Le payload etait `{"url": ..., "priority": 10}` ; le
   conteneur 0.8.6 attend `{"urls": [...]}` — une LISTE. Mesure : `HTTP 422
   Unprocessable Entity` sur l'ancienne forme, `200` sur la nouvelle.
3. **`markdown` n'est plus une chaine** mais un objet
   `{raw_markdown, markdown_with_citations, references_markdown, fit_markdown,
   fit_html}`. Un dict est truthy : il passait le test `if md:` et partait vers le
   firewall puis le RAG sous forme de `repr` Python — du texte qui n'en est pas.

Ce garde est STATIQUE et hermetique : il ne lance ni Docker, ni conteneur, ni reseau.
Il tient la PROPRIETE qui a manque, pas la disponibilite du service.
"""
import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app" / "forge_crawl_tool.py"


@pytest.fixture(scope="module")
def arbre():
    return ast.parse(SRC.read_text(encoding="utf-8", errors="replace"))


def _fonction(arbre, nom):
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError("fonction %s introuvable : le NR ne prouve plus rien" % nom)


def test_aucun_import_urllib_dans_le_corps_de_la_fonction(arbre):
    """Le defaut paye : un import local casse l'usage situe PLUS HAUT."""
    fn = _fonction(arbre, "crawl_url_detail")
    for n in ast.walk(fn):
        noms = []
        if isinstance(n, ast.Import):
            noms = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            noms = [n.module or ""]
        for nom in noms:
            assert not str(nom).startswith("urllib"), (
                "`%s` importe dans le corps de crawl_url_detail : cela rend `urllib` "
                "LOCAL a toute la fonction et fait lever UnboundLocalError au tier 1"
                % nom)


def test_urllib_est_importe_au_niveau_module(arbre):
    au_module = set()
    for n in arbre.body:
        if isinstance(n, ast.Import):
            au_module.update(a.name for a in n.names)
    assert any(x.startswith("urllib.request") for x in au_module)
    assert any(x.startswith("urllib.error") for x in au_module), \
        "urllib.error doit vivre au niveau module, pas dans une fonction"


def test_le_payload_respecte_le_contrat_mesure():
    """`{"urls": [...]}` — mesure contre le conteneur 0.8.6 : l'ancienne forme rend 422."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert '"urls": [url]' in src or "'urls': [url]" in src, \
        "payload crawl4ai hors contrat : la forme {'url': ...} rend HTTP 422"


def test_markdown_objet_est_reduit_en_texte():
    """Un dict est truthy : sans reduction il partirait au RAG en repr Python."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert "fit_markdown" in src and "raw_markdown" in src, \
        "la forme OBJET de `markdown` (0.8.6) n'est pas reduite en texte"


def test_le_repli_reste_signale():
    """Une degradation qui se lit comme un succes est pire qu'une panne franche."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert "CRAWL4AI INJOIGNABLE" in src, \
        "le repli sans navigateur doit rester bruyant, jamais silencieux"


def test_le_contrat_mesure_est_documente():
    """Garde du garde : la forme attendue doit rester tracable dans le code."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert "422" in src, "le contrat mesure (422 sur l'ancienne forme) n'est plus consigne"
    json.loads('{"urls": ["https://example.com"]}')
