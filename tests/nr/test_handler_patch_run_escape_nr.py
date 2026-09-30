# -*- coding: utf-8 -*-
"""NR — `@run` doit pouvoir afficher le resultat de la commande qu'il a lancee.

`forge_handler_patch._handle_run` affiche la sortie (et les erreurs) via
`escape(...)`, que le module n'importait pas. La commande SSH etait deja
EXECUTEE quand le NameError survenait : resultat perdu en silence, et en cas
d'erreur le `except` levait a son tour. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : `@run` execute une commande sur un hote SSH.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_escape_est_lie_dans_le_module():
    assert "escape" not in noms_non_lies_du_module("app/forge_handler_patch.py")
