"""
tools/forge_vendor_kb_ingest.py — Ingest vendor knowledge base into RAG.

Parse les fichiers Markdown du corpus netcfg-agent/docs/vendor_knowledge/
et ingere dans rag_chunks avec domain=vendor_cli.

Structure attendue des fichiers (produits par Gemini via prompt P4):
  docs/vendor_knowledge/
  ├── README.md
  ├── <vendor_key>/
  │   ├── models.yaml
  │   ├── 01_vlan_basic.md
  │   ├── 02_vlan_trunk.md
  │   ...
  │   └── 10_link_agg.md

Chaque fichier .md a un frontmatter YAML :
  ---
  vendor: huawei_vrp
  scenario: vlan_trunk
  tags: [vlan, trunk, l2]
  models_tested: [S5720, S6720]
  difficulty: intermediate
  ---

Strategie de chunking :
  - 1 chunk par section H2 (##) du markdown
  - Meta enrichi : vendor_key, scenario, tags, difficulty, section_title
  - source = "vendor_kb:{vendor}/{scenario}#{section_slug}"
  - domain = "vendor_cli"
  - role_hint = "network_reference"

Usage :
    python tools/forge_vendor_kb_ingest.py --root docs/vendor_knowledge/
    python tools/forge_vendor_kb_ingest.py --root docs/vendor_knowledge/ --dry-run
    python tools/forge_vendor_kb_ingest.py --vendor huawei_vrp  # ingère juste ce vendor

Integration RAG Nokido :
  - rag_chunks.domain = "vendor_cli"
  - Embedding automatique via brain_worker:5557 si dispo
  - Deduplication par source (UPSERT-like: delete old then insert)

Queries ulterieures (exemples) :
  SELECT text FROM rag_chunks
  WHERE domain = 'vendor_cli' AND source LIKE 'vendor_kb:huawei_vrp/%';

  SELECT text FROM rag_chunks
  WHERE domain = 'vendor_cli' AND text LIKE '%port trunk allow-pass%';
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ===================== Config =====================

# Le RAG Nokido est dans RAG/embeddings.db
DEFAULT_RAG_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
DEFAULT_VENDOR_ROOT = (
    Path(__file__).resolve().parent.parent.parent / "netcfg-agent" / "docs" / "vendor_knowledge"
)

# Vendors attendus (cohérence avec netcfg-agent)
EXPECTED_VENDORS = ["huawei_vrp", "hp_comware", "aruba_aoscx", "hp_procurve", "netgear_prosafe"]

# Taille max d'un chunk (caractères) avant split en sous-chunks
MAX_CHUNK_CHARS = 2000
MIN_CHUNK_CHARS = 80  # sous ça, on skip (trop court pour être utile)


# ===================== Data models =====================


@dataclass
class VendorChunk:
    """Un chunk a ingerer dans le RAG."""

    text: str
    source: str  # vendor_kb:<vendor>/<scenario>#<section>
    domain: str = "vendor_cli"
    role_hint: str = "network_reference"
    meta: dict = field(default_factory=dict)

    def as_sql_row(self) -> tuple:
        """Retourne (text, domain, role_hint, author, source, meta, ingested_at)."""
        from datetime import datetime

        return (
            self.text,
            self.domain,
            self.role_hint,
            "CLAUDE",
            self.source,
            json.dumps(self.meta, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        )


# ===================== Parsing =====================


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL | re.MULTILINE)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extrait le frontmatter YAML et retourne (meta, body_without_frontmatter)."""
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}, content

    fm_block = m.group(1)
    body = content[m.end() :]

    # Parse YAML simple (lines key: value ou key: [list])
    meta = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            # List : [a, b, c]
            if v.startswith("[") and v.endswith("]"):
                items = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
                meta[k] = items
            else:
                # String / scalar
                meta[k] = v.strip("\"'")
    return meta, body


def slug(text: str) -> str:
    """Transforme un titre en slug URL-safe."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:50]


def split_by_h2_sections(body: str) -> list[tuple[str, str]]:
    """Split un markdown body par sections H2 (##).

    Returns:
        Liste de (section_title, section_content_including_h2)
    """
    # Split par lignes commencant par "## "
    parts = re.split(r"^(## .+)$", body, flags=re.MULTILINE)

    sections = []
    # parts alterne : [avant-1er-H2, "## Titre1", contenu1, "## Titre2", contenu2, ...]
    # Premiere partie = intro avant tout H2 (souvent le H1 + context)
    if parts and parts[0].strip():
        first_h1 = re.search(r"^# (.+)$", parts[0], re.MULTILINE)
        title = first_h1.group(1) if first_h1 else "intro"
        sections.append((title, parts[0]))

    i = 1
    while i < len(parts):
        if i + 1 < len(parts):
            h2_line = parts[i]
            content = parts[i + 1]
            title = h2_line.replace("##", "").strip()
            sections.append((title, h2_line + content))
            i += 2
        else:
            i += 1

    return sections


def chunk_vendor_file(
    path: Path,
    vendor_root: Path,
) -> list[VendorChunk]:
    """Parse un fichier md et retourne la liste de chunks a ingerer."""
    content = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(content)

    # Determiner vendor + scenario depuis le chemin
    rel = path.relative_to(vendor_root)
    parts = rel.parts
    vendor_dir = parts[0] if len(parts) >= 2 else "unknown"
    scenario_file = path.stem  # "02_vlan_trunk" par ex

    # Si frontmatter est absent, deriver du chemin
    if "vendor" not in meta:
        meta["vendor"] = vendor_dir
    if "scenario" not in meta:
        # Strip prefix numerique "02_" -> "vlan_trunk"
        sc = re.sub(r"^\d+[_\-]", "", scenario_file)
        meta["scenario"] = sc

    # Split le body en sections H2
    sections = split_by_h2_sections(body)

    chunks = []
    for section_title, section_body in sections:
        # Split plus si > MAX_CHUNK_CHARS
        text = section_body.strip()
        if len(text) < MIN_CHUNK_CHARS:
            continue

        # Sub-split sur taille
        if len(text) > MAX_CHUNK_CHARS:
            # Split sur les blocs de code (preserve les ```) ou doubles newlines
            parts_sub = re.split(r"\n\n+", text)
            accumulator = ""
            sub_i = 0
            for p in parts_sub:
                if len(accumulator) + len(p) + 2 > MAX_CHUNK_CHARS and accumulator:
                    chunks.append(_mk_chunk(accumulator, path, meta, section_title, sub_idx=sub_i))
                    accumulator = p
                    sub_i += 1
                else:
                    accumulator = (accumulator + "\n\n" + p) if accumulator else p
            if accumulator:
                chunks.append(_mk_chunk(accumulator, path, meta, section_title, sub_idx=sub_i))
        else:
            chunks.append(_mk_chunk(text, path, meta, section_title))

    return chunks


def _mk_chunk(
    text: str,
    path: Path,
    meta: dict,
    section_title: str,
    sub_idx: int = 0,
) -> VendorChunk:
    """Helper : cree un VendorChunk avec source bien forme."""
    section_slug_s = slug(section_title)
    vendor = meta.get("vendor", "unknown")
    scenario = meta.get("scenario", path.stem)
    source = f"vendor_kb:{vendor}/{scenario}#{section_slug_s}"
    if sub_idx > 0:
        source += f"-chunk{sub_idx}"

    chunk_meta = {
        "vendor": vendor,
        "scenario": scenario,
        "section": section_title,
        "tags": meta.get("tags", []),
        "models_tested": meta.get("models_tested", []),
        "difficulty": meta.get("difficulty", "unknown"),
        "file_path": str(path.name),
        "sub_chunk": sub_idx,
    }

    return VendorChunk(
        text=text,
        source=source,
        meta=chunk_meta,
    )


# ===================== Ingest =====================


def ingest_to_sqlite(
    chunks: list[VendorChunk],
    db_path: Path,
    dry_run: bool = False,
) -> dict:
    """Insere les chunks dans rag_chunks.

    Strategie :
      1. DELETE WHERE source = vendor_kb:<same>  (upsert-like)
      2. INSERT chaque chunk

    Returns:
        Stats : {inserted: N, deleted: N, errors: [...]}
    """
    stats = {"inserted": 0, "deleted": 0, "skipped": 0, "errors": []}

    if dry_run:
        for c in chunks:
            stats["inserted"] += 1
        return stats

    if not db_path.exists():
        stats["errors"].append(f"RAG DB not found: {db_path}")
        return stats

    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        # Check schema
        cur = conn.execute("PRAGMA table_info(rag_chunks)")
        cols = [r[1] for r in cur.fetchall()]
        has_meta_col = "meta" in cols

        # Delete anciens chunks du meme vendor_kb (idempotence)
        sources_to_del = list(set(c.source for c in chunks))
        if sources_to_del:
            placeholders = ",".join("?" * len(sources_to_del))
            n = conn.execute(
                f"DELETE FROM rag_chunks WHERE source IN ({placeholders})",
                sources_to_del,
            ).rowcount
            stats["deleted"] = n

        # Insert (adapte au schema)
        for c in chunks:
            try:
                row = c.as_sql_row()
                # 2026-09-12 : les deux branches omettaient `id` (TEXT PRIMARY KEY),
                # laissant la clef NULLE. row = (text, domain, role_hint, author,
                # source, meta, ingested_at) -> la source est en [4], le texte en [0].
                from nokido_agent.app.forge_db_path import chunk_id as _cid  # type: ignore

                _id = _cid(row[4], row[0])
                if has_meta_col:
                    conn.execute(
                        "INSERT INTO rag_chunks (id, text, domain, role_hint, author, source, meta, ingested_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (_id,) + tuple(row),
                    )
                else:
                    # Fallback sans colonne meta
                    conn.execute(
                        "INSERT INTO rag_chunks (id, text, domain, role_hint, author, source, ingested_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (_id, row[0], row[1], row[2], row[3], row[4], row[6]),
                    )
                stats["inserted"] += 1
            except sqlite3.Error as e:
                stats["errors"].append(f"{c.source}: {e}")

        conn.commit()
    finally:
        conn.close()

    return stats


# ===================== CLI =====================


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest vendor knowledge base into RAG")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_VENDOR_ROOT,
        help=f"Racine du corpus (default: {DEFAULT_VENDOR_ROOT})",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_RAG_DB, help=f"Chemin DB RAG (default: {DEFAULT_RAG_DB})"
    )
    parser.add_argument(
        "--vendor", type=str, default=None, help="Ingest un seul vendor (default: tous)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Ne pas ecrire en DB, juste compter")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"ERR: vendor root not found: {args.root}", file=sys.stderr)
        return 1

    # Collecter les fichiers md (hors README)
    md_files = []
    vendors_found = set()
    for p in sorted(args.root.rglob("*.md")):
        if p.name.lower() == "readme.md":
            continue
        rel = p.relative_to(args.root)
        if len(rel.parts) < 2:
            continue  # fichier racine autre que README
        vendor = rel.parts[0]
        if args.vendor and vendor != args.vendor:
            continue
        md_files.append(p)
        vendors_found.add(vendor)

    print("=== Vendor KB ingest ===")
    print(f"  Root       : {args.root}")
    print(f"  DB         : {args.db}")
    print(f"  Files found: {len(md_files)}")
    print(f"  Vendors    : {sorted(vendors_found)}")

    if not md_files:
        print("  No files to ingest.")
        return 0

    # Chunker
    all_chunks = []
    for md in md_files:
        try:
            chunks = chunk_vendor_file(md, args.root)
            all_chunks.extend(chunks)
            if args.verbose:
                print(f"  {md.relative_to(args.root)} -> {len(chunks)} chunks")
        except Exception as e:
            print(f"  ERR parsing {md}: {e}", file=sys.stderr)

    print(f"\n  Total chunks produced: {len(all_chunks)}")

    # Ingest
    stats = ingest_to_sqlite(all_chunks, args.db, dry_run=args.dry_run)
    prefix = "[DRY-RUN] " if args.dry_run else ""
    print(f"\n  {prefix}Deleted  : {stats['deleted']}")
    print(f"  {prefix}Inserted : {stats['inserted']}")
    print(f"  {prefix}Skipped  : {stats['skipped']}")
    if stats["errors"]:
        print(f"\n  ERRORS ({len(stats['errors'])}):")
        for e in stats["errors"][:10]:
            print(f"    - {e}")

    return 0 if not stats["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
