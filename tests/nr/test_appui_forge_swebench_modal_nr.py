# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `tools/forge_swebench_modal.py`. TROISIEME ETAT : ce module importe `modal`, ABSENT de cet
environnement. Le module n'est pas casse, l'environnement est incomplet —
UNKNOWN, pas NO. Echouer accuserait le module a tort, passer mentirait :
il SKIP en nommant ce qui manque.
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_module_se_charge():
    pytest.importorskip("modal", reason="dependance TIERCE absente de cet "
                        "environnement : le module n'est pas en cause")
    assert importlib.import_module("forge_swebench_modal") is not None
