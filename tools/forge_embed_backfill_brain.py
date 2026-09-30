"""Backfill NULL chunks via brain_worker ZMQ direct (skip cascade router).

Brain_worker REP socket = 1 task simultane. Parallelisation par BATCH SIZE
non par workers Python. batch=32 = sweet spot AVX-512 znver4.

Usage :
    LAFORGE_PYTHON tools/forge_embed_backfill_brain.py --limit 250000
"""

import argparse
import json
import logging
import sqlite3
import struct
import time
from pathlib import Path

import msgpack
import zmq

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

logger = logging.getLogger("brain_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ZMQ_ENDPOINT = "tcp://127.0.0.1:5557"


def brain_embed(texts: list[str], timeout_s: float = 120.0) -> list[list[float]] | None:
    """Submit + poll brain_worker ZMQ."""
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, 10000)
    s.connect(ZMQ_ENDPOINT)
    try:
        s.send(msgpack.packb({"cmd": "submit", "type": "embed", "texts": texts}, use_bin_type=True))
        rep = msgpack.unpackb(s.recv(), raw=False)
        tid = rep.get("task_id")
        if not tid:
            return None

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(0.5)
            s.send(msgpack.packb({"cmd": "check", "task_id": tid}, use_bin_type=True))
            r = msgpack.unpackb(s.recv(), raw=False)
            status = r.get("status", "pending")
            if status == "completed":
                data = r.get("data", {})
                if isinstance(data, dict):
                    return data.get("vecs", [])
                if isinstance(data, list):
                    return data
                return None
            if status == "error":
                logger.warning(f"brain_worker error: {r.get('error')}")
                return None
        return None
    except Exception as e:
        logger.warning(f"brain_worker KO: {type(e).__name__}: {e}")
        return None
    finally:
        s.close()


def encode_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def backfill(limit: int, batch_size: int = 32) -> dict:
    conn = sqlite3.connect(str(DB), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    total_null = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL").fetchone()[
        0
    ]
    logger.info(f"NULL chunks: {total_null}")

    processed = 0
    success = 0
    t_start = time.time()

    while processed < limit:
        rows = conn.execute(
            "SELECT id, text FROM rag_chunks "
            "WHERE embedding IS NULL AND text IS NOT NULL "
            "AND length(text) > 50 "
            "ORDER BY ingested_at DESC LIMIT ?",
            (batch_size,),
        ).fetchall()
        if not rows:
            logger.info("no more NULL chunks")
            break

        t0 = time.time()
        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]
        vecs = brain_embed(texts, timeout_s=180.0)

        if vecs and len(vecs) == len(rows):
            for cid, vec in zip(ids, vecs):
                if vec and len(vec) >= 256:
                    conn.execute(
                        "UPDATE rag_chunks SET embedding=?, embedding_model='bge-m3' WHERE id=?",
                        (encode_blob(vec), cid),
                    )
                    success += 1
            conn.commit()
        processed += len(rows)

        dt = time.time() - t0
        elapsed = time.time() - t_start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total_null - processed) / rate if rate > 0 else 0
        logger.info(
            f"batch {len(rows)} in {dt:.1f}s ({1000 * dt / len(rows):.0f}ms/chunk) "
            f"| TOTAL processed={processed} success={success} "
            f"rate={rate * 60:.0f}/min ETA={eta / 60:.1f}min"
        )

    conn.close()
    return {
        "processed": processed,
        "success": success,
        "remaining_null": total_null - success,
        "elapsed_s": round(time.time() - t_start, 1),
        "rate_per_min": round(processed * 60 / max(1, time.time() - t_start), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=250000)
    ap.add_argument("--batch-size", type=int, default=32)
    args = ap.parse_args()
    print(json.dumps(backfill(args.limit, args.batch_size), indent=2))


if __name__ == "__main__":
    main()
