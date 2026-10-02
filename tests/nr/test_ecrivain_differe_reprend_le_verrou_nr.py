# -*- coding: utf-8 -*-
"""NR -- EcrivainDiffere ne PERD plus une ecriture sur un verrou SQLite (2026-10-01).

Mesure : 26 ecritures du profileur du hub perdues en une minute, toutes sur `database is
locked`. Le fil d'ecriture est hors de la boucle : il peut attendre son tour. Seul le
VERROU est repris ; toute autre erreur reste perdue et comptee tout de suite (la reprendre
serait un deni du vrai probleme), et un verrou qui ne lache pas finit compte, pas en boucle.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app.forge_bounded_queue import EcrivainDiffere  # noqa: E402


@pytest.fixture
def ecrivain(monkeypatch):
    monkeypatch.setattr(EcrivainDiffere, "RECUL_BASE_S", 0.0)
    return EcrivainDiffere("nr_verrou", capacity=10)


def _ecriture(erreurs, faites):
    def ecrire():
        if erreurs:
            raise erreurs.pop(0)
        faites.append(1)
    return ecrire


def test_un_verrou_passager_est_repris_et_l_ecriture_faite(ecrivain):
    faites = []
    erreurs = [sqlite3.OperationalError("database is locked")] * 2
    assert ecrivain.soumettre(_ecriture(erreurs, faites))
    assert ecrivain.vider(5)
    assert faites == [1]
    assert ecrivain.stats()["echecs"] == 0 and ecrivain.stats()["reprises"] == 2


def test_une_autre_erreur_n_est_pas_reprise(ecrivain):
    faites = []
    erreurs = [sqlite3.OperationalError("no such table: promcp_tool_metrics")]
    ecrivain.soumettre(_ecriture(erreurs, faites))
    assert ecrivain.vider(5)
    assert faites == [] and ecrivain.echecs == 1 and ecrivain.reprises == 0


def test_un_verrou_qui_ne_lache_pas_finit_compte(ecrivain):
    faites = []
    erreurs = [sqlite3.OperationalError("database is locked")] * 50
    ecrivain.soumettre(_ecriture(erreurs, faites))
    assert ecrivain.vider(5)
    assert faites == [] and ecrivain.echecs == 1
    assert ecrivain.reprises == EcrivainDiffere.REPRISES_VERROU
