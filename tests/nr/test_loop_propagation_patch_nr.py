# -*- coding: utf-8 -*-
"""NR — `forge_loop.propagate_patch` doit recevoir ce que son corps utilise.

La fonction copie une version validee vers le source protege. Son corps lit
`new_path`, `vm` et `chat` -- la signature de son jumeau
`forge_handler_patch._propagate_patch(new_path, vm, chat)` -- mais l'extraction
lui avait donne `(app, suggestion)`, deux parametres jamais lus : NameError sur
`new_path` des la validation de syntaxe. Aucun appelant aujourd'hui. Releve par
l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Test statique : la propagation ecrit dans le source protege de l'application.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_signature_couvre_ce_que_le_corps_lit():
    assert not ({"new_path", "vm", "chat"} & noms_globaux_non_lies("app/forge_loop.py", "propagate_patch"))
