# -*- coding: utf-8 -*-
"""NR -- aucun echantillonneur de ressources ne demarre dans un process pytest (19/10, volet A).

Mesure 19/10 (enquete OPENCODE_GPTOSS job_e38b27f7, docs/audit/ci_memoire_6go_et_sampler_20261019.md) : dans la CI
de reference, `get_snapshot()` -> `_should_autostart_sampler()` rendait vrai (etat publie absent ou perime : le
premier appelant devient proprietaire) et la boucle du sampler spawnait forge_arbitrage / forge_auto_evict DANS le
pytest (pile prouvee, job_18ebfba6e38a.log). Un process de test n'est jamais proprietaire de l'echantillonnage du
corps. Contrat :
  1. tests/conftest.py pose LAFORGE_SAMPLER_AUTOSTART=0 par defaut (une valeur explicite de l'appelant prime) ;
  2. `_should_autostart_sampler()` rend donc False sous pytest ;
  3. `get_snapshot()` n'y demarre aucun thread d'echantillonnage.
"""
import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_conftest_coupe_l_autostart():
    assert os.environ.get(rm._SAMPLER_AUTOSTART_ENV) == "0"


def test_pytest_n_est_jamais_proprietaire(monkeypatch):
    # condition de la CI de reference : worktree neuf, AUCUN etat publie -> sans interrupteur, reprise de propriete
    monkeypatch.setattr(rm, "_published_state_age_s", lambda: None)
    assert rm._should_autostart_sampler() is False


def test_get_snapshot_ne_demarre_aucun_sampler():
    avant = getattr(rm, "_SAMPLER_THREAD", None)
    rm.get_snapshot()
    apres = getattr(rm, "_SAMPLER_THREAD", None)
    assert apres is avant or apres is None or not apres.is_alive()
