# -*- coding: utf-8 -*-
"""NR — le stub `forge_handlers.compose` doit deleguer a une vraie implementation.

`compose(self)` renvoyait `_compose_main(self)`, nom qui n'existe nulle part dans
le depot : NameError a tout appel. Le monolithe lui-meme compose via
`forge_compose.compose` (Nokido.py, « tombeau corrige ») : le stub delegue
desormais la. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_handlers.py"


def test_compose_ne_lit_que_des_noms_lies():
    assert "_compose_main" not in noms_globaux_non_lies(FICHIER, "compose")


def test_compose_importe_un_nom_qui_existe():
    assert imports_introuvables(FICHIER, "compose") == set()
