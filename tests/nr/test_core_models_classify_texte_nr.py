# -*- coding: utf-8 -*-
"""NR — `IntentClassifier.classify_with_cmd` doit transmettre le texte recu.

La methode recoit `text` mais deleguait par `_fh(cmd, ...)` -- `cmd` n'existe pas
dans cette portee : NameError a chaque classification (`classify`,
`classify_hybrid` en repli). Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_texte_recu_est_transmis():
    assert "cmd" not in noms_globaux_non_lies(
        "app/forge_core_models.py", "IntentClassifier.classify_with_cmd")
