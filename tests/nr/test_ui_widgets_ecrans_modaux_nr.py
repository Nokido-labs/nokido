# -*- coding: utf-8 -*-
"""NR — les ecrans modaux de forge_ui_widgets doivent pouvoir se composer.

`ConfirmScreen`, `ModelScreen` et `NotificationScreen` disposent leur contenu
dans un `Vertical` (conteneur Textual) que le module n'importait pas : NameError
a la composition. `ConfirmScreen` est poussee par `dispatch_ai` quand le garde de
danger avertit sur une commande a injecter : la confirmation ne pouvait jamais
s'afficher. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_vertical_est_lie():
    assert "Vertical" not in noms_non_lies_du_module("app/forge_ui_widgets.py")
