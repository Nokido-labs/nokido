"""NR -- une sauvegarde de la base ne se pose jamais par defaut dans le depot (20/10).

Mesure du 20/10 : `forge_db_backup.DEFAULT_BACKUP_DIR` = `ROOT/_backups`, DANS l'arbre du depot (C:). La base pese
50 Go : une sauvegarde nocturne lancee sans `--dir` remplissait le disque systeme et l'arbre de travail partage.
Decision owner du 19/10 : l'archive externe va sur E: (F: n'est plus un prerequis).

Contrat : `dossier_par_defaut(environ, existe)` -> LAFORGE_BACKUP_DIR s'il est pose ; sinon E:/nokido_backups si le
volume E: existe ; sinon ROOT/_backups (repli DIT par l'outil, jamais tu).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("db_backup_defaut_nr", RACINE / "tools" / "forge_db_backup.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_la_variable_d_environnement_prime():
    m = _mod()
    assert m.dossier_par_defaut({"LAFORGE_BACKUP_DIR": "D:/ailleurs"}, lambda p: True) == Path("D:/ailleurs")


def test_le_volume_e_sert_d_archive_par_defaut():
    """Le VOLUME decide, pas le dossier : au premier lancement E:/nokido_backups n'existe pas encore (livraison MISTRAL
    e560ab5a5 : elle sondait le dossier et retombait alors dans le depot -- ce NR, trop lache, ne le voyait pas)."""
    m = _mod()
    volume_seul = {Path("E:/")}
    assert m.dossier_par_defaut({}, lambda p: Path(p) in volume_seul) == Path("E:/nokido_backups")


def test_sans_e_le_repli_reste_le_depot():
    m = _mod()
    assert m.dossier_par_defaut({}, lambda p: False) == m.ROOT / "_backups"
