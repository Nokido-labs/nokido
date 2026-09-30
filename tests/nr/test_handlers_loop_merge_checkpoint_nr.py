# -*- coding: utf-8 -*-
"""NR — `@loop merge` de `forge_handlers` doit poser son checkpoint AVANT la fusion.

Jumeau de `test_handler_ci_loop_merge_checkpoint_nr.py`. La branche `merge` de
`forge_handlers._handle_loop` testait `if save_orchestrator:` sans jamais lier le nom :
NameError avant meme la fusion -- ni checkpoint ni fusion. L'audit « noms non definis »
(mesures/audits/noms_non_definis.md) avait corrige les trois jumeaux (handler_ci,
hub_handlers, mixin_patch) mais pas celui-ci ; `test_symboles_source_unique_nr` l'a
attrape a la CI de reference f72859efc (2026-09-29), une fois `save_orchestrator`
declare au niveau module dans forge_mixin_patch (0c47d9b2f).

Correctif : `_g("save_orchestrator", None)`, l'accesseur deja importe par le module.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_l_orchestrateur_de_sauvegarde_est_lie():
    assert "save_orchestrator" not in noms_globaux_non_lies("app/forge_handlers.py", "_handle_loop")
