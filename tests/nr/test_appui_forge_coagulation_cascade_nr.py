# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `app/forge_coagulation_cascade.py`. Il verifie que le module se CHARGE, rien de plus.

Ce qu'il apporte : un perimetre de mesure, sans lequel `juger_module_avec_gain`
ne peut rendre que GAIN_INDECIDABLE sur ce module ; et la detection des erreurs
de chargement (NameError, ImportError) sur un chemin que personne n'execute.

Ce qu'il NE prouve PAS : aucun comportement. Il ne compte donc jamais dans la
metrique `couverture prouvee` — le marqueur en tete sert exactement a l'en
exclure. Le remplacer par un vrai test de comportement est un progres ; le
supprimer sans le remplacer rend le module non mesurable.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_module_se_charge():
    assert importlib.import_module("forge_coagulation_cascade") is not None
