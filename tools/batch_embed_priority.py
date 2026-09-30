#!/usr/bin/env python3
"""
Batch embed nokido_code + forge_core domains (missing embeddings).
Uses brain_worker ZMQ :5557 for NPU-accelerated embeddings.
Also ingests gitingest_nokido.txt into RAG domain=nokido_digest.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def zmq_embed_batch(sock, texts: list, timeout_s: int = 60) -> list:
    """Submit embed task, poll until completed. Returns list of vectors."""
    import time

    import msgpack

    # submit
    sock.send(
        msgpack.packb(
            {"cmd": "submit", "type": "embed", "texts": texts, "priority": 5}, use_bin_type=True
        )
    )
    raw = sock.recv()
    resp = msgpack.unpackb(raw, raw=False)
    task_id = resp.get("task_id") or resp.get("data", {})
    if not task_id:
        raise RuntimeError(f"submit failed: {resp}")

    # poll check
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        sock.send(msgpack.packb({"cmd": "check", "task_id": task_id}, use_bin_type=True))
        raw = sock.recv()
        r = msgpack.unpackb(raw, raw=False)
        status = r.get("status") or (r.get("data", {}) or {}).get("status", "")
        if status == "completed":
            data = r.get("data", r)
            vecs = data.get("vecs", data.get("embeddings", data.get("vectors", [])))
            return vecs
        if status == "error":
            raise RuntimeError(f"embed error: {r}")
        time.sleep(0.05)
    raise TimeoutError(f"embed timeout after {timeout_s}s")


def embed_missing(domain: str, batch_size: int = 32):
    import sqlite3
    import struct

    import zmq

    con = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"))
    cur = con.cursor()
    cur.execute(
        "SELECT id, text FROM rag_chunks WHERE domain=? AND embedding IS NULL LIMIT 5000", (domain,)
    )
    rows = cur.fetchall()
    if not rows:
        print(f"[{domain}] nothing to embed")
        con.close()
        return 0

    print(f"[{domain}] {len(rows)} chunks to embed via brain_worker...")

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect("tcp://127.0.0.1:5557")
    sock.setsockopt(zmq.RCVTIMEO, 10000)

    done = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]
        try:
            vecs = zmq_embed_batch(sock, texts, timeout_s=90)
            if not vecs:
                print(f"  [{domain}] empty vecs at batch {i}")
                continue
            for rid, vec in zip(ids, vecs):
                blob = struct.pack(f"{len(vec)}f", *vec)
                con.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (blob, rid))
            con.commit()
            done += len(batch)
            if done % 256 == 0 or i == 0:
                print(f"  [{domain}] {done}/{len(rows)} embedded (dim={len(vecs[0])})")
        except zmq.error.Again:
            print(f"  [{domain}] ZMQ timeout at batch {i}")
            break
        except Exception as e:
            print(f"  [{domain}] error at {i}: {e}")
            break

    sock.close()
    ctx.term()
    con.close()
    print(f"[{domain}] done: {done} embedded")
    return done


def ingest_gitingest():
    digest = ROOT / "docs" / "gitingest_nokido.txt"
    if not digest.exists():
        print("gitingest_nokido.txt not found, skip ingest")
        return
    try:
        from nokido_agent.app.forge_rag_store import ingest_text

        text = digest.read_text(encoding="utf-8", errors="replace")
        chunks = ingest_text(
            text, source="gitingest:nokido", domain="nokido_digest", chunk_size=1200, overlap=100
        )
        print(f"Ingested gitingest: {chunks} chunks into nokido_digest domain")
    except Exception as e:
        print(f"ingest error: {e}")


if __name__ == "__main__":
    print("batch_embed_priority START", flush=True)
    t0 = time.time()
    # ingest_gitingest() — already done via tools/ingest_gitingest.py
    for dom in ["nokido_code", "forge_core", "nokido_digest", "general"]:
        embed_missing(dom, batch_size=32)
    print(f"Total time: {time.time() - t0:.1f}s", flush=True)
