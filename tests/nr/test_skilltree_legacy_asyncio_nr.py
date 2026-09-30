# -*- coding: utf-8 -*-
"""NR — la demo de `app/legacy/skilltree.py` doit avoir `asyncio` a portee.

`AdvancedRagTUI.run_demo_cycle` attend `asyncio.sleep(1.5)` entre deux etapes,
mais le module n'importait pas `asyncio` : NameError a la premiere etape de la
demo. Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Test statique : la demo est une application Textual.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_asyncio_est_lie_pour_la_demo():
    assert "asyncio" not in noms_globaux_non_lies(
        "app/legacy/skilltree.py", "AdvancedRagTUI.run_demo_cycle")
