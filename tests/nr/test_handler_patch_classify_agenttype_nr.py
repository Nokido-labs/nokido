# -*- coding: utf-8 -*-
"""NR — `classify_with_cmd` doit rendre des `AgentType` du module qui les compare.

La fonction rend `AgentType.ACTION / RAG / CHAT` sans importer `AgentType` :
NameError a chaque verdict. Deux enums portent ce nom (`forge_llm` et
`forge_core_models`) ; l'appelant, `forge_core_models.IntentClassifier`, compare
avec le sien. Le correctif importe donc celui de `forge_core_models`, comme
`forge_dispatch_ai`. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import RACINE, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_handler_patch.py"


def test_agenttype_est_lie():
    assert "AgentType" not in noms_globaux_non_lies(FICHIER, "classify_with_cmd")


def test_agenttype_vient_du_module_de_l_appelant():
    arbre = ast.parse((RACINE / FICHIER).read_text(encoding="utf-8"))
    fn = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "classify_with_cmd")
    sources = {n.module for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)
               and any(a.name == "AgentType" for a in n.names)}
    assert sources == {"nokido_agent.app.forge_core_models"}
