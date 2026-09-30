# -*- coding: utf-8 -*-
"""NR — `@workflow list/cancel/logs` doivent atteindre le client Prefect.

`_handle_workflow` appelait `get_client()` (client Prefect) sans que le module
l'importe : des que Prefect est installe et initialise, `@workflow list`
affichait « Prefect: name 'get_client' is not defined » a la place des runs, et
`@workflow cancel/logs <id>` echouaient pareil. La fonction Prefect ne faisait
donc jamais rien. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : import local depuis `forge_prefect` (qui vaut `None` si Prefect est
absent, cas deja garde par `HAS_PREFECT`). Test statique : Prefect absent en CI.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_client_prefect_est_lie():
    assert "get_client" not in noms_globaux_non_lies("app/forge_handler_ci.py", "_handle_workflow")
