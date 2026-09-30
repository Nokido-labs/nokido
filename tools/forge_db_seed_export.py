"""
forge_db_seed_export.py — Export précieux DB vers JSONL git-trackable.

Sélectionne les tables PRÉCIEUSES (anchors, biblio promoted, configs,
curated_skills, ADR, system_rules, profiles agents) et les sauve en
JSONL dans `data/seed/`. Versionable git.

PAS EXPORTÉ : rag_snapshots, network_log, agent_messages, conversation_log,
shared_prompt_log, rag_fts_* (régénérables), embedding BLOB (rebuild auto).

USAGE :
    LAFORGE_PYTHON tools/forge_db_seed_export.py
    LAFORGE_PYTHON tools/forge_db_seed_export.py --dry-run

Réutilisé par forge_db_bootstrap.py pour restore fresh-clone.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SEED_DIR = ROOT / "seed"

# Tables précieuses à exporter (nom_table, condition WHERE optionnelle, cols à conserver)
# Cols=None = tout sauf embedding/blobs
EXPORTS = [
    # Lessons anchored — coeur capitalisation
    (
        "rag_chunks",
        "id LIKE 'lesson_sol_%' OR id LIKE 'lesson_err_%'",
        ["id", "source", "text", "domain", "meta", "ingested_at", "hash"],
    ),
    # Skills curatés (forge_skill_curator output)
    (
        "rag_chunks",
        "domain='curated_skills'",
        ["id", "source", "text", "domain", "meta", "ingested_at", "hash"],
    ),
    # Biblio promoted (vérifiées humain)
    ("biblio_raw", "status='promoted'", None),
    ("biblio_topics", None, None),
    ("biblio_link", None, None),
    # ADR (architecture decision records)
    ("adr_records", None, None),
    # System rules (capabilities, configs ring)
    ("system_rules", None, None),
    # Agent profiles (capabilities, tier mapping)
    ("agent_profiles", None, None),
    # Forge entities (RBAC mapping)
    ("forge_entities", None, None),
    # Trajectoires importantes
    ("trajectories", None, None),
    # Skill registry (forge_agentic_engine state)
    ("commit_intel", None, None),
]


def _row_to_dict(cols: list[str], row: tuple) -> dict:
    out = {}
    for c, v in zip(cols, row):
        if isinstance(v, bytes):
            # Skip BLOBs (embeddings) — seed = pas de vecteurs
            continue
        out[c] = v
    return out


def _table_exists(conn, table: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return r is not None


def _columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def export_table(
    conn,
    table: str,
    where: str | None,
    cols_select: list[str] | None,
    out_dir: Path,
    dry_run: bool = False,
) -> dict:
    if not _table_exists(conn, table):
        return {"table": table, "skipped": "table absent"}
    all_cols = _columns(conn, table)
    if cols_select is None:
        # Exclure BLOB (embedding etc.)
        cols_select = [c for c in all_cols if c.lower() not in ("embedding",)]
    # Filtre cols qui existent
    cols_select = [c for c in cols_select if c in all_cols]
    if not cols_select:
        return {"table": table, "skipped": "no usable column"}

    sql = f'SELECT {",".join(cols_select)} FROM "{table}"'
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY rowid"

    try:
        rows = conn.execute(sql).fetchall()
    except Exception as e:
        return {"table": table, "where": where, "error": str(e)[:200]}

    # Nom de fichier : <table>[_<slug_where>].jsonl
    fname = table
    if where:
        slug = where.replace("=", "_").replace("'", "").replace(" ", "_")
        slug = "".join(ch for ch in slug if ch.isalnum() or ch in "_-")[:40]
        fname = f"{table}__{slug}"
    out_file = out_dir / f"{fname}.jsonl"

    if dry_run:
        return {
            "table": table,
            "where": where,
            "rows": len(rows),
            "file": str(out_file),
            "dry_run": True,
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    n_written = 0
    with open(out_file, "w", encoding="utf-8") as f:
        for row in rows:
            d = _row_to_dict(cols_select, row)
            f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
            n_written += 1
    size = out_file.stat().st_size
    return {
        "table": table,
        "where": where,
        "rows": n_written,
        "file": str(out_file.relative_to(ROOT)),
        "size_kb": round(size / 1024, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(SEED_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out_dir = Path(args.out)

    if not DB.exists():
        print(f"ERR: DB introuvable: {DB}")
        return 1

    print(f"DB     : {DB}")
    print(f"OUT    : {out_dir}")
    print(f"DRY RUN: {args.dry_run}")
    print()

    conn = sqlite3.connect(str(DB), timeout=30)
    total_rows = 0
    total_kb = 0
    manifest = {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "db_source": str(DB.relative_to(ROOT)),
        "exports": [],
    }
    for table, where, cols in EXPORTS:
        r = export_table(conn, table, where, cols, out_dir, dry_run=args.dry_run)
        manifest["exports"].append(r)
        n = r.get("rows", 0)
        kb = r.get("size_kb", 0)
        total_rows += n
        total_kb += kb
        label = f"{table}" + (f" WHERE {where[:40]}..." if where else "")
        flag = "OK" if "rows" in r else "SKIP"
        print(f"  [{flag}] {label:55} rows={n:>7,} size={kb:>7.1f} KB")
    conn.close()

    if not args.dry_run:
        manifest_path = out_dir / "manifest.json"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nManifest: {manifest_path.relative_to(ROOT)}")

    print(f"\nTOTAL: {total_rows:,} rows, {total_kb / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
