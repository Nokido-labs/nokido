# -*- coding: utf-8 -*-
"""NR — `forge_loop.apply_suggestion` doit recevoir la suggestion qu'elle applique.

Le corps lit `sugg["num"]`, `sugg["code"]`... et `_ask_restart` -- la signature de
la methode d'origine `DevOpsApp._apply_suggestion(sugg, _ask_restart=True)` --
mais l'extraction lui avait donne `(app, num: int)` : NameError sur `sugg` des
la premiere ligne. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : appliquer une suggestion reecrit le source de l'application.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_suggestion_et_l_option_de_redemarrage_sont_des_parametres():
    assert not ({"sugg", "_ask_restart"} & noms_globaux_non_lies("app/forge_loop.py", "apply_suggestion"))
