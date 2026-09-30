# -*- coding: utf-8 -*-
"""NR — `@workflow hub` doit afficher le statut du Hub et du Core.

`handle_workflow_hub` appelait `_hub.status_report()` et `get_core()`, deux noms
que le module n'importe que DANS une autre fonction (`handle_ci_remote`) : ici,
NameError rattrape en « @workflow hub: name '_hub' is not defined ». Le statut
n'etait jamais affiche. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : le chemin demande un Hub vivant.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_hub_et_core_sont_lies():
    manquants = noms_globaux_non_lies("app/forge_hub_handlers.py", "handle_workflow_hub")
    assert not ({"_hub", "get_core"} & manquants)
