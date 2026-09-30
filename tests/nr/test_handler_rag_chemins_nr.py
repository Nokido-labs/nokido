# -*- coding: utf-8 -*-
"""NR — `@rag dev`, `@rag drop <fichier>` et `@rag download` doivent construire leurs chemins.

`forge_handler_rag` appelait `Path(...)` en quatre endroits sans jamais importer
`pathlib.Path` : `@rag dev` (lecture de Nokido.env), `@rag drop` d'un fichier
local, la resolution du dossier RAG, et `@rag download`. NameError a chaque fois.
Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Test statique : ces chemins demandent la TUI et un moteur RAG vivant.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_path_est_lie_dans_le_module():
    assert "Path" not in noms_non_lies_du_module("app/forge_handler_rag.py")
