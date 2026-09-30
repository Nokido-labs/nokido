#!/usr/bin/env python3
"""NR — « la wheel se construit » n'est pas une preuve.

Une wheel se construit parfaitement en oubliant la moitie de ses paquets : rien
n'echoue, l'artefact existe, et le defaut se revele a l'import, chez quelqu'un
d'autre. C'est la forme exacte du defaut que P4.2a a paye — un controle satisfait
pour une promesse non tenue.

Ces tests portent sur le JUGE (`verdict_wheel`), pas sur le build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

w = pytest.importorskip("forge_pypi_wheel")

_DECLARES = ["nokido", "nokido.app", "nokido.tools"]
_PRESENTS = {"nokido", "nokido.app", "nokido.tools"}
_SCRIPTS = {"nokido-hub": "nokido.tools.nokido_hub:main"}
_ENTRY = "[console_scripts]\nnokido-hub = nokido.tools.nokido_hub:main\n"
_NOMS = ["nokido/__init__.py", "nokido/app/__init__.py", "nokido/tools/__init__.py"]


def test_une_wheel_complete_est_certifiee():
    verdict, ecarts = w.verdict_wheel(_DECLARES, _PRESENTS, _SCRIPTS, _ENTRY, _NOMS)
    assert verdict == "CERTIFIE"
    assert ecarts == []


def test_un_paquet_declare_absent_est_un_FAIL():
    """Le cas silencieux : la wheel existe, il lui manque un paquet."""
    verdict, ecarts = w.verdict_wheel(_DECLARES, {"nokido"}, _SCRIPTS, _ENTRY, _NOMS)
    assert verdict == "FAIL"
    assert any("ABSENTS" in e for e in ecarts)


def test_un_paquet_A_PLAT_dans_la_wheel_est_un_FAIL():
    """`app` et `tools` en premier niveau ECRASERAIENT les modules du meme nom
    chez l'utilisateur — un paquet nomme `tools` sur PyPI est un accident qui
    attend. C'est precisement ce que le namespace corrige."""
    verdict, ecarts = w.verdict_wheel(
        _DECLARES, _PRESENTS | {"tools", "app.rag"}, _SCRIPTS, _ENTRY, _NOMS)
    assert verdict == "FAIL"
    assert any("a plat" in e for e in ecarts)


def test_un_entry_point_absent_des_metadata_est_un_FAIL():
    verdict, ecarts = w.verdict_wheel(_DECLARES, _PRESENTS, _SCRIPTS, "[console_scripts]\n", _NOMS)
    assert verdict == "FAIL"
    assert any("entry point absent" in e for e in ecarts)


def test_une_fuite_de_fichier_hors_perimetre_est_un_FAIL():
    """Une distribution publique qui embarque `Nokido.env` ou `RAG/` publie des
    secrets et des donnees. Le refus est structurel, pas un rappel."""
    verdict, ecarts = w.verdict_wheel(
        _DECLARES, _PRESENTS, _SCRIPTS, _ENTRY, _NOMS + ["nokido/Nokido.env"])
    assert verdict == "FAIL"
    assert any("hors perimetre" in e for e in ecarts)


def test_une_archive_vide_est_NON_CERTIFIANTE_pas_saine():
    """Regle owner : un artefact qu'on n'a pas su ouvrir n'est pas un artefact
    sain. Denominateur vide = NON_CERTIFIANT, jamais CERTIFIE."""
    verdict, ecarts = w.verdict_wheel(_DECLARES, set(), _SCRIPTS, _ENTRY, [])
    assert verdict == "NON_CERTIFIANT"


def test_aucun_paquet_declare_est_NON_CERTIFIANT():
    """Sans declaration, toute wheel passerait : le juge n'aurait rien a comparer."""
    verdict, ecarts = w.verdict_wheel([], _PRESENTS, _SCRIPTS, _ENTRY, _NOMS)
    assert verdict == "NON_CERTIFIANT"
    assert any("denominateur vide" in e for e in ecarts)


def test_la_liste_des_interdits_est_non_vide():
    assert len(w.INTERDITS) >= 5
    for attendu in ("sandbox", "RAG", "Nokido.env"):
        assert attendu in w.INTERDITS


def test_un_module_dont_le_NOM_contient_secrets_n_est_PAS_une_fuite():
    """FAUX POSITIF MESURE le 2026-09-10 sur la premiere wheel reelle.

    `INTERDITS` contenait la sous-chaine « secrets » et accusait
    `nokido/app/forge_secrets.py` — le module CIBLE de l'entry point
    `nokido-secrets`. L'exclure aurait casse la distribution pour proteger un
    fichier qui ne contient aucun secret.

    5e occurrence du motif dans la journee (prose du README, `numpy`, `_attic`,
    `chantier_pypi`, et ceci) : une MENTION dans un nom n'est pas une STRUCTURE.
    """
    legitimes = [
        "nokido/app/forge_secrets.py",
        "nokido/tools/migrate_secrets_to_wcm.py",
        "nokido/tools/forge_scrub_secrets_phase1.py",
    ]
    assert w.fuites(legitimes) == []


def test_les_vraies_fuites_sont_toujours_attrapees():
    """Contre-epreuve de la correction : en elargissant la tolerance, on ne doit
    pas avoir ouvert la porte."""
    dangereux = [
        "nokido/Nokido.env",              # nom exact
        "nokido/app/.env",                # nom exact
        "sandbox/x.py",                   # segment de dossier
        "nokido/tools/tests/test_x.py",   # segment de dossier
        "nokido/app/cle.pem",             # extension
        "nokido/RAG/embeddings.db",       # les deux
    ]
    attrapes = w.fuites(dangereux)
    assert len(attrapes) == len(dangereux), f"laisse passer : {set(dangereux) - set(attrapes)}"


def test_la_source_de_build_est_hors_du_depot():
    """La racine du depot est fermee en ecriture au compte sandbox, et le build y
    ecrirait son `.egg-info` (mesure 2026-09-10). La source exportee doit vivre
    ailleurs — et ce qui n'est pas copie ne peut pas fuir dans l'artefact."""
    import forge_pypi_contrat as ct
    cible = str(w.SRC_BUILD).replace("\\", "/")
    assert "Script python IA" not in cible
    # Le namespace se LIT dans le contrat : le recopier ici a fait echouer ce
    # test au changement de namespace alors que le build etait juste.
    assert set(w.SOURCES_DOSSIERS) == {ct.NAMESPACE_CIBLE, "app", "tools"}
