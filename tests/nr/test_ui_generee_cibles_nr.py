"""Non-regression : une UI GENEREE ne sert que des routes qui existent.

Mesure du 2026-08-26, en production. Le recensement du cablage (mode navigateur, session
owner) a trouve un lien mort sur `/ui/auto/services-status` : `<a href="/alerts">`, 404.
Ce widget n'est pas ecrit a la main — il est produit par un LLM (`generate_ui`, appele
par la route), a qui le prompt demande « ajoute alerte rouge ». Le modele a INVENTE la
route, et elle etait servie telle quelle.

`_sanitize_html` protegeait deja du HTML dangereux (tags et attributs autorises). Rien ne
protegeait de la route imaginaire : une sortie de modele traitee comme un fait, la faute
que ce depot paie ailleurs sous d'autres formes.

Le remede ne SUPPRIME pas l'element : il lui retire sa cible et marque pourquoi. Un
bouton mort et visible vaut mieux qu'un bouton mort et silencieux.
"""

from __future__ import annotations

import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from app.web_hub.ui_generate import (  # noqa: E402
    _cible_connue,
    neutraliser_cibles_inconnues,
)

CONNUES = {"/dashboard", "/forge/feed", "/api/vital/{name}", "/graph", "/"}


# ------------------------------------------------------- reconnaissance de cible

def test_une_route_declaree_est_reconnue():
    assert _cible_connue("/dashboard", CONNUES) is True
    assert _cible_connue("/dashboard/", CONNUES) is True, "le slash final ne change rien"
    assert _cible_connue("/forge/feed?x=1", CONNUES) is True, "la query non plus"


def test_une_route_parametree_accepte_sa_valeur():
    assert _cible_connue("/api/vital/ram", CONNUES) is True
    assert _cible_connue("/api/vital/ram/extra", CONNUES) is False


def test_un_sous_chemin_de_montage_est_accepte():
    """`/graph` est un montage : tout ce qui vit dessous est servi par le proxy."""
    assert _cible_connue("/graph/explorer", CONNUES) is True


def test_une_route_inventee_est_refusee():
    assert _cible_connue("/alerts", CONNUES) is False


# ------------------------------------------------------------- neutralisation

def test_le_cas_REEL_alerts_est_neutralise_sans_effacer_le_texte():
    html = '<div><a href="/alerts" class="red">3 services critiques</a></div>'
    out, refusees = neutraliser_cibles_inconnues(html, CONNUES)
    assert refusees == ["/alerts"]
    assert 'href="/alerts"' not in out, "la cible morte ne doit plus etre servie"
    assert 'data-cible-refusee="/alerts"' in out and "neutralisee" in out
    assert "3 services critiques" in out, "le texte reste lisible"


def test_les_cibles_htmx_sont_couvertes_aussi():
    html = '<button hx-post="/api/inventee">Go</button><button hx-get="/dashboard">OK</button>'
    out, refusees = neutraliser_cibles_inconnues(html, CONNUES)
    assert refusees == ["/api/inventee"]
    assert 'hx-get="/dashboard"' in out, "une cible valide n'est jamais touchee"


def test_une_cible_externe_nest_pas_du_ressort_de_cette_porte():
    """Le perimetre est l'application : un lien vers l'exterieur se juge ailleurs."""
    html = '<a href="https://exemple.test/x">doc</a>'
    out, refusees = neutraliser_cibles_inconnues(html, CONNUES)
    assert refusees == [] and out == html


def test_application_non_chargee_ne_vide_pas_lUI():
    """Troisieme etat. Sans routes lisibles, tout refuser viderait le widget au lieu
    de le proteger — « je n'ai pas pu regarder » n'est pas « rien n'existe »."""
    html = '<a href="/alerts">x</a>'
    out, refusees = neutraliser_cibles_inconnues(html, None)
    assert out == html and refusees is None


def test_rien_a_redire_se_distingue_de_non_verifie():
    out, refusees = neutraliser_cibles_inconnues('<a href="/dashboard">ok</a>', CONNUES)
    assert refusees == [], "liste vide = verifie et propre"
    assert refusees is not None, "et surtout pas None, qui veut dire non verifie"
    assert "/dashboard" in out
