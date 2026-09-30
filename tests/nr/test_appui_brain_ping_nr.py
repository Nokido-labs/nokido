# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `app/brain_ping.py`. Il verifie que le module se CHARGE, rien de plus.

Ce qu'il apporte : un perimetre de mesure, sans lequel `juger_module_avec_gain` ne
peut rendre que GAIN_INDECIDABLE sur ce module ; et la detection des erreurs de
chargement (NameError, ImportError) sur un chemin que personne n'execute.

Ce qu'il NE prouve PAS : aucun comportement. Il ne compte donc jamais dans la metrique
`couverture prouvee`.

TROISIEME ETAT, pose le 2026-09-08 : ce module importe `zmq`, qui est ABSENT de
l'environnement de la CI. Ce n'est pas un module CASSE, c'est un environnement
INCOMPLET — `UNKNOWN`, pas `NO`. Le faire echouer accuserait le module a tort ; le
faire passer mentirait. Il SKIP donc, en NOMMANT la dependance manquante, ce qui rend
le manque visible sans rougir la suite de tout le monde.
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_module_se_charge():
    pytest.importorskip(
        "zmq",
        reason="dependance TIERCE absente de cet environnement : le module n'est pas "
               "en cause, la mesure n'est simplement pas possible ici",
    )
    assert importlib.import_module("brain_ping") is not None
