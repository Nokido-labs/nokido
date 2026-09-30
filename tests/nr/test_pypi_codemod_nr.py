#!/usr/bin/env python3
"""NR — le codemod ne transforme que ce qu'il a PROUVE transformable.

PHASE 5. Ces tests portent sur la DECISION (pure, testable sans LibCST). La
transformation elle-meme est verifiee par la mesure reelle : dry-run, puis
NR + tests + CI apres chaque famille.

LE DEFAUT QUE CES TESTS EMPECHENT. Un codemod qui traite `numpy` comme un module
frere ecrirait `from nokido.app import numpy` — un import qui casse a coup sur, sur
un paquet qui n'a jamais rien demande. Le meme piege a deja fausse deux mesures
aujourd'hui : sans point et hors stdlib ne veut pas dire « du depot ».
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

cm = pytest.importorskip("forge_pypi_codemod")

_CARTE = {"forge_secrets": "app", "ci_local": "tools", "forge_db_path": "app"}


def test_un_module_du_depot_est_transformable():
    ok, motif = cm.decider("forge_secrets", _CARTE)
    assert ok is True
    assert "app" in motif


def test_un_tiers_sans_point_est_REFUSE():
    """LE piege. `numpy` ressemble a un frere : pas de point, pas stdlib."""
    ok, motif = cm.decider("numpy", _CARTE)
    assert ok is False
    assert "hors depot" in motif


def test_la_stdlib_est_refusee():
    ok, motif = cm.decider("json", _CARTE)
    assert ok is False
    assert motif == "stdlib"


def test_un_import_deja_qualifie_est_laisse_tel_quel():
    """`app.forge_secrets` est deja a la cible ; le retoucher serait du bruit."""
    ok, motif = cm.decider("app.forge_secrets", _CARTE)
    assert ok is False
    assert "qualifie" in motif


def test_la_cible_est_la_zone_reelle_du_module():
    """Le namespace se LIT dans le module, il ne se recopie pas : un test qui
    duplique la source de verite mesure sa propre copie."""
    assert cm.cible_namespace("forge_secrets", _CARTE) == f"{cm.NAMESPACE}.app"
    assert cm.cible_namespace("ci_local", _CARTE) == f"{cm.NAMESPACE}.tools"
    assert cm.cible_namespace("inconnu", _CARTE) is None


def test_le_namespace_du_codemod_egale_celui_du_contrat():
    """Deux sources de verite qui divergent produiraient des imports vers un
    paquet que la wheel ne contient pas — l'erreur n'apparaitrait qu'a
    l'installation."""
    import forge_pypi_contrat as ct
    assert cm.NAMESPACE == ct.NAMESPACE_CIBLE


def test_la_carte_reelle_a_un_denominateur_non_vide():
    """Une carte vide ne transformerait RIEN tout en paraissant prudente — c'est
    la panne muette que la regle owner sur le denominateur interdit."""
    carte = cm.carte_modules()
    assert len(carte) > 500
    assert carte.get("ci_local") == "tools"


def test_un_module_en_sous_dossier_n_est_pas_dans_la_carte():
    """Il n'est pas atteignable a plat, donc il n'est pas concerne : l'ajouter
    ferait croire a une dette plus large qu'elle n'est."""
    carte = cm.carte_modules()
    for nom, zone in carte.items():
        assert (ROOT / zone / f"{nom}.py").exists(), f"{nom} n'est pas a plat dans {zone}"


# ------------------------------------------- REDIRECTION DES sys.path
#
# Mesure du 2026-09-10 : dans le contexte reel d'un script (`sys.path[0] = tools/`),
# la RACINE n'est pas dans `sys.path` — donc `nokido_agent` est INTROUVABLE. Migrer
# les imports sans rien d'autre casserait tout script lance par chemin.
#
# La reponse n'est PAS de supprimer les `sys.path` (regle owner : « aucune
# transformation automatique ne supprime un sys.path tant qu'on n'a pas prouve
# pourquoi il etait la »), mais de les REDIRIGER : le chemin servait a rendre
# `app/` importable ; la racine rend `nokido_agent.app` importable. Meme role,
# une cran plus haut.


def test_une_cible_de_zone_est_redirigee_vers_la_racine():
    assert cm.rediriger_cible("ROOT/app") == "ROOT"
    assert cm.rediriger_cible("ROOT/tools") == "ROOT"
    assert cm.rediriger_cible("FICHIER/app") == "FICHIER"


def test_une_cible_qui_n_est_pas_une_zone_n_est_PAS_touchee():
    """Un `sys.path` vers autre chose qu'une zone du depot garde son role : le
    rediriger casserait ce qu'il servait, sans rien apporter."""
    for cible in ("ROOT/vendor", "/opt/greffons", "ROOT", "UNKNOWN", "ROOT/app/sous"):
        assert cm.rediriger_cible(cible) is None, f"{cible} ne doit pas etre redirige"


def test_la_redirection_refuse_une_cible_non_reduite():
    """`CIBLE_NON_REDUITE` reste A_INSTRUIRE : on ne redirige pas ce qu'on n'a pas
    su lire — ce serait deviner."""
    assert cm.rediriger_cible("UNKNOWN") is None
    assert cm.rediriger_cible("") is None


def test_les_cibles_d_une_famille_sont_non_vides_et_bornees():
    carte = cm.carte_modules()
    app = cm.fichiers_famille("app", carte)
    tools = cm.fichiers_famille("tools", carte)
    assert len(app) > 100 and len(tools) > 100
    assert all("\\app\\" in f or "/app/" in f for f in app)
    assert not any("_attic" in Path(f).parts for f in app)
