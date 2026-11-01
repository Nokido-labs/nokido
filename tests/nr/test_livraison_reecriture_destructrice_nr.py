# -*- coding: utf-8 -*-
"""NR -- une livraison qui RASE un fichier existant n'est jamais committee (30/10).

OPENCODE_DEFAUT3 (job_ebb0f6b9) a reecrit app/forge_health_diagnostic.py : -2532 / +27 lignes, en annoncant
OK_DONE. Le juge a refuse cette fois pour une autre raison (artefact non trouve) ; rien ne gardait le cas ou le
pointeur aurait ete lisible. Contrat : `_reecritures_destructrices(numstat)` nomme tout fichier qui perd au moins 200
lignes ET plus de la moitie de ses lignes d'avant ; `_committer_pour_agent` refuse alors le commit.
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


def test_la_reecriture_du_30_10_est_nommee():
    numstat = "27\t2532\tapp/forge_health_diagnostic.py\n5\t1\ttests/nr/test_x_nr.py\n"
    assert te._reecritures_destructrices(numstat) == ["app/forge_health_diagnostic.py"]


def test_un_vrai_refactor_passe():
    # gros retrait compense par un ajout comparable : pas un rasage
    assert te._reecritures_destructrices("900\t1000\tapp/gros.py\n") == []
    # petit fichier : sous le seuil absolu de 200 lignes
    assert te._reecritures_destructrices("2\t150\tapp/petit.py\n") == []


def test_le_commit_executeur_appelle_la_garde():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    corps = src.split("def _committer_pour_agent", 1)[1].split("\ndef ", 1)[0]
    assert "_reecritures_destructrices(" in corps
