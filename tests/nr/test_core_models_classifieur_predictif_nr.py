# -*- coding: utf-8 -*-
"""NR — `IntentClassifier` doit lier son predictif et sa trace avant usage.

`classify_hybrid` testait `if HAS_PREDICTIF:` HORS de son `try` : NameError a
chaque classification (le classifieur global du monolithe, Nokido.py:1737). Le
chemin predictif lisait aussi `_pred_get_router` et `debug_log`, et `classify`
trace par `debug_log` : trois noms du seul monolithe. Releve par l'audit « noms
non definis » (mesures/audits/noms_non_definis.md).

Correctif : `HAS_PREDICTIF` et `_pred_get_router` lus comme le fait
`forge_dispatch_ai` (`get_app_attr`, `forge_nlu.get_router_if_ready`), et
`debug_log` importe de `forge_logging`.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_core_models.py"


def test_classify_hybrid_lie_ses_noms():
    assert not ({"HAS_PREDICTIF", "_pred_get_router", "debug_log"}
                & noms_globaux_non_lies(FICHIER, "IntentClassifier.classify_hybrid"))


def test_classify_lie_sa_trace():
    assert "debug_log" not in noms_globaux_non_lies(FICHIER, "IntentClassifier.classify")


def test_les_noms_importes_existent():
    assert imports_introuvables(FICHIER, "IntentClassifier.classify_hybrid") == set()
