# -*- coding: utf-8 -*-
"""NR — `forge_loop.apply_suggestion` lie versionnement et checkpoint avant usage.

La fonction lisait `save_orchestrator` (checkpoint avant patch) et
`version_manager` (code courant, preparation du patch, propagation) comme des
globals du seul monolithe : NameError au checkpoint, avant tout patch. Releve par
l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : `app_ctx().version_manager` (comme `post_loop_safe_check` du meme
module) et `get_app_attr("save_orchestrator")`. Test statique : appliquer une
suggestion reecrit le source de l'application.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_versionnement_et_checkpoint_sont_lies():
    assert not ({"version_manager", "save_orchestrator"}
                & noms_globaux_non_lies("app/forge_loop.py", "apply_suggestion"))
