# -*- coding: utf-8 -*-
"""Non-regression — un applicateur de blocs qui ne remplace RIEN doit le DIRE.

Defaut mesure le 2026-08-26, en production, sur `governed_edit` : des blocs passes en
tableau JSON au lieu du format Aider donnent `parse_blocks(...) == []`. `apply_to_text`
rendait alors `ok=True` avec le texte INCHANGE ; le handler hub ecrivait le fichier a
l identique et repondait « ok:true, verified: relecture disque identique ». Les deux
affirmations etaient VRAIES et l edition n avait rien fait. Trois appels de suite ont
ete annonces reussis sans qu une seule ligne ne change.

Ce n est pas un garde manquant, c est un garde CONTOURNE : `apply_blocks` refusait deja
`not blocks` -- mais le seul appelant reel du hub passe par `apply_to_text`, qui ne
l avait pas. Meme famille que « un garde branche sur un signal que personne n emet ».

Regle verrouillee ici : un succes doit etre adosse a un COMPTE. `ok=True` avec
`applied == []` est un mensonge poli.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SR = pytest.importorskip("forge_search_replace")

_DEB, _SEP, _FIN = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"
SOURCE = "alpha\nbeta\ngamma\n"


def bloc(cherche, remplace):
    return "\n".join((_DEB, cherche, _SEP, remplace, _FIN))


def test_liste_vide_refuse():
    """LE test. Zero bloc = refus, pas un no-op deguise en succes."""
    res = SR.apply_to_text(SOURCE, [])
    assert res["ok"] is False, "une liste vide rendait ok=True et le texte inchange"
    assert res["text"] == SOURCE, "un refus ne doit pas alterer le texte"
    assert res["applied"] == []
    assert res["failed"], "le refus doit porter une raison lisible"


def test_raison_du_refus_nomme_le_format():
    """La raison doit orienter : c est la description du champ qui a induit l erreur."""
    raison = str(SR.apply_to_text(SOURCE, [])["failed"])
    assert "SEARCH/REPLACE" in raison
    assert "JSON" in raison, "le cas reel etait un tableau JSON — le dire evite la recidive"


def test_json_au_lieu_du_format_aider_refuse_de_bout_en_bout():
    """Le cas EXACT paye en production : le parseur rend [], donc l application refuse."""
    faux = '[{"search": "beta", "replace": "BETA"}]'
    blocs = SR.parse_blocks(faux)
    assert blocs == [], "un tableau JSON ne doit pas parser comme des blocs Aider"
    assert SR.apply_to_text(SOURCE, blocs)["ok"] is False


def test_bloc_valide_passe_toujours():
    """Le garde ne doit pas casser le chemin nominal."""
    res = SR.apply_to_text(SOURCE, SR.parse_blocks(bloc("beta", "BETA")))
    assert res["ok"] is True
    assert res["text"] == "alpha\nBETA\ngamma\n"
    assert len(res["applied"]) == 1


def test_succes_adosse_a_un_compte():
    """Regle generale : tout ok=True porte au moins un bloc applique."""
    res = SR.apply_to_text(SOURCE, SR.parse_blocks(bloc("alpha", "ALPHA")))
    assert res["ok"] is True and len(res["applied"]) >= 1


def test_search_introuvable_refuse():
    res = SR.apply_to_text(SOURCE, SR.parse_blocks(bloc("delta", "DELTA")))
    assert res["ok"] is False and res["text"] == SOURCE


def test_search_ambigu_refuse():
    """Deux occurrences : on n ecrit RIEN plutot que de choisir au hasard."""
    res = SR.apply_to_text("x\nx\n", SR.parse_blocks(bloc("x", "y")))
    assert res["ok"] is False
    assert "ambigu" in str(res["failed"]).lower()


def test_search_vide_cree_toujours():
    """Le mode creation/append ne passe pas par une liste vide : il a UN bloc."""
    res = SR.apply_to_text("", SR.parse_blocks(bloc("", "neuf")))
    assert res["ok"] is True and res["text"] == "neuf"
