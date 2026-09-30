# -*- coding: utf-8 -*-
"""NR — l'audit 3 agents du mixin doit lier son gestionnaire de memoire Ollama.

`_handle_audit` (forge_mixin_patch) libere la memoire Ollama avant chaque agent
par `_mem_mgr.free(...)` (8 lectures), global du seul monolithe : NameError au
premier agent, l'audit s'arretait avant toute proposition. Releve par l'audit
« noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : `forge_app_context.get_mem_mgr()` (lit `mem_optimizer` ou `_mem_mgr`
du monolithe, None s'il n'y en a pas -- cas deja garde par `if _mem_mgr:`).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_gestionnaire_de_memoire_est_lie():
    assert "_mem_mgr" not in noms_globaux_non_lies("app/forge_mixin_patch.py", "PatchMixin._handle_audit")
