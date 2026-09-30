# -*- coding: utf-8 -*-
"""NR — la verification de fin de `@loop` doit atteindre une implementation.

A la fin de chaque boucle d'amelioration, les handlers appellent
`app._post_loop_safe_check(...)` (checkpoint ZIP, validation AST des versions,
rapport, proposition merge/rollback). Le wrapper `DevOpsApp._post_loop_safe_check`
deleguait a `forge_handlers._post_loop_safe_check`, nom qui n'existe pas :
ImportError, rattrapee par le handler de la boucle -> tronc abandonne SANS
verification. L'implementation vit dans `forge_loop.post_loop_safe_check`
(meme signature). Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : la verification demande une vraie boucle et un workspace.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables  # noqa: E402


def test_la_delegation_vise_un_nom_qui_existe():
    assert imports_introuvables("app/Nokido.py", "DevOpsApp._post_loop_safe_check") == set()
