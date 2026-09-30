# -*- coding: utf-8 -*-
"""NR — les traces de routage de `forge_handlers` ne doivent pas lever NameError.

`process_user_input` (six etapes tracees) et le scan reseau appellent
`debug_log(...)` (10 appels), fonction du monolithe jamais importee dans le
module : chaque trace levait NameError. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_debug_log_est_lie_dans_le_module():
    assert "debug_log" not in noms_non_lies_du_module("app/forge_handlers.py")
