# -*- coding: utf-8 -*-
"""NR — `_validate_suggestion_async` (forge_handler_rag) doit lire l'application recue.

La fonction, extraite d'une methode du monolithe, declarait son premier parametre
`self` mais son corps lisait `app` (`app._DANGER_PATTERNS`, `app.model_rag`...) :
NameError des la premiere verification de danger d'une suggestion d'audit.
Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : renommer le parametre `self` -> `app`, les appelants le passent en
position. Test statique : la validation demande Ollama.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_l_application_est_liee():
    assert "app" not in noms_globaux_non_lies("app/forge_handler_rag.py", "_validate_suggestion_async")
