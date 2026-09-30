# -*- coding: utf-8 -*-
"""NR — `forge_handlers._handle_rag` doit etre le vrai handler, pas un stub.

`forge_handlers` importe le vrai `_handle_rag` (async) de `forge_handler_rag`,
puis le REDEFINISSAIT plus bas en « stub de compatibilite » synchrone qui rend
`None` (`# noqa: F811` : ruff ne le signalait plus). Tout
`await forge_handlers._handle_rag(...)` levait TypeError (`DevOpsApp._handle_rag`
de Nokido.py, plusieurs tests), et le canari de demarrage, qui ne verifie que la
presence du nom, passait a tort. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import RACINE  # noqa: E402


def test_aucune_redefinition_ne_masque_le_handler_importe():
    arbre = ast.parse((RACINE / "app" / "forge_handlers.py").read_text(encoding="utf-8"))
    redefinitions = [n.lineno for n in arbre.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_handle_rag"]
    assert redefinitions == [], "stub qui masque le vrai _handle_rag : lignes %s" % redefinitions


def test_le_handler_reste_importe_du_module_specialise():
    arbre = ast.parse((RACINE / "app" / "forge_handlers.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.ImportFrom) and n.module == "nokido_agent.app.forge_handler_rag"
               and any(a.name == "_handle_rag" for a in n.names) for n in arbre.body)
