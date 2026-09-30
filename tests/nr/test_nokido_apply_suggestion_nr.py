# -*- coding: utf-8 -*-
"""NR — `@apply <n>` et la touche « t » doivent atteindre une implementation.

`DevOpsApp._apply_suggestion` (Nokido.py) deleguait a
`forge_handler_patch._apply_suggestion` -- nom qui n'existe pas dans ce module :
ImportError a chaque `@apply`, et la touche « t » (tout appliquer) cassait pareil.
L'implementation extraite du monolithe vit dans `forge_loop.apply_suggestion`
(patch cumulatif, PatchGuard, propagation, proposition de redemarrage). Releve
par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Le correctif delegue a `forge_loop.apply_suggestion` et lui transmet
`_ask_restart` : les appelants « tout appliquer » passent `False` pour ne
proposer le redemarrage qu'une fois. Test statique : appliquer une suggestion
reecrit le source de l'application.
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import RACINE, imports_introuvables  # noqa: E402


def test_la_delegation_vise_un_nom_qui_existe():
    assert imports_introuvables("app/Nokido.py", "DevOpsApp._apply_suggestion") == set()


def test_l_option_de_redemarrage_est_transmise():
    arbre = ast.parse((RACINE / "app" / "Nokido.py").read_text(encoding="utf-8"))
    meth = next(n for n in ast.walk(arbre)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_apply_suggestion")
    appels = [c for c in ast.walk(meth) if isinstance(c, ast.Call)
              and isinstance(c.func, ast.Name) and c.func.id == "_fh"]
    assert appels and all(any(k.arg == "_ask_restart" for k in c.keywords) for c in appels)
