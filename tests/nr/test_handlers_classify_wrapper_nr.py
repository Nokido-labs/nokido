# -*- coding: utf-8 -*-
"""NR — le wrapper `forge_handlers.classify_with_cmd` ne doit pas lever ImportError.

Le wrapper (verifie par le canari de demarrage de Nokido.py) delegue a
`forge_handler_patch.classify_with_cmd`, mais importait aussi
`forge_mixin_ui._compose_main` -- nom qui n'existe nulle part, ligne egaree du
stub `compose` voisin. ImportError a CHAQUE appel : le repli NLU de
`forge_core_models.IntentClassifier` ne pouvait jamais classer. Le canari ne
verifie que la presence du nom, il passait donc a tort. Releve par l'audit
« noms non definis » (mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables  # noqa: E402


def test_le_wrapper_n_importe_que_des_noms_qui_existent():
    assert imports_introuvables("app/forge_handlers.py", "classify_with_cmd") == set()
