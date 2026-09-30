# -*- coding: utf-8 -*-
"""NR — `Nokido.get_remote_context()` ne doit pas lire un `self` inexistant.

Fonction de module (pas une methode) du monolithe, elle deleguait par
`_fh(self)` : NameError sur `self` -- et `forge_handlers.get_remote_context` ne
prend de toute facon aucun argument. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_get_remote_context_ne_lit_pas_self():
    assert "self" not in noms_globaux_non_lies("app/Nokido.py", "get_remote_context")
