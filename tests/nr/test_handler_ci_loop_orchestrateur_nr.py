# -*- coding: utf-8 -*-
"""NR — `@loop start` (forge_handler_ci) doit pouvoir construire son orchestrateur.

`_handle_loop` instanciait `ImprovementOrchestrator` sans jamais l'importer : le
nom n'existe pas dans `forge_handler_ci`, seul le monolithe `Nokido.py` l'importait
de `forge_code`. Consequence : NameError des le `start`, APRES que le tronc de loop
a ete ouvert (`start_loop_trunk`) -- tronc laisse ouvert, boucle jamais lancee.
Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Test statique (symtable) : lancer la boucle demande la TUI, Ollama et un
gestionnaire de versions, absents en CI.
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import RACINE, noms_globaux_non_lies  # noqa: E402


def test_l_orchestrateur_est_lie_dans_handle_loop():
    assert "ImprovementOrchestrator" not in noms_globaux_non_lies(
        "app/forge_handler_ci.py", "_handle_loop")


def test_la_source_importee_definit_bien_la_classe():
    """L'import local vise `forge_code`, comme le monolithe : la classe doit y
    rester definie au niveau module, sinon l'import deviendrait l'ImportError."""
    arbre = ast.parse((RACINE / "app" / "forge_code.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.ClassDef) and n.name == "ImprovementOrchestrator"
               for n in arbre.body)
