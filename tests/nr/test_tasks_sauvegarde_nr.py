"""NR : tools/forge_tasks_sauvegarde.py — sauvegarde coherente de sandbox/tasks.db.

Contrat (consigne du 2026-11-07) :
- copie par l'API backup de SQLite, source ouverte en mode=ro ;
- verification de la copie (integrity_check = ok, count(tasks) > 0) AVANT toute
  retablissement ; copie non conforme supprimee, anciennes copiees intactes, rc 2 ;
- garde les 7 copies les plus recentes du motif tasks_AAAAMMJJ_HHMMSS.db, rien d'autre ;
- un fichier d'un autre motif n'est JAMAIS supprime.

Pur : bases factices sous tmp_path, point d'entree main(), aucun reseau, aucune
vraie sandbox/tasks.db, aucun service. Phase RED : le module n'existe pas encore.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
CHEMIN_OUTIL = RACINE / "tools" / "forge_tasks_sauvegarde.py"


@pytest.fixture()
def outil():
    if not CHEMIN_OUTIL.exists():
        pytest.fail("tools/forge_tasks_sauvegarde.py absent : RED attendu avant le module")
    spec = importlib.util.spec_from_file_location("forge_tasks_sauvegarde", CHEMIN_OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def base_tasks(tmp_path, n_lignes=2):
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, titre TEXT)")
    for k in range(n_lignes):
        con.execute("INSERT INTO tasks (titre) VALUES (?)", (f"t{k}",))
    con.commit()
    con.close()
    return db


def rc_de(main, argv):
    """Lance main() ; retourne le code retour (SystemExit ou valeur)."""
    try:
        retour = main(argv)
        return 0 if retour is None else int(retour)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)


def test_copie_conforme(outil, tmp_path):
    src = base_tasks(tmp_path)
    dest = tmp_path / "backups"
    rc = rc_de(outil.main, ["--src", str(src), "--dest", str(dest)])
    assert rc == 0
    copies = sorted(dest.glob("tasks_*.db"))
    assert len(copies) == 1
    con = sqlite3.connect(str(copies[0]))
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    assert con.execute("SELECT titre FROM tasks ORDER BY id").fetchall() == [("t0",), ("t1",)]
    con.close()


def test_rotation_a_sept(outil, tmp_path):
    src = base_tasks(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()
    # 9 vieilles copies plausibles, horodatages distincts du meme motif.
    for k in range(9):
        (dest / f"tasks_20260130_12153{k}.db").write_bytes(b"x")
    rc = rc_de(outil.main, ["--src", str(src), "--dest", str(dest)])
    assert rc == 0
    restantes = sorted(dest.glob("tasks_*.db"))
    assert len(restantes) == 7
    # la plus ancienne du motif (121530) a ete evincee.
    assert not (dest / "tasks_20260130_121530.db").exists()


def test_rotation_suit_l_horodatage_du_nom_pas_le_mtime(outil, tmp_path):
    """8/11 : mtimes INVERSES par rapport aux noms (copie/restauration) -> la rotation garde quand meme les plus
    recentes PAR LE NOM. Rouge tant que la rotation triait par mtime."""
    import os
    src = base_tasks(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()
    for k in range(9):
        p = dest / f"tasks_20260130_12153{k}.db"
        p.write_bytes(b"x")
        t = 2_000_000_000 - k * 100  # la plus ANCIENNE par le nom a le mtime le plus RECENT
        os.utime(p, (t, t))
    rc = rc_de(outil.main, ["--src", str(src), "--dest", str(dest)])
    assert rc == 0
    assert not (dest / "tasks_20260130_121530.db").exists()
    assert (dest / "tasks_20260130_121538.db").exists()


def test_fichier_autre_motif_jamais_supprime(outil, tmp_path):
    src = base_tasks(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()
    etranger = dest / "notes_20260101_000000.db"
    etranger.write_bytes(b"important")
    (dest / "critical_events.bak.2026.db").write_bytes(b"autre")
    for k in range(8):
        (dest / f"tasks_20260120_00000{k}.db").write_bytes(b"x")
    rc = rc_de(outil.main, ["--src", str(src), "--dest", str(dest)])
    assert rc == 0
    assert etranger.exists()
    assert (dest / "critical_events.bak.2026.db").exists()


def test_source_illisible_rc2_et_anciennes_intactes(outil, tmp_path, capsys):
    src = tmp_path / "tasks.db"
    src.write_bytes(b"pas une base sqlite aucunement")
    dest = tmp_path / "backups"
    dest.mkdir()
    ancienne = dest / "tasks_20260101_000000.db"
    ancienne.write_bytes(b"gardee")
    rc = rc_de(outil.main, ["--src", str(src), "--dest", str(dest)])
    assert rc == 2
    assert capsys.readouterr().err.strip()
    assert ancienne.exists()
    assert list(dest.glob("tasks_2026*.db")) == [ancienne]


def test_taches_vide_rc2(outil, tmp_path, capsys):
    src = tmp_path / "tasks.db"
    con = sqlite3.connect(str(src))
    con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    dest = tmp_path / "backups"
    rc = rc_de(outil.main, ["--src", str(src), "--dest", str(dest)])
    assert rc == 2
    assert capsys.readouterr().err.strip()
    assert list(dest.glob("tasks_*.db")) == []
