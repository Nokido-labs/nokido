# -*- coding: utf-8 -*-
"""NR — le wrapper `DevOpsApp._validate_suggestion_async` doit transmettre sa suggestion.

Dans le monolithe `Nokido.py`, la methode recoit `sugg` mais deleguait par
`_fh(self, suggestion)` -- `suggestion` n'existe nulle part : NameError a chaque
validation passee par ce wrapper. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : la methode vit dans l'application Textual.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_suggestion_transmise_est_le_parametre_recu():
    assert "suggestion" not in noms_globaux_non_lies(
        "app/Nokido.py", "DevOpsApp._validate_suggestion_async")
