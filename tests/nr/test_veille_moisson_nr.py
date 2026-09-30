"""NR — moisson de la veille (`forge_veille_moisson`).

Defaut REELLEMENT paye le 2026-09-08, releve par l'owner : *« il n'y a pas eu que
des depots GitHub en veille, des pages aussi »*. L'identification par depot rend
`None` sur une URL, donc **51 494 chunks web et 329 hotes restaient hors de tout
inventaire**. Une page n'a pas de fichiers d'intention : lui appliquer le filtre
des depots les ecarte toutes.

Le second invariant est celui de l'absence DITE : un canal eteint rend `None`
(INDISPONIBLE) et jamais `[]` (aucun resultat), sans quoi une panne se lit comme
un corpus vide.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "app"))

# Import STRICT (2026-09-24) : `importorskip` sur le livrable transformait un import
# casse en test SAUTE — un faux vert (methode des cliquets, 08/09).
import forge_veille_moisson as mo  # noqa: E402


def test_une_page_web_est_reconnue_par_son_hote():
    assert mo.hote("https://arxiv.org/abs/2503.21676") == "arxiv.org"
    assert mo.hote("http://dx.doi.org/10.1109/iros55552") == "dx.doi.org"


def test_ce_qui_n_est_pas_une_page_ne_donne_pas_d_hote():
    """Sans cette separation, un depot serait compte comme une page."""
    assert mo.hote("github:nengo/nengo/README.md") is None
    assert mo.hote("berriai_litellm/litellm/x.py") is None
    assert mo.hote("") is None


def test_les_documents_structurants_sont_reconnus():
    """Un depot s'enseigne par ce qu'il DIT de ses choix, pas par son code."""
    for chemin in ("github:o/r/README.md", "github:o/r/docs/ARCHITECTURE.md",
                   "github:o/r/docs/adr/0001-choix.md", "github:o/r/SPEC.md",
                   "github:o/r/CHEATSHEET.md", "github:o/r/CONTRIBUTING.md"):
        assert mo.DOCS_STRUCTURANTS.search(chemin), chemin


def test_le_code_ordinaire_n_est_pas_un_document_structurant():
    for chemin in ("github:o/r/src/main.rs", "github:o/r/lib/utils.py",
                   "github:o/r/tests/x_test.go"):
        assert not mo.DOCS_STRUCTURANTS.search(chemin), chemin


def test_les_sources_internes_sont_ecartees():
    """Un instrument ne lit jamais son propre vocabulaire : motif paye six fois
    en trois jours."""
    for source in ("conv_claude/abc/12", "session:2026-09-01:solution",
                   "mcp_result:POST_COMMIT:x", "memory:carte"):
        assert mo.interne(source), source
    assert not mo.interne("https://arxiv.org/abs/1")
    assert not mo.interne("github:nengo/nengo/README.md")


def test_un_canal_eteint_rend_indisponible_et_non_une_liste_vide(monkeypatch):
    """`None` = INDISPONIBLE, `[]` = aucun resultat. Confondre les deux fait lire
    une panne comme un corpus vide."""
    monkeypatch.setattr(mo, "embed", lambda _texte: None)
    assert mo.dense("une question", con=None) is None


def test_la_borne_par_depot_est_declaree():
    """Une borne doit dire COMBIEN : le module publie la sienne."""
    assert isinstance(mo.EXTRAITS_PAR_DEPOT, int)
    assert mo.EXTRAITS_PAR_DEPOT >= 1
