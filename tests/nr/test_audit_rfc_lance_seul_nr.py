"""NR -- tools/audit_rfc_compliance.py se LANCE seul, hors de la racine du depot (2026-10-20).

Mesure du 20/10 : `run_job tools/audit_rfc_compliance.py` (dossier courant sandbox/workspace) est mort en
« ModuleNotFoundError: No module named 'nokido_agent' » -- le script insere `tools/` dans sys.path (un "." au lieu de
".."), alors que le paquet `nokido_agent/` vit a la racine. Sous pytest la racine est deja dans le chemin : le defaut
etait invisible a tous les tests qui importent le module. Ce NR emprunte le CHEMIN REEL : l'interpreteur isole (-I,
ni PYTHONPATH ni dossier du script), depuis un dossier etranger, `--help`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def test_le_script_se_lance_hors_de_la_racine(tmp_path):
    r = subprocess.run([sys.executable, "-I", str(RACINE / "tools" / "audit_rfc_compliance.py"), "--help"],
                       cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    assert r.returncode == 0, (r.stderr or r.stdout)[-600:]
    assert "--category" in r.stdout
