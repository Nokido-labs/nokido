# -*- coding: utf-8 -*-
"""NR — `@loop` (TUI) doit lier ses dependances avant de les utiliser.

`forge_hub_handlers.handle_loop` -- la cible reelle de `@loop` dans la TUI --
lisait `version_manager`, `rag_engine`, `settings`, `save_orchestrator` et
`ImprovementOrchestrator` comme des globals que seul le monolithe definit
(24 lectures) : `start` cassait des la resolution des fichiers cibles, `merge` et
`versions` des leur premiere ligne. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : liaison par `forge_app_context.app_ctx()` et `get_app_attr`, import
local de `ImprovementOrchestrator` depuis `forge_code` (comme le monolithe).
Test statique : la boucle demande Ollama et un gestionnaire de versions.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_les_dependances_du_loop_sont_liees():
    manquants = noms_globaux_non_lies("app/forge_hub_handlers.py", "handle_loop")
    assert not ({"version_manager", "rag_engine", "settings", "save_orchestrator",
                 "ImprovementOrchestrator"} & manquants), manquants
