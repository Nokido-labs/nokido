# -*- coding: utf-8 -*-
"""NR — le routeur intelligent de `dispatch_ai` doit recevoir la demande brute.

Dans `forge_dispatch_ai.dispatch_ai`, la branche SmartRouter passait
`user_input=_raw_demande`, variable LOCALE affectee seulement ~100 lignes plus bas,
dans la branche de repli. Sur ce chemin : UnboundLocalError, rattrapee par
`except Exception as _sr_err` -> `route_result = None` -> repli systematique sur
l'orchestrateur. Le SmartRouter n'a donc JAMAIS route une demande, sans autre
trace qu'un `logger.warning`. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : executer `dispatch_ai` demande la TUI Textual, un SmartRouter et
un orchestrateur, absents en CI.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import lus_avant_affectation  # noqa: E402


def test_la_demande_brute_est_liee_avant_le_smart_router():
    assert "_raw_demande" not in lus_avant_affectation(
        "app/forge_dispatch_ai.py", "dispatch_ai")
