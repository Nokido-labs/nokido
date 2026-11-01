# -*- coding: utf-8 -*-
"""NR -- la sortie BRUTE d'agy est conservee avant toute reaffectation (30/10).

Sonde job_ce55a33f : AGY rend 110 caracteres, RIEN_PRODUIT, puis la reaffectation vers WORKER_CODE ECRASE le
resultat dans tasks.db -- la seule preuve du chemin refuse par le bac etait perdue. Contrat : _delegate_to_agy ecrit
la sortie brute (stdout/stderr) dans sandbox/jobs/agy_<tache>.json AVANT de juger ou de reaffecter.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
CORPS = SRC.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]

pytestmark = pytest.mark.timeout(60)


def test_la_sortie_brute_est_ecrite_avant_le_jugement():
    assert "_conserver_sortie_agy(" in CORPS
    assert CORPS.index("_conserver_sortie_agy(") < CORPS.index("_reaffecter(")


def test_le_conservateur_existe_et_ecrit_sous_sandbox_jobs():
    assert "def _conserver_sortie_agy" in SRC
    fn = SRC.split("def _conserver_sortie_agy", 1)[1].split("\ndef ", 1)[0]
    assert "agy_" in fn and "jobs" in fn
