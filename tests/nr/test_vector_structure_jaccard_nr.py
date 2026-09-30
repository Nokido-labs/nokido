"""NR — `forge_vector_structure.jaccard` : la mesure sur laquelle repose le verdict.

`tools/forge_vector_structure.py` (commit `aec01a951`) doit repondre a la question
owner « le 1024d organise-t-il mieux que le syntaxique ». Tout son verdict se
compare a un recouvrement LEXICAL : si `jaccard` se trompe, la conclusion sur
l'apport du vectoriel se trompe avec lui, et rien ne le signalerait.

Le module lui-meme n'a jamais tourne avec succes (il meurt sous `action=python`,
cf. le piege BLAS). Raison de plus pour verrouiller sa seule brique PURE : c'est
la partie dont on peut prouver quelque chose aujourd'hui.

Test PUR : aucune base, aucun vecteur, aucun appel externe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.forge_vector_structure import jaccard  # noqa: E402


def test_deux_textes_identiques_se_recouvrent_totalement():
    assert jaccard("le chat dort", "le chat dort") == pytest.approx(1.0)


def test_deux_textes_sans_mot_commun_ne_se_recouvrent_pas():
    assert jaccard("alpha beta", "gamma delta") == pytest.approx(0.0)


def test_le_recouvrement_partiel_est_entre_les_deux():
    """« le chat » sur « le chat dort » : 2 mots communs sur 3 distincts."""
    v = jaccard("le chat", "le chat dort")
    assert 0.0 < v < 1.0


def test_la_mesure_est_symetrique():
    a, b = "un deux trois", "deux trois quatre"
    assert jaccard(a, b) == pytest.approx(jaccard(b, a))


def test_un_texte_vide_ne_leve_pas_et_ne_recouvre_rien():
    """Un chunk vide existe en base : la mesure ne doit pas mourir dessus,
    ni rendre 1.0 (ce qui ferait passer deux vides pour des doublons)."""
    assert jaccard("", "quelque chose") == pytest.approx(0.0)
    assert jaccard("", "") == pytest.approx(0.0)


def test_la_repetition_ne_gonfle_pas_le_recouvrement():
    """Jaccard travaille sur des ENSEMBLES : repeter un mot ne change rien."""
    assert jaccard("chat chat chat", "chat") == pytest.approx(1.0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
