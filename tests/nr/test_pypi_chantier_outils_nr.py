#!/usr/bin/env python3
"""NR — l'outillage de migration mesure sa propre limite avant de servir.

PHASE 2. Ces tests portent sur les deux fonctions qui DECIDENT : classer un echec
de parse, et trancher le verdict du corpus. Le reste du module est de
l'orchestration de sous-processus, verifiee par la mesure reelle.

CE QU'ILS GARDENT. Un outil de refactoring qui n'analyse pas 100 % du corpus ne
peut pas etre lance en codemod global — et un corpus vu a zero fichier n'est pas
« sans probleme », c'est une absence de mesure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

outils = pytest.importorskip("forge_pypi_chantier_outils")


def test_un_echec_de_grammaire_est_distingue_d_une_syntaxe_refusee():
    """Ne PAS confondre « LibCST ne connait pas cette forme » et « ce fichier est
    casse ». Le premier est un defaut de l'OUTIL, le second du CODE — et ils
    n'appellent pas le meme geste."""
    assert outils.classer_echec_parse(
        "ParserSyntaxError: unsupported version 3.14"
    ) == "GRAMMAIRE_NON_SUPPORTEE"
    assert outils.classer_echec_parse("ParserSyntaxError: unexpected token") == "SYNTAXE_REFUSEE"
    assert outils.classer_echec_parse("UnicodeDecodeError: codec") == "ENCODAGE"
    assert outils.classer_echec_parse("bruit inconnu") == "INDETERMINE"


def test_un_corpus_vu_a_zero_fichier_est_non_certifiant():
    """LA regle owner : denominateur vide = NON-CERTIFIANT, pas « rien a signaler ».
    Sans ce garde, un scan qui n'a rien lu passerait pour un scan sans probleme."""
    verdict, motif = outils.verdict_corpus(vus=0, parses=0, echecs=0)
    assert verdict == "NON_CERTIFIANT"
    assert "denominateur vide" in motif


def test_une_ventilation_qui_ne_boucle_pas_est_non_certifiante():
    """Somme de controle : si parses + echecs != vus, des fichiers ont disparu du
    compte. Un total qui ne boucle pas cache un cas non classe."""
    verdict, _ = outils.verdict_corpus(vus=100, parses=90, echecs=5)
    assert verdict == "NON_CERTIFIANT"


def test_des_echecs_reels_donnent_FAIL_pas_NON_CERTIFIANT():
    """Symetrie indispensable : une mesure qui a REELLEMENT echoue n'est pas une
    mesure manquante. Les confondre effacerait un defaut demontre."""
    verdict, motif = outils.verdict_corpus(vus=100, parses=97, echecs=3)
    assert verdict == "FAIL"
    assert "3" in motif


def test_un_corpus_entierement_parse_est_certifie():
    verdict, motif = outils.verdict_corpus(vus=2433, parses=2433, echecs=0)
    assert verdict == "CERTIFIE"
    assert "2433" in motif


def test_le_perimetre_du_corpus_est_non_vide_et_relatif():
    """Le scan doit voir le depot. Et le filtre porte sur le chemin RELATIF —
    defaut paye le 2026-09-10 : teste sur le chemin absolu, il vidait tout dans le
    worktree de la CI (`sandbox/ci_reference_wt`)."""
    fichiers = outils.fichiers_corpus()
    assert len(fichiers) > 500, "corpus vide ou filtre trop large"

    # FAUX POSITIF DE CE NR, corrige le 2026-09-10 : la premiere version cherchait
    # la SOUS-CHAINE « _attic » dans le chemin complet et accusait
    # `tools/forge_autophagie_attic.py` — un module LEGITIME dont le NOM contient
    # le mot. Le filtre de l'outil, lui, teste des PARTS de chemin, ce qui est
    # correct. Troisieme occurrence du meme motif dans la journee (la prose du
    # README prise pour une promesse, `numpy` pris pour un module frere) :
    # une MENTION n'est pas une STRUCTURE.
    from pathlib import Path as _P
    for f in fichiers:
        parts = _P(f).parts
        assert "_attic" not in parts, f"dossier d'archive traverse : {f}"
        assert "node_modules" not in parts


def test_le_venv_de_chantier_ne_touche_jamais_l_env_de_nokido():
    """Regle du corps : un CLI tiers va dans un env DEDIE. Le chemin du venv doit
    vivre sous sandbox/, jamais dans miniforge3."""
    cible = str(outils.VENV).replace("\\", "/")
    assert "/sandbox/chantier_pypi/" in cible
    assert "miniforge3" not in cible
