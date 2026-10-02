#!/usr/bin/env python3
"""
ingest_pdf.py — Ingère un PDF dans le RAG via MarkdownChunker (forge_rag_store).

Workflow:
  1. Extrait le texte brut (pdfplumber)
  2. Convertit en pseudo-markdown (détection chapitres/sections par patterns typiques)
  3. MarkdownChunker → chunks sémantiques avec header_path dans le texte
  4. INSERT OR IGNORE dans rag_chunks + FTS rebuild

Usage:
  LAFORGE_PYTHON tools/ingest_pdf.py <pdf> [--domain vitis_ai] [--max-chunk 1600]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RAG_DB = ROOT / "RAG" / "embeddings.db"
FTS_LOCK = ROOT / "RAG" / "fts_rebuild.lock"
import time as _time


def _wait_fts_lock(max_wait: int = 120) -> None:
    waited = 0
    while FTS_LOCK.exists() and waited < max_wait:
        print(f"  FTS rebuild en cours, attente 2s... ({waited}s)")
        _time.sleep(2)
        waited += 2
    if waited >= max_wait:
        print(f"  FTS lock stale après {max_wait}s — suppression forcée")
        FTS_LOCK.unlink(missing_ok=True)


def extract_text(pdf_path: Path) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ""
            pages.append(t)
    return "\n".join(pages)


def pdf_text_to_markdown(text: str) -> str:
    """Heuristique : convertit texte PDF brut en pseudo-markdown pour MarkdownChunker.

    Détecte les lignes-titres typiques de PDFs techniques AMD/UG14xx :
    - "Chapter N: Title" → ## Chapter N: Title
    - Lignes ALL CAPS courtes → ### Title
    - "Figure N:" / "Table N:" → conservées telles quelles
    """
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        # Chapter headings
        if re.match(r"^Chapter\s+\d+[:.]?\s+\w", stripped):
            lines.append(f"## {stripped}")
        # Section headings: ligne courte (<80 chars) qui ne finit pas par . ou ,
        elif (
            len(stripped) < 80
            and not stripped.endswith((".", ",", ";", ":"))
            and re.match(r"^[A-Z][A-Za-z0-9 \-/()]+$", stripped)
            and len(stripped.split()) >= 2
        ):
            lines.append(f"### {stripped}")
        else:
            lines.append(stripped)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", help="Chemin vers le PDF")
    parser.add_argument("--domain", default="vitis_ai")
    parser.add_argument(
        "--max-chunk",
        type=int,
        default=1600,
        help="Max chars par chunk MarkdownChunker (défaut 1600)",
    )
    parser.add_argument("--overlap", type=int, default=200)
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Fichier non trouvé: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    from nokido_agent.app.forge_rag_store import MarkdownChunker
    from nokido_agent.app.forge_self_correction import rebuild_fts_index

    print(f"Extraction texte: {pdf_path.name}...")
    raw = extract_text(pdf_path)
    print(f"  {len(raw):,} chars bruts")

    md = pdf_text_to_markdown(raw)
    print(f"  Converti en pseudo-markdown ({md.count(chr(10))} lignes)")

    chunks = MarkdownChunker.chunk(md, max_chunk_chars=args.max_chunk, overlap_chars=args.overlap)
    print(f"  {len(chunks)} chunks via MarkdownChunker")

    _wait_fts_lock()
    con = sqlite3.connect(str(RAG_DB), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")

    inserted = 0
    for i, chunk in enumerate(chunks):
        header_path = chunk.get("header_path", "")
        text = chunk["text"]
        # Préfixer avec le header_path pour enrichir le contexte sémantique
        full_text = f"[{header_path}]\n{text}" if header_path else text
        if len(full_text.strip()) < 80:
            continue

        src = f"{args.domain}:{pdf_path.stem}#chunk{i}"
        chunk_id = hashlib.sha256((src + full_text[:80]).encode()).hexdigest()[:16]
        cur = con.execute(
            "INSERT OR IGNORE INTO rag_chunks (id, source, domain, text) SELECT ?,?,?,? "
            "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
            (chunk_id, src, args.domain, full_text, chunk_id),
        )
        if cur.rowcount:
            inserted += 1

    con.commit()
    con.close()
    print(f"Inserted {inserted}/{len(chunks)} chunks → domain={args.domain}")

    print("FTS rebuild...")
    result = rebuild_fts_index()
    print(f"FTS: {result}")


if __name__ == "__main__":
    main()
