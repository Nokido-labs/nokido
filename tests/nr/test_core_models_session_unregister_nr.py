# -*- coding: utf-8 -*-
"""NR — changer de session (barre laterale) ne doit pas lever NameError.

`SessionContext.unregister` retire la session du moteur RAG en lisant
`rag_engine`, global du monolithe jamais lie dans `forge_core_models` : NameError
a chaque changement de session depuis la barre laterale de la TUI (Nokido.py:3753),
apres la sauvegarde. La methode voisine `add()` le lie correctement
(`getattr(self, "rag_engine", None) or get_rag()`). Releve par l'audit « noms non
definis » (mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_moteur_rag_est_lie():
    assert "rag_engine" not in noms_globaux_non_lies("app/forge_core_models.py", "SessionContext.unregister")
