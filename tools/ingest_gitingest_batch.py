"""
tools/ingest_gitingest_batch.py — Batch ingest data/gitingest/*.txt into RAG
Usage: hub run action=python code="exec(open('tools/ingest_gitingest_batch.py').read())"
"""

import hashlib
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GITINGEST_DIR = ROOT / "data" / "gitingest"
DB_PATH = ROOT / "RAG" / "embeddings.db"
INDEXED_FILE = GITINGEST_DIR / ".rag_indexed"
CHUNK_SIZE = 1200
OVERLAP = 150
DOMAIN = "gitingest"


def sha256_id(source, text):
    return hashlib.sha256((source + text).encode()).hexdigest()[:16]


def chunk_text(text, size=CHUNK_SIZE, overlap=OVERLAP):
    lines = text.splitlines(keepends=True)
    chunks, buf, buf_len = [], [], 0
    for line in lines:
        buf.append(line)
        buf_len += len(line)
        if buf_len >= size:
            chunks.append("".join(buf))
            ol, ol_len = [], 0
            for l in reversed(buf):
                ol_len += len(l)
                ol.insert(0, l)
                if ol_len >= overlap:
                    break
            buf, buf_len = ol, ol_len
    if buf:
        chunks.append("".join(buf))
    return chunks


def main():
    indexed = set()
    if INDEXED_FILE.exists():
        indexed = set(INDEXED_FILE.read_text().splitlines())

    files = sorted(
        [f for f in GITINGEST_DIR.iterdir() if f.suffix == ".txt" and f.stem not in indexed]
    )
    print(f"[batch] {len(files)} fichiers restants")

    con = sqlite3.connect(str(DB_PATH))
    con.execute("""CREATE TABLE IF NOT EXISTS rag_chunks
        (id TEXT PRIMARY KEY, text TEXT, source TEXT,
         domain TEXT DEFAULT 'code', role_hint TEXT,
         ingested_at REAL)""")
    total = 0
    t0 = time.time()

    for fpath in files:
        repo = fpath.stem
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  [SKIP] {repo}: {e}")
            continue

        chunks = chunk_text(text)
        inserted = 0
        for chunk in chunks:
            if len(chunk.strip()) < 50:
                continue
            src = f"gitingest/{repo}"
            cid = sha256_id(src, chunk)
            con.execute(
                "INSERT OR IGNORE INTO rag_chunks(id,text,source,domain,role_hint,ingested_at) VALUES(?,?,?,?,?,?)",
                (cid, chunk, src, DOMAIN, "code", time.time()),
            )
            if con.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        con.commit()

        with open(INDEXED_FILE, "a") as f:
            f.write(repo + "\n")
        total += inserted
        print(f"  [OK] {repo}: {len(chunks)} chunks, {inserted} new ({time.time() - t0:.1f}s)")

    # Rebuild FTS
    try:
        con.execute("INSERT INTO rag_fts(rag_fts) VALUES('rebuild')")
        con.commit()
        print("[OK] FTS rebuilt")
    except Exception as e:
        print(f"[WARN] FTS: {e}")

    con.close()
    print(f"[batch] DONE — {total} chunks, {len(files)} repos, {time.time() - t0:.1f}s")


main()
