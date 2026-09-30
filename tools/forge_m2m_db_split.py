# -*- coding: utf-8 -*-
"""Sortir `agent_messages` de RAG/embeddings.db vers la base M2M dediee.

P0 decide par l'owner le 2026-09-05 (« il faut que les db soient scindees ») :
`handle_notify` ecrivait `agent_messages` EN SYNCHRONE dans l'event loop du hub,
dans la base de 24,9 Go, avec busy_timeout=15000 — chaque verrou tenu par un
autre ecrivain gelait le hub 15 s (16 morts en 2 jours quand le kill-watchdog
etait a 15 s). Meme sortie que `access_switches` le matin meme
(tools/forge_switches_db_split.py) : ce script en reprend la forme.

    LAFORGE_PYTHON tools/forge_m2m_db_split.py --copier            # dry-run
    LAFORGE_PYTHON tools/forge_m2m_db_split.py --copier --apply    # ecrit
    LAFORGE_PYTHON tools/forge_m2m_db_split.py --verifier          # compare

- la SOURCE est ouverte en `mode=ro` : ce script ne peut pas toucher la 24,9 Go ;
- le schema (table + index) est RELU dans sqlite_master de la source, jamais
  recopie a la main ;
- `--verifier` est independant de `--copier` : il rend, par id, ce qui manque
  et ce qui differe, et un fichier illisible est dit ILLISIBLE, pas « 0 ecart ».
La bascule des ecrivains/lecteurs (forge_db_path.m2m_path) prend effet au
redemarrage du hub ; entre la copie et ce redemarrage, les nouveaux messages
arrivent encore dans la source : rejouer `--copier --apply` juste apres la
bascule (INSERT OR IGNORE : idempotent), puis `--verifier`.
"""
from __future__ import annotations

__FORGE_COLOR__ = "cerveau/message_frame : sortir agent_messages vers la base M2M dediee"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TABLE = "agent_messages"
COLONNES = ("id", "from_agent", "to_agent", "correlation_id", "method", "payload",
            "result", "status", "created_at", "read_at")


def _source() -> str:
    from nokido_agent.app.forge_db_path import db_path
    return db_path()


def _cible_defaut() -> str:
    # La base DEDIEE, toujours -- pas m2m_path() : tant que l'interrupteur
    # sandbox/m2m.switch n'est pas pose, m2m_path() rend la base du RAG, c'est-a-dire
    # la SOURCE, et une copie sur elle-meme se lirait « deja : 19 282 » comme un succes.
    from nokido_agent.app.forge_db_path import _M2M_DEFAULT
    return str(_M2M_DEFAULT)


def _ro(chemin: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=15.0)
    c.execute("PRAGMA busy_timeout=15000")
    return c


def _schema(src: sqlite3.Connection) -> list[str]:
    """CREATE TABLE puis CREATE INDEX, tels que la source les porte."""
    rows = src.execute(
        "SELECT type, sql FROM sqlite_master WHERE tbl_name=? AND sql IS NOT NULL "
        "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END", (TABLE,)).fetchall()
    if not rows or rows[0][0] != "table":
        raise SystemExit(f"[m2m_split] table {TABLE} ABSENTE de la source {_source()}")
    return [s for _, s in rows]


def _empreinte(row: tuple) -> str:
    return hashlib.sha256("\x1f".join("" if v is None else str(v) for v in row).encode()).hexdigest()[:16]


def copier(cible: str, appliquer: bool, source: str | None = None, lot: int = 2000) -> dict:
    source = source or _source()
    if Path(cible).resolve() == Path(source).resolve():
        # Refus DIT, jamais un faux succes : mesure 2026-09-06, la cible par defaut
        # suivait m2m_path(), donc la source tant que la bascule n'a pas eu lieu.
        return {"source": source, "cible": cible, "dry_run": not appliquer,
                "inseres": 0, "deja": 0,
                "erreur": "cible identique a la source (interrupteur eteint ?) : passer --cible"}
    src = _ro(source)
    try:
        schema = _schema(src)
        total = src.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        out = {"source": source, "cible": cible, "lignes_source": total,
               "objets_schema": len(schema), "dry_run": not appliquer, "inseres": 0, "deja": 0}
        if not appliquer:
            return out
        Path(cible).parent.mkdir(parents=True, exist_ok=True)
        dst = sqlite3.connect(cible, timeout=30.0)
        try:
            dst.execute("PRAGMA journal_mode=WAL")
            dst.execute("PRAGMA busy_timeout=30000")
            for sql in schema:
                dst.execute(sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
                               .replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
            cols = ", ".join(COLONNES)
            marques = ", ".join("?" * len(COLONNES))
            cur = src.execute(f"SELECT {cols} FROM {TABLE} ORDER BY rowid")
            while True:
                rows = cur.fetchmany(lot)
                if not rows:
                    break
                avant = dst.total_changes
                dst.executemany(f"INSERT OR IGNORE INTO {TABLE} ({cols}) VALUES ({marques})", rows)
                dst.commit()
                ecrits = dst.total_changes - avant
                out["inseres"] += ecrits
                out["deja"] += len(rows) - ecrits
        finally:
            dst.close()
        return out
    finally:
        src.close()


def verifier(cible: str, source: str | None = None, echantillon: int = 500) -> dict:
    """Par id : manquants dans la cible, presents en trop, et lignes DIFFERENTES
    (empreinte des colonnes) sur un echantillon des plus recents.
    """
    source = source or _source()
    out = {"source": source, "cible": cible}
    if not Path(cible).exists():
        out["verdict"] = "CIBLE ABSENTE"
        return out
    try:
        src, dst = _ro(source), _ro(cible)
    except sqlite3.OperationalError as e:
        out["verdict"] = f"ILLISIBLE ({e})"
        return out
    try:
        ids_src = {r[0] for r in src.execute(f"SELECT id FROM {TABLE}")}
        ids_dst = {r[0] for r in dst.execute(f"SELECT id FROM {TABLE}")}
        out["lignes_source"], out["lignes_cible"] = len(ids_src), len(ids_dst)
        out["manquants_dans_cible"] = len(ids_src - ids_dst)
        out["en_trop_dans_cible"] = len(ids_dst - ids_src)
        out["exemples_manquants"] = sorted(ids_src - ids_dst)[:5]
        cols = ", ".join(COLONNES)
        recents = src.execute(
            f"SELECT {cols} FROM {TABLE} ORDER BY created_at DESC LIMIT ?", (echantillon,)).fetchall()
        differents = 0
        for row in recents:
            d = dst.execute(f"SELECT {cols} FROM {TABLE} WHERE id=?", (row[0],)).fetchone()
            if d is not None and _empreinte(d) != _empreinte(row):
                differents += 1
        out["echantillon"] = len(recents)
        out["differents_dans_echantillon"] = differents
        out["verdict"] = ("OK" if not (ids_src - ids_dst) and differents == 0
                          else "ECART")
        return out
    finally:
        src.close()
        dst.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--copier", action="store_true", help="recopier la table (avec --apply)")
    ap.add_argument("--verifier", action="store_true", help="comparer id a id + echantillon")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    ap.add_argument("--cible", default=None, help="defaut : forge_db_path.m2m_path()")
    ap.add_argument("--source", default=None, help="defaut : forge_db_path.db_path()")
    a = ap.parse_args()
    cible = a.cible or _cible_defaut()
    if not (a.copier or a.verifier):
        ap.print_help()
        return 2
    import json
    if a.copier:
        print(json.dumps(copier(cible, a.apply, a.source), ensure_ascii=False, indent=1))
    if a.verifier:
        r = verifier(cible, a.source)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("verdict") == "OK" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
