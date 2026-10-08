"""
forge_db_bootstrap.py — Restore DB depuis `data/seed/*.jsonl` git-tracked.

Cible : fresh-clone Nokido, embeddings.db absent ou neuve.
Charge les seeds JSONL produits par `forge_db_seed_export.py`.

PAS DE EMBEDDINGS — l'embedder (brain_worker / forge_rag_warmup) le fait
au démarrage en background.

USAGE :
    LAFORGE_PYTHON tools/forge_db_bootstrap.py
    LAFORGE_PYTHON tools/forge_db_bootstrap.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SEED_DIR = ROOT / "seed"
# Schema d'une installation NEUVE, copie de la base de reference (2026-10-07). Avant lui, cet outil renvoyait vers
# « forge_rag_warmup ou demarrer le hub », et sur machine vierge NI l'un NI l'autre ne creait rag_chunks (test
# d'installation sur runners GitHub : Linux « base absente », Windows fichier vide, pack refuse).
SCHEMA = SEED_DIR / "schema_base.sql"


def creer_schema(c) -> list[str]:
    """Applique seed/schema_base.sql (tout en IF NOT EXISTS : rejouable). Rend les tables presentes ensuite."""
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    return sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"))


def _table_exists(c, table: str) -> bool:
    return (
        c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        is not None
    )


def _columns(c, table: str) -> list[str]:
    return [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]


def import_jsonl(c, jsonl_path: Path, table: str, dry_run: bool = False) -> dict:
    if not _table_exists(c, table):
        return {
            "file": jsonl_path.name,
            "table": table,
            "skipped": "table absent — schema pas créé",
        }
    table_cols = set(_columns(c, table))

    rows = []
    skipped = 0
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                skipped += 1
                continue
            # Filter to existing table cols
            d = {k: v for k, v in d.items() if k in table_cols}
            if not d:
                skipped += 1
                continue
            rows.append(d)

    if dry_run:
        return {
            "file": jsonl_path.name,
            "table": table,
            "would_import": len(rows),
            "skipped": skipped,
            "dry_run": True,
        }

    n_inserted = 0
    n_replaced = 0
    for d in rows:
        keys = list(d.keys())
        placeholders = ",".join("?" for _ in keys)
        try:
            # INSERT OR IGNORE (preserve existing rows)
            cur = c.execute(
                f'INSERT OR IGNORE INTO "{table}" ({",".join(keys)}) VALUES ({placeholders})',
                [d[k] for k in keys],
            )
            if cur.rowcount > 0:
                n_inserted += 1
            else:
                n_replaced += 1
        except Exception:
            skipped += 1
    c.commit()
    return {
        "file": jsonl_path.name,
        "table": table,
        "inserted": n_inserted,
        "skipped_existing": n_replaced,
        "errors": skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-dir", default=str(SEED_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    seed_dir = Path(args.seed_dir)
    if not seed_dir.exists():
        print(f"ERR: seed dir absent: {seed_dir}")
        return 1

    manifest_path = seed_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            print(f"Manifest from {manifest.get('exported_at', '?')}")
        except Exception:
            pass

    if not SCHEMA.exists():
        print(f"ERR: schema de base absent ({SCHEMA}) : impossible de creer la base")
        return 1
    neuve = not DB.exists()
    if neuve and args.dry_run:
        print(f"DRY RUN : la base {DB} serait CREEE avec {SCHEMA.name}")
        return 0

    print(f"DB     : {DB}{' (creee)' if neuve else ''}")
    print(f"SEED   : {seed_dir}")
    print(f"DRY RUN: {args.dry_run}")

    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    if not args.dry_run:
        tables = creer_schema(c)
        print(f"SCHEMA : {SCHEMA.name} applique, rag_chunks {'PRESENTE' if 'rag_chunks' in tables else 'ABSENTE'}")
    print()

    # Pour chaque .jsonl, deviner la table (préfixe avant __ ou tout le nom)
    files = sorted(seed_dir.glob("*.jsonl"))
    total_inserted = 0
    for f in files:
        # Nom : <table>.jsonl OU <table>__<slug>.jsonl
        stem = f.stem
        table = stem.split("__")[0]
        r = import_jsonl(c, f, table, dry_run=args.dry_run)
        flag = "OK" if "inserted" in r or "would_import" in r else "SKIP"
        n = r.get("inserted", r.get("would_import", 0))
        total_inserted += n
        print(f"  [{flag}] {f.name:55} -> {table:25} +{n}")

    c.close()
    print(f"\nTOTAL inserted: {total_inserted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
