# -*- coding: utf-8 -*-
"""NR -- l'executeur reecrit en ABSOLU les chemins relatifs du depot cites dans la consigne d'AGY (30/10).

Mesure : `read_file` d'AGY refuse tout chemin relatif ; seule la sonde qui donnait le chemin ABSOLU complet sous le
worktree de tache a lu (docs/enquetes/sonde_lecture_agy_20261030.md). Les consignes disant « app\\x.py » ou
« <ton repertoire>\\app\\x.py » sont mortes au premier refus (agy s'arrete a la premiere action refusee, journal vide :
docs/enquetes/agy_lectures_20261030.md). Contrat : `_absolutiser_chemins(desc, wd)` remplace `app/…`, `tools/…`,
`tests/…`, `docs/…`, `config/…` (separateurs / ou \\) par `wd\\…` ; un chemin deja absolu ou une URL restent intacts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as te  # noqa: E402

pytestmark = pytest.mark.timeout(60)
WD = r"C:\w\nokido_worktrees\taches\antigravity_abc"


def test_relatifs_absolutises():
    s = te._absolutiser_chemins(r"Lire app\forge_mcp_registry.py puis ecrire tests/nr/test_x_nr.py.", WD)
    assert WD + r"\app\forge_mcp_registry.py" in s
    assert WD + r"\tests\nr\test_x_nr.py" in s


def test_absolus_et_urls_intacts():
    src = r"Voir C:\autre\app\x.py et https://github.com/a/b/tools/y.py"
    assert te._absolutiser_chemins(src, WD) == src


def test_la_delegation_absolutise_la_consigne():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    corps = src.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]
    assert "_absolutiser_chemins(" in corps
