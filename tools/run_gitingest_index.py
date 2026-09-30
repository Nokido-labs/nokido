#!/usr/bin/env python
"""tools/run_gitingest_index.py — Indexe docs/gitingest_*.txt dans RAG."""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
DOCS = ROOT / "docs"
REPORT = ROOT / "sandbox" / "gitingest_index_report.json"

CHUNK_LINES = 500
OVERLAP = 50


def _chunk_lines(lines: list[str], size: int = CHUNK_LINES, overlap: int = OVERLAP) -> list[str]:
    chunks = []
    i = 0
    while i < len(lines):
        chunk = "\n".join(lines[i : i + size])
        if chunk.strip():
            chunks.append(chunk)
        i += size - overlap
    return chunks


def main() -> None:
    txt_files = sorted(DOCS.glob("gitingest_*.txt"))
    if not txt_files:
        print(f"[gitingest] aucun fichier gitingest_*.txt dans {DOCS}")
        return

    conn = sqlite3.connect(str(DB), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    total = 0
    per_file: dict[str, int] = {}

    for fp in txt_files:
        lines = fp.read_text("utf-8", errors="replace").splitlines()
        chunks = _chunk_lines(lines)
        source = f"gitingest/{fp.name}"
        count = 0
        for chunk in chunks:
            chunk_id = hashlib.sha256((source + chunk).encode()).hexdigest()[:16]
            conn.execute(
                "INSERT OR REPLACE INTO rag_chunks "
                "(id, text, source, domain, role_hint, embedding, quality_score, ingested_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (chunk_id, chunk, source, "gitingest", "codebase", None, 0.7, now),
            )
            count += 1
        per_file[fp.name] = count
        total += count
        print(f"  {fp.name}: {count} chunks")

    conn.commit()
    conn.close()

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(
        json.dumps({"nb_chunks": total, "files": per_file, "created_at": now}, indent=2),
        encoding="utf-8",
    )
    print(f"[gitingest] {total} chunks → {DB}")


if __name__ == "__main__":
    main()
