# -*- coding: utf-8 -*-
"""NR — les checkpoints du mixin (`@loop merge`, `@apply`) doivent lier leur orchestrateur.

`PatchMixin._handle_loop` (merge) et `PatchMixin._apply_suggestion` posent un
checkpoint avant d'ecrire, par `save_orchestrator` (6 lectures) -- global du seul
monolithe, alors que le module expose deja ses autres globals par `_LazyGlobal`
(`rag_engine`, `agentic_engine`...). NameError avant toute fusion ou application.
Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_l_orchestrateur_de_sauvegarde_est_lie():
    assert "save_orchestrator" not in noms_non_lies_du_module("app/forge_mixin_patch.py")
