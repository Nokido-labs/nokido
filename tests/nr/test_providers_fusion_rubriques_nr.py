# -*- coding: utf-8 -*-
"""NR — un seul ecran pour les fournisseurs, et des rubriques qui disent quoi faire.

Demande owner du 2026-09-18 : *« il serait bon de fusionner avec /providers et de bien
organiser les rubriques »*.

Le defaut etait une SEPARATION qui coutait a l'usage : `/llm-dashboard` listait ou
s'inscrire sans savoir quels fournisseurs etaient configures, et `/providers` connaissait
l'etat des cles sans dire ou les obtenir. Deux ecrans, un seul sujet, et aucun des deux
ne permettait de decider.

CE QUE CE FICHIER FIGE :

1. Le lien d'inscription est DERIVE de la source unique (`FOURNISSEURS`), jamais invente.
   Un lien fabrique enverrait l'utilisateur sur une adresse plausible et fausse.
2. Ce qui n'a PAS de lien est nomme, au lieu d'etre tu (`sans_lien_d_inscription`).
3. Les exclusions portent leur RAISON : une absence nommee n'est pas un oubli.
4. Les rubriques existent et sont ordonnees par ACTION, pas par ordre alphabetique.

Hermetique : aucun appel au hub, aucun reseau.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pytest.importorskip(
    "fastapi",
    reason="fastapi est une dependance REELLE du portail : son absence est un fait a voir",
)

from app.web_hub import provider_views as PV  # noqa: E402

JS = ROOT / "app" / "web_hub" / "static" / "providers.js"


def test_aucun_lien_sans_source_declaree():
    """MORSURE — un lien invente est pire qu'un lien absent : il a l'air juste.

    DEUX sources legitimes, et seulement deux :
      - `FOURNISSEURS` (catalogue des endpoints /models), dont l'adresse est DERIVEE ;
      - `_INSCRIPTION_HORS_MODELS`, relevee de la page que cette fusion remplace, pour
        les fournisseurs qui n'exposent aucun endpoint /models (Anthropic, OpenAI,
        Gemini, Perplexity). Sans elle, la fusion FAISAIT DISPARAITRE cinq liens que
        l'ancienne page portait -- mesure du 2026-09-18. Fusionner ne doit rien perdre.

    Tout lien hors de ces deux ensembles serait devine.
    """
    catalogue = pytest.importorskip("forge_provider_catalogue")
    du_catalogue = {e[1] for e in catalogue.FOURNISSEURS if len(e) > 1 and e[1]}
    releves = set(PV._INSCRIPTION_HORS_MODELS)
    liens = PV._inscriptions_par_cle()
    assert liens, "aucun lien derive : la fusion ne rapporte rien"
    intrus = sorted(set(liens) - du_catalogue - releves)
    assert not intrus, (
        "liens proposes sans source declaree : %s — ni derives du catalogue, ni releves "
        "de la page remplacee, donc inventes" % intrus
    )


def test_la_fusion_n_a_fait_perdre_aucun_fournisseur_majeur():
    """Contre-epreuve du defaut REEL mesure apres la premiere version de la fusion."""
    liens = PV._inscriptions_par_cle()
    for cle in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "PERPLEXITY_API_KEY"):
        assert cle in liens, (
            "%s n'a plus de lien d'inscription : la fusion a perdu ce que l'ancienne "
            "page portait" % cle
        )


def test_tout_lien_est_une_adresse_https_plausible():
    for cle, url in PV._inscriptions_par_cle().items():
        assert url.startswith("https://"), "%s : %r n'est pas une adresse https" % (cle, url)
        assert " " not in url, "%s : adresse malformee %r" % (cle, url)


def test_les_fournisseurs_locaux_n_ont_pas_de_lien():
    """Proposer une inscription pour un service local serait un contresens."""
    catalogue = pytest.importorskip("forge_provider_catalogue")
    liens = PV._inscriptions_par_cle()
    for entree in catalogue.FOURNISSEURS:
        if len(entree) < 3:
            continue
        env_key, url = entree[1], str(entree[2])
        if "127.0.0.1" in url or "localhost" in url:
            assert env_key not in liens, (
                "%s est servi localement et se voit proposer une inscription" % env_key
            )


def test_les_exclusions_portent_leur_raison():
    """MORSURE — une liste d'exclus sans motif est un tapis, pas une information."""
    assert PV.HORS_CATALOGUE, "aucune exclusion nommee"
    for nom, raison in PV.HORS_CATALOGUE.items():
        assert raison and len(raison) > 8, (
            "%r est exclu sans raison lisible : on cherchera indefiniment pourquoi "
            "il manque" % nom
        )


def test_le_catalogue_illisible_ne_fabrique_pas_de_liens(monkeypatch):
    """ILLISIBLE n'est pas VIDE, et surtout pas « pas de lien » silencieux."""
    import builtins
    vrai_import = builtins.__import__

    def _refuse(nom, *a, **k):
        if nom == "forge_provider_catalogue":
            raise ImportError("temoin")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _refuse)
    restants = PV._inscriptions_par_cle()
    assert set(restants) == set(PV._INSCRIPTION_HORS_MODELS), (
        "catalogue illisible : il doit rester EXACTEMENT les liens releves a la main, "
        "ni plus (rien de devine) ni moins (on ne perd pas ce qu'on sait)"
    )


def test_les_rubriques_existent_et_sont_ordonnees_par_action():
    """Une liste alphabetique de 39 lignes ne dit pas par ou commencer."""
    js = JS.read_text(encoding="utf-8", errors="replace")
    for cle in ("a_configurer", "actif", "local", "perime"):
        assert '"%s"' % cle in js, "rubrique %r absente du rendu" % cle
    # L'ordre COMPTE : ce qui attend un geste vient en premier.
    i_conf = js.index('cle: "a_configurer"')
    i_actif = js.index('cle: "actif"')
    i_perime = js.index('cle: "perime"')
    assert i_conf < i_actif < i_perime, (
        "l'ordre des rubriques n'est plus actionnable : « a configurer » doit venir "
        "avant « operationnels », et les perimes en dernier"
    )


def test_la_page_accueille_les_exclusions_et_le_lien():
    page = PV._PAGE
    assert 'id="hors-catalogue"' in page, "la page n'a pas de place pour les exclusions"
    js = JS.read_text(encoding="utf-8", errors="replace")
    assert "p.inscription" in js, "le lien d'inscription n'est pas rendu sur la ligne"
    assert "sans_lien" in js, "ce qui n'a pas de lien n'est pas dit"


def test_l_ancienne_page_redirige_vers_la_fusion():
    """Sans redirection, les deux ecrans coexisteraient et divergeraient a nouveau."""
    import ast
    src = (ROOT / "app" / "web_hub" / "app.py").read_text(encoding="utf-8", errors="replace")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "llm_dashboard_page":
            corps = ast.unparse(n)
            assert "RedirectResponse" in corps and "/providers" in corps, (
                "/llm-dashboard ne redirige pas vers la page fusionnee"
            )
            return
    pytest.fail("llm_dashboard_page introuvable")
