# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `app/web_hub/dashboard_diag_htmx.py`. TROISIEME ETAT : ce module importe `dashboard_diag_htmx`, ABSENT de cet
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
    pytest.importorskip("dashboard_diag_htmx", reason="dependance TIERCE absente de cet "
                        "environnement : le module n'est pas en cause")
    assert importlib.import_module("dashboard_diag_htmx") is not None
