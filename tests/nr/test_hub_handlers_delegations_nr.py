# -*- coding: utf-8 -*-
"""NR — `@workflow hub` et `@ci remote` (forge_hub_handlers) delegent avec `app`.

`handle_workflow(app, ...)` et `handle_ci(app, ...)` deleguaient les sous-commandes
`hub` et `remote` par `_hwh(self)` et `_hcr(self, parts)` : `self` n'existe pas
dans ces fonctions (vestige des methodes du monolithe) -> NameError. Releve par
l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Test statique : les delegations demandent un Hub vivant.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_hub_handlers.py"


def test_handle_workflow_ne_passe_plus_self():
    assert "self" not in noms_globaux_non_lies(FICHIER, "handle_workflow")


def test_handle_ci_ne_passe_plus_self():
    assert "self" not in noms_globaux_non_lies(FICHIER, "handle_ci")
