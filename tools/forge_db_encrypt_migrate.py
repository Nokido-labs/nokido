#!/usr/bin/env python3
"""
forge_db_encrypt_migrate.py — Migration at-rest SQLCipher d'une DB sqlite.

AVERTISSEMENT
-------------
Ce script produit une COPIE chiffrée (<db>.enc) d'une base sqlite en clair.
Il ne supprime JAMAIS l'original et ne fait AUCUN swap automatique.

La migration n'est exploitable côté système QUE lorsque TOUS les lecteurs
ouvrent la DB via app/forge_db_conn.get_db() (audit 2026-06-01 : ~631 sites
sqlite3.connect() directs, 0 helper central). Tant que ce cutover n'est pas
fait, swapper la DB chiffrée en place RENDRA LE SYSTÈME ILLISIBLE. C'est
pourquoi --migrate s'arrête après avoir produit <db>.enc + le backup.

Usage
-----
  set LAFORGE_DB_KEY=<passphrase>
  python tools/forge_db_encrypt_migrate.py --db RAG/embeddings.db --dry-run
  python tools/forge_db_encrypt_migrate.py --db RAG/embeddings.db --migrate
  python tools/forge_db_encrypt_migrate.py --db RAG/embeddings.db --verify

Pré-requis : pip install pysqlcipher3
Clé : env LAFORGE_DB_KEY (obligatoire pour --migrate/--verify).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time


def _log(msg: str) -> None:
    print(f"[at-rest-migrate] {msg}", flush=True)


def _require_key() -> str:
    key = os.environ.get("LAFORGE_DB_KEY")
    if not key:
        _log("ERREUR: env LAFORGE_DB_KEY absente — requise pour migrate/verify.")
        sys.exit(1)
    return key


def _require_sqlcipher():
    try:
        from sqlcipher3 import dbapi2 as sqlcipher

        return sqlcipher
    except ImportError:
        _log("ERREUR: pysqlcipher3 absent. Installer: pip install pysqlcipher3")
        sys.exit(1)


def _enc_path(db: str) -> str:
    return db + ".enc"


def _first_table(db: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _count(conn, table: str) -> int:
    return conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]


def cmd_dry_run(db: str) -> int:
    if not os.path.isfile(db):
        _log(f"ERREUR: DB introuvable: {db}")
        return 1
    size_mb = os.path.getsize(db) / 1_048_576
    table = _first_table(db)
    _log("PLAN (aucune écriture):")
    _log(f"  source      : {db} ({size_mb:.1f} MiB)")
    _log(f"  backup       -> {db}.pre_sqlcipher.bak")
    _log(f"  chiffré      -> {_enc_path(db)}")
    _log(f"  table témoin : {table or '(aucune)'}")
    _log(f"  sqlcipher    : {'présent' if _has_cipher() else 'ABSENT (pip install pysqlcipher3)'}")
    _log(f"  clé          : {'LAFORGE_DB_KEY définie' if os.environ.get('LAFORGE_DB_KEY') else 'ABSENTE'}")
    _log("  swap auto    : NON (cutover manuel via forge_db_conn requis)")
    return 0


def _has_cipher() -> bool:
    try:
        import sqlcipher3  # noqa: F401

        return True
    except ImportError:
        return False


def cmd_migrate(db: str) -> int:
    if not os.path.isfile(db):
        _log(f"ERREUR: DB introuvable: {db}")
        return 1
    key = _require_key()
    sqlcipher = _require_sqlcipher()

    # (1) BACKUP obligatoire
    bak = db + ".pre_sqlcipher.bak"
    try:
        _log(f"backup {db} -> {bak}")
        shutil.copy2(db, bak)
    except OSError as e:
        _log(f"ERREUR: backup échoué ({e}) — abandon, rien n'a été modifié.")
        return 1
    if not os.path.isfile(bak) or os.path.getsize(bak) != os.path.getsize(db):
        _log("ERREUR: backup incomplet — abandon.")
        return 1

    enc = _enc_path(db)
    if os.path.exists(enc):
        _log(f"ERREUR: {enc} existe déjà — déplacer/supprimer avant relance.")
        return 1

    # (2)+(3) sqlcipher_export depuis la source en clair
    safe_path = enc.replace("'", "''")
    safe_key = key.replace("'", "''")
    _log(f"export chiffré -> {enc}")
    conn = sqlite3.connect(db)
    try:
        conn.execute(f"ATTACH DATABASE '{safe_path}' AS enc KEY '{safe_key}'")
        conn.execute("SELECT sqlcipher_export('enc')")
        conn.execute("DETACH DATABASE enc")
        conn.commit()
    except sqlite3.OperationalError as e:
        _log(f"ERREUR: sqlcipher_export indisponible via sqlite3 standard ({e}).")
        _log("  -> rejouer avec le binaire sqlcipher OU pysqlcipher3 côté source.")
        # Fallback : ouvrir la source via pysqlcipher3 (supporte sqlcipher_export)
        conn.close()
        conn = sqlcipher.connect(db)
        conn.execute(f"ATTACH DATABASE '{safe_path}' AS enc KEY '{safe_key}'")
        conn.execute("SELECT sqlcipher_export('enc')")
        conn.execute("DETACH DATABASE enc")
        conn.commit()
    finally:
        conn.close()

    _log("OK migration produite. Original INTACT.")
    _log("Étapes cutover (MANUELLES, à valider) :")
    _log(f"  1. python tools/forge_db_encrypt_migrate.py --db {db} --verify")
    _log(f"  2. router TOUS les readers vers app/forge_db_conn.get_db()")
    _log(f"  3. seulement ensuite: remplacer {db} par {enc} (garder {bak})")
    return 0


def cmd_verify(db: str) -> int:
    enc = _enc_path(db)
    if not os.path.isfile(enc):
        _log(f"ERREUR: {enc} introuvable — lancer --migrate d'abord.")
        return 1
    key = _require_key()
    sqlcipher = _require_sqlcipher()
    table = _first_table(db) if os.path.isfile(db) else None

    safe_key = key.replace("'", "''")
    conn = sqlcipher.connect(enc)
    try:
        conn.execute(f"PRAGMA key='{safe_key}'")
        ver = conn.execute("PRAGMA cipher_version").fetchone()
        if not ver:
            _log("ERREUR: PRAGMA cipher_version vide — DB non chiffrée ?")
            return 1
        _log(f"cipher_version = {ver[0]}")
        if table:
            n_enc = _count(conn, table)
            plain = sqlite3.connect(db)
            n_plain = _count(plain, table)
            plain.close()
            _log(f"table '{table}': enc={n_enc} plain={n_plain}")
            if n_enc != n_plain:
                _log("ERREUR: comptes divergents — migration suspecte.")
                return 1
        _log("VERIFY OK — DB chiffrée lisible avec la clé, comptes cohérents.")
        return 0
    except Exception as e:  # mauvaise clé -> exception SQLCipher
        _log(f"ERREUR: ouverture chiffrée échouée ({e}) — mauvaise clé ?")
        return 1
    finally:
        conn.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Migration at-rest SQLCipher (copie chiffrée, sans swap).")
    p.add_argument("--db", required=True, help="Chemin de la DB sqlite source (ex: RAG/embeddings.db)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Afficher le plan sans rien écrire")
    g.add_argument("--migrate", action="store_true", help="Produire backup + <db>.enc chiffrée")
    g.add_argument("--verify", action="store_true", help="Vérifier <db>.enc avec la clé")
    args = p.parse_args(argv)

    if args.dry_run:
        return cmd_dry_run(args.db)
    if args.migrate:
        return cmd_migrate(args.db)
    if args.verify:
        return cmd_verify(args.db)
    return 2


if __name__ == "__main__":
    sys.exit(main())
