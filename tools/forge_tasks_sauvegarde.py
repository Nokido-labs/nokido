"""tools/forge_tasks_sauvegarde.py — sauvegarde coherente de sandbox/tasks.db.

Copie par l'API backup de SQLite (snapshot consistant), source ouverte en
mode=ro, vers <dest>/tasks_AAAAMMJJ_HHMMSS.db. La copie est :
  - verifiee (PRAGMA integrity_check = ok, count(*) de tasks > 0) AVANT qu'une
    rotation retire quoi que ce soit ;
  - supprimee si non conforme (anciennes copiees intactes), rc 2, motif sur stderr.
Rotation : garde les 7 copies les plus recentes du motif tasks_AAAAMMJJ_HHMMSS.db,
et rien d'autre (un fichier d'un autre motif n'est jamais retire).

Usage :
    LAFORGE_PYTHON tools/forge_tasks_sauvegarde.py [--dest CHEMIN] [--src CHEMIN]

rc 0 = copie conforme posee ; rc 2 = echec nomme (motif sur stderr).
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

__FORGE_COLOR__ = "proprioception/sauvegarde : copie coherente et verifiee de sandbox/tasks.db"

_CODE = str(Path(__file__).resolve().parents[1])
if _CODE not in sys.path:
    sys.path.insert(0, _CODE)

from nokido_agent.app.forge_db_path import racine_donnees  # noqa: E402

GARDER = 7
MOTIF_COPIE = re.compile(r"^tasks_\d{8}_\d{6}\.db$")

def _echec(motif: str) -> int:
    print(f"[tasks_sauvegarde] ECHEC : {motif}", file=sys.stderr)
    return 2


def _rotation(dest: Path) -> None:
    """Garde les GARDER copies les plus recentes du motif ; retire les surplus."""
    copies = [
        p
        for p in dest.glob("*.db")
        if MOTIF_COPIE.match(p.name)
    ]
    # 8/11 (CI lot p1, test_rotation_a_sept rouge) : tri par mtime = ordre ARBITRAIRE entre copies ecrites dans la
    # meme seconde, et faux apres une copie/restauration qui change le mtime. Le NOM porte l'horodatage de la copie
    # (tasks_AAAAMMJJ_HHMMSS.db) : l'ordre lexicographique est l'ordre chronologique.
    copies.sort(key=lambda p: p.name, reverse=True)
    for vieille in copies[GARDER:]:
        vieille.unlink(missing_ok=True)


def _copie_conforme(copie: Path) -> bool:
    con = sqlite3.connect(str(copie), timeout=10.0)
    try:
        integrite = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrite != "ok":
            return False
        compte = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        return int(compte) > 0
    finally:
        con.close()


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sauvegarde coherente de sandbox/tasks.db")
    donnees = racine_donnees() / "sandbox"
    parser.add_argument("--dest", default=str(donnees / "backups"), help="Repertoire des copies (defaut sandbox/backups)")
    parser.add_argument("--src", default=str(donnees / "tasks.db"), help="Base source (defaut sandbox/tasks.db)")
    args = parser.parse_args(argv)

    src = Path(args.src).resolve()
    dest_dir = Path(args.dest).resolve()
    if not src.is_file():
        return _echec(f"source absente : {src}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    horodatage = (datetime.now()).strftime("%Y%m%d_%H%M%S")
    _copie = dest_dir / f"tasks_{horodatage}.db"
    try:
        conn_source = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True, timeout=10.0)
        try:
            conn_copie = sqlite3.connect(str(_copie), timeout=10.0)
            try:
                conn_source.backup(conn_copie)
            finally:
                conn_copie.close()
        finally:
            conn_source.close()
    except Exception as exc:
        _copie.unlink(missing_ok=True)
        return _echec(f"copie impossible depuis {src} : {exc!r:.300}")

    try:
        conforme = _copie_conforme(_copie)
        motif = "" if conforme else f"copie non conforme ({_copie.name})"
    except Exception as exc:
        conforme, motif = False, f"verification impossible : {exc!r:.300}"
    if not conforme:
        _copie.unlink(missing_ok=True)
        return _echec(motif)

    _rotation(dest_dir)
    print(f"[tasks_sauvegarde] OK : {_copie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
