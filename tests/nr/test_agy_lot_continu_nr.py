# -*- coding: utf-8 -*-
"""NR — la session continue d'agy s'active PAR LOT, jamais par defaut.

POURQUOI (mesure + arbitrage owner, 2026-09-18). Interroge sur ses propres capacites,
agy 1.2.6 a repondu qu'il n'a PAS `--experimental-acp` mais qu'il sait reprendre une
session (`--continue` / `--conversation`). Chaque delegation recreait pourtant une
session complete : c'est le cout ressenti sur un enchainement de taches.

L'owner a tranche la forme : **par lot explicite, pas par defaut**. La raison tient en
une phrase -- `--continue` fait heriter le contexte de la tache PRECEDENTE. Sur un lot
coherent c'est le gain ; sur deux taches independantes l'agent repondrait a la question
d'avant, et rien dans le resultat ne le signalerait. Un defaut invisible est pire qu'un
cout visible.

MORSURE : une tache ordinaire ne doit JAMAIS porter `--continue`. C'est cette moitie-la
qui protege, l'autre n'etant qu'une commodite.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "forge_task_executor.py"


@pytest.fixture(scope="module")
def corps() -> str:
    """Le CORPS de `_delegate_to_agy`, isole -- on ne juge pas le reste du fichier."""
    if not SOURCE.exists():
        pytest.skip("forge_task_executor.py absent de cet arbre")
    txt = SOURCE.read_text(encoding="utf-8", errors="replace")
    i = txt.find("def _delegate_to_agy")
    assert i > 0, "la fonction de delegation a disparu"
    j = txt.find("\ndef ", i + 10)
    return txt[i:j if j > 0 else len(txt)]


def test_le_marqueur_de_lot_est_lu_en_TETE_de_tache(corps):
    """L'intention se declare au debut, pas n'importe ou dans 30 000 caracteres."""
    assert "startswith" in corps and "LOT_CONTINU" in corps, (
        "le marqueur n'est pas cherche en tete : un texte qui CITE le mot suffirait "
        "a reprendre une session par accident")


def test_le_drapeau_est_CONDITIONNE(corps):
    """MORSURE — `--continue` ne doit jamais etre dans la commande de base."""
    m = re.search(r"cmd\s*=\s*\[agy_bin.*?\]", corps, re.S)
    assert m, "la commande de base est introuvable"
    assert "--continue" not in m.group(0), (
        "`--continue` est pose PAR DEFAUT : toute tache heriterait du contexte de la "
        "precedente, et l'agent repondrait a la question d'avant sans que rien ne le dise")
    assert re.search(r"if\s+_continu\s*:", corps), "l'ajout n'est pas sous condition"


def test_l_activation_est_JOURNALISEE(corps):
    """Un changement de mode qui ne se voit pas dans le journal est indebuggable."""
    bloc = corps[corps.find("if _continu"):]
    assert "log." in bloc[:400], (
        "la reprise de session ne laisse aucune trace : impossible de savoir "
        "apres coup si une reponse venait d'un contexte herite")


@pytest.mark.parametrize("desc,attendu", [
    ("LOT_CONTINU: instruire les items 1 a 20", True),
    ("lot_continu: minuscules acceptees", True),
    ("   LOT_CONTINU apres espaces", True),
    ("Instruire un item isole", False),
    ("Analyse citant LOT_CONTINU au milieu du texte", False),
    ("", False),
])
def test_la_regle_de_declenchement_se_comporte_comme_attendu(desc, attendu):
    """La regle elle-meme, rejouee a l'identique — y compris le cas du mot CITE."""
    assert desc.lstrip().upper().startswith("LOT_CONTINU") is attendu, desc
