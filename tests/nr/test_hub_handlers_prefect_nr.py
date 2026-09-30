# -*- coding: utf-8 -*-
"""NR — `handle_workflow` / `handle_ci` (forge_hub_handlers) lient Prefect avant usage.

Les deux handlers lisaient `prefect_manager` (22 fois), `HAS_PREFECT` et
`get_client` comme des globals du seul monolithe : NameError sur list/run/add/
del/show/deploy/history et sur @ci run/status/lint/test/diff/env. Dans les
taches `do_test`, `do_diff`, `do_env`, le `except RuntimeError` ne rattrape pas
NameError : la tache mourait sans rien afficher. Aujourd'hui la TUI route
@workflow et @ci vers `forge_handler_ci` : ces copies n'ont pas d'appelant, mais
elles sont exportees et verifiees au demarrage (canari de Nokido.py). Releve par
l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : `forge_context.get_prefect_manager()` et import de `HAS_PREFECT`,
`get_client` depuis `forge_prefect`. Test statique : Prefect et SSH absents en CI.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_hub_handlers.py"


def test_handle_workflow_lie_prefect():
    assert not ({"prefect_manager", "HAS_PREFECT", "get_client"}
                & noms_globaux_non_lies(FICHIER, "handle_workflow"))


def test_handle_ci_lie_prefect():
    assert "prefect_manager" not in noms_globaux_non_lies(FICHIER, "handle_ci")
