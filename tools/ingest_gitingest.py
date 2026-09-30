#!/usr/bin/env python3
"""Ingest gitingest_nokido.txt into RAG domain=nokido_digest."""

import hashlib
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DIGEST_FILE = ROOT / "docs" / "gitingest_nokido.txt"
DB_PATH = ROOT / "RAG" / "embeddings.db"
DOMAIN = "nokido_digest"
CHUNK_SIZE = 1200
OVERLAP = 150


def sha256_id(source: str, text: str) -> str:
    return hashlib.sha256((source + text).encode()).hexdigest()[:16]


def chunk_text(text: str, size: int, overlap: int):
    lines = text.splitlines(keepends=True)
    chunks, buf, buf_len = [], [], 0
    for line in lines:
        buf.append(line)
        buf_len += len(line)
        if buf_len >= size:
            chunks.append("".join(buf))
            # keep overlap
            overlap_lines, overlap_len = [], 0
            for l in reversed(buf):
                overlap_len += len(l)
                overlap_lines.insert(0, l)
                if overlap_len >= overlap:
                    break
            buf, buf_len = overlap_lines, overlap_len
    if buf:
        chunks.append("".join(buf))
    return chunks


def main():
    if not DIGEST_FILE.exists():
        print("ERROR: gitingest_nokido.txt not found")
        sys.exit(1)

    text = DIGEST_FILE.read_text(encoding="utf-8", errors="replace")
    print(f"Input: {len(text):,} chars")

    # Split by section then chunk
    sections = text.split("=" * 80)
    all_chunks = []
    for sec in sections:
        sec = sec.strip()
        if len(sec) < 100:
            continue
        header = sec.split("\n")[0][:80]
        for chunk in chunk_text(sec, CHUNK_SIZE, OVERLAP):
            if len(chunk.strip()) < 50:
                continue
            all_chunks.append((header, chunk))

    print(f"Chunks: {len(all_chunks)}")

    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()

    # Drop existing nokido_digest to avoid duplicates
    cur.execute("DELETE FROM rag_chunks WHERE domain=?", (DOMAIN,))
    deleted = cur.rowcount
    print(f"Cleared {deleted} old nokido_digest chunks")

    inserted = 0
    t0 = time.time()
    for i, (header, chunk) in enumerate(all_chunks):
        source = f"gitingest:nokido/{header[:50]}"
        cid = sha256_id(source, chunk)
        cur.execute(
            "INSERT OR IGNORE INTO rag_chunks (id,text,source,domain,role_hint) VALUES (?,?,?,?,?)",
            (cid, chunk, source, DOMAIN, "code"),
        )
        if cur.rowcount:
            inserted += 1
        if i % 500 == 0 and i > 0:
            con.commit()
            print(f"  {i}/{len(all_chunks)} inserted={inserted} ({time.time() - t0:.1f}s)")

    con.commit()

    # Rebuild FTS
    try:
        cur.execute("INSERT INTO rag_fts(rag_fts) VALUES('rebuild')")
        con.commit()
        print("FTS rebuilt")
    except Exception as e:
        print(f"FTS rebuild: {e}")

    con.close()
    print(f"\nDone: {inserted} chunks inserted in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
