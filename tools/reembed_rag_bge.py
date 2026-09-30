#!/usr/bin/env python3
r"""
reembed_rag_bge.py — Re-embedder tous les chunks RAG avec bge-m3
=================================================================
Remplace les embeddings inhomogenes (dim 2032-2080) par bge-m3 (dim 1024).
Active ensuite les edges SEMANTIC du Graph-RAG.

Usage:
    cd %NOKIDO_WORKSPACE%\LaForge
    python tools\reembed_rag_bge.py                 # embed all
    python tools\reembed_rag_bge.py --batch 500      # embed 500 at a time
    python tools\reembed_rag_bge.py --build-graph     # rebuild Graph-RAG after
"""

from __future__ import annotations

import json
import sqlite3
import struct
import sys
import time
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

OLLAMA_URL = "http://localhost:11434"
MODEL = "bge-m3:latest"
DB_PATH = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
EXPECTED_DIM = 1024
MAX_TEXT = 2000  # bge-m3 context limit


def embed_text(text):
    payload = json.dumps({"model": MODEL, "prompt": text[:MAX_TEXT]}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get("embedding", [])


def vec_to_blob(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def needs_reembed(blob):
    if not blob:
        return True
    dim = len(blob) // 4
    return dim != EXPECTED_DIM


def main():
    batch_size = 500
    build_graph = False
    for i, arg in enumerate(sys.argv):
        if arg == "--batch" and i + 1 < len(sys.argv):
            batch_size = int(sys.argv[i + 1])
        if arg == "--build-graph":
            build_graph = True

    print(f"Re-embedding RAG chunks with {MODEL}")
    print(f"DB: {DB_PATH}")
    print(f"Batch size: {batch_size}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Count what needs work
    total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    rows = conn.execute("SELECT id, text, embedding FROM rag_chunks").fetchall()

    todo = [(cid, text) for cid, text, emb in rows if needs_reembed(emb)]
    already = total - len(todo)
    print(f"Total: {total}, need re-embed: {len(todo)}, already OK: {already}")

    if not todo:
        print("Nothing to do!")
        if build_graph:
            _build_graph(conn)
        conn.close()
        return

    # Process in batches
    done = 0
    errors = 0
    t0 = time.time()

    for i in range(0, min(len(todo), batch_size), 1):
        cid, text = todo[i]
        try:
            vec = embed_text(text)
            if len(vec) != EXPECTED_DIM:
                print(f"  WARN: {cid} dim={len(vec)} (expected {EXPECTED_DIM})")
                errors += 1
                continue
            blob = vec_to_blob(vec)
            conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (blob, cid))
            done += 1

            if done % 50 == 0:
                conn.commit()
                elapsed = time.time() - t0
                rate = done / elapsed
                eta = (min(len(todo), batch_size) - done) / rate / 60
                print(
                    f"  [{done}/{min(len(todo), batch_size)}] {rate:.1f} chunks/s, ETA: {eta:.1f} min"
                )
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"  ERROR {cid}: {e}")
            if errors == 5:
                print("  (suppressing further errors)")

    conn.commit()
    elapsed = time.time() - t0
    print(
        f"\nDone: {done} embedded, {errors} errors, {elapsed:.1f}s ({done / max(elapsed, 1):.1f} chunks/s)"
    )
    print(f"Remaining: {len(todo) - done}")

    if build_graph:
        _build_graph(conn)

    conn.close()


def _build_graph(conn):
    print("\nRebuilding Graph-RAG with SEMANTIC edges...")
    import sys as _sys

    _sys.path.insert(0, str(DB_PATH.parent.parent / "app"))
    from nokido_agent.app.forge_graph_rag import GraphRAG

    grag = GraphRAG(str(DB_PATH), semantic_threshold=0.75)
    stats = grag.build_graph()
    print(f"Graph: {stats}")


if __name__ == "__main__":
    main()
