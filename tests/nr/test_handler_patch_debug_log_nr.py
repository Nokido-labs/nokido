# -*- coding: utf-8 -*-
"""NR — `classify_with_cmd` ne doit pas casser sur son propre journal de routage.

La fonction trace chaque decision de routage par `debug_log(...)` (9 appels),
fonction du monolithe jamais importee dans `forge_handler_patch` : une fois le
texte lie, le premier appel levait NameError -- des le premier mot shell, la
premiere question, le premier motif RAG. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_debug_log_est_lie_dans_le_module():
    assert "debug_log" not in noms_non_lies_du_module("app/forge_handler_patch.py")
