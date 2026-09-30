#!/usr/bin/env python3
"""forge_qdrant_fill.py — Remplissage de la collection Qdrant depuis embeddings.db.

Chantier SSoT RAG 2026 (COMMUNICATIONS.md 2026-07-06). Streame rag_chunks
(embedding IS NOT NULL), décode les blobs (float32/JSON via forge_faiss_sidecar.
_decode_emb), filtre NaN/Inf (72 blobs corrompus recensés le 2026-07-06), et
upserte par lots via forge_qdrant_sidecar.upsert_chunks (garde DISK_PRESSURE
incluse). Idempotent par chunk_id -> relançable après crash/reboot.

Cible par défaut : serveur Qdrant NATIF :6334 (gRPC, ~1700 pts/s mesuré).
Jamais le local mode qdrant-client pour >20k points (python brute-force).

Usage (job détaché) :
  LAFORGE_PYTHON tools/forge_qdrant_fill.py [--db %NOKIDO_DATA%\\embeddings.db]
      [--host 127.0.0.1] [--grpc-port 6334] [--batch 512]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from qdrant_client import QdrantClient

from nokido_agent.tools.forge_faiss_sidecar import _decode_emb
from nokido_agent.tools.forge_qdrant_sidecar import COLLECTION_NAME, init_sovereign_db, upsert_chunks


def fill(db: str, host: str, grpc_port: int, batch_size: int) -> dict:
    client = QdrantClient(host=host, grpc_port=grpc_port, prefer_grpc=True, timeout=120)
    init_sovereign_db(client=client)

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, embedding, source, domain FROM rag_chunks WHERE embedding IS NOT NULL"
    )

    total = ok = bad = 0
    t0 = time.time()
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        batch = []
        for cid, blob, source, domain in rows:
            v = _decode_emb(blob)
            if v is None or not np.isfinite(v).all():
                bad += 1
                continue
            batch.append(
                {"id": cid, "dense": v.tolist(), "path": source or "", "domain": domain or ""}
            )
        if batch:
            try:
                ok += upsert_chunks(client, batch)
            except Exception as be:  # noqa: BLE001 — un point pourri ne tue pas le job
                print(f"batch KO ({be}) -> point par point", flush=True)
                for item in batch:
                    try:
                        ok += upsert_chunks(client, [item])
                    except Exception:
                        bad += 1
                        print(f"point rejeté: {item['id']}", flush=True)
        total += len(rows)
        if total % (batch_size * 40) < batch_size:
            rate = total / max(1.0, time.time() - t0)
            print(f"{total} lus | {ok} upsertés | {bad} invalides | {rate:.0f}/s", flush=True)

    conn.close()
    info = client.get_collection(COLLECTION_NAME)
    res = {"lus": total, "upsertes": ok, "invalides": bad,
           "points": info.points_count, "secondes": int(time.time() - t0)}
    print("DONE", res, flush=True)
    return res


def main() -> int:
    p = argparse.ArgumentParser(description="Remplissage collection Qdrant depuis embeddings.db")
    p.add_argument("--db", default=r"%NOKIDO_DATA%\embeddings.db")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--grpc-port", type=int, default=6334)
    p.add_argument("--batch", type=int, default=512)
    a = p.parse_args()
    fill(a.db, a.host, a.grpc_port, a.batch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
