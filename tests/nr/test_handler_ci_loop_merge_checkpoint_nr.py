# -*- coding: utf-8 -*-
"""NR — `@loop merge` doit poser son checkpoint AVANT la fusion.

La branche `merge` de `forge_handler_ci._handle_loop` teste `if save_orchestrator:`
pour creer un checkpoint avant de fusionner le tronc (« Double Porte »), mais
`save_orchestrator` est un global du seul monolithe : NameError avant meme la
fusion -- ni checkpoint ni fusion. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : `_g("save_orchestrator", None)`, l'accesseur deja importe par le
module. Test statique : le chemin demande un gestionnaire de versions.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_l_orchestrateur_de_sauvegarde_est_lie():
    assert "save_orchestrator" not in noms_globaux_non_lies("app/forge_handler_ci.py", "_handle_loop")
