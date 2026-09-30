"""Backfill NULL chunks via Voyage AI direct (skip cascade router).

Batch=128 max Voyage, workers=8 parallel HTTPS. Lit VOYAGE_API_KEY via
get_secret (vault DPAPI) ou env fallback.

Usage :
    LAFORGE_PYTHON tools/forge_embed_backfill_voyage.py --limit 250000
"""

import argparse
import json
import logging
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("voyage_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


def _get_key():
    key = None
    try:
        from nokido_agent.app.forge_secrets import get_secret

        key = get_secret("VOYAGE_API_KEY")
    except Exception:
        pass
    if not key:
        import os

        key = get_secret("VOYAGE_API_KEY") or ""
    if not key:
        raise RuntimeError("VOYAGE_API_KEY missing (vault + env)")
    return key.strip()


def voyage_batch(texts: list[str], key: str, timeout: float = 30.0) -> list[list[float]] | None:
    body = json.dumps(
        {
            "model": "voyage-3",
            "input": [t[:8000] for t in texts[:128]],
            "input_type": "document",
            "output_dimension": 1024,
        }
    ).encode()
    req = urllib.request.Request(
        VOYAGE_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Mozilla/5.0 LaForge-Embed",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        items = data.get("data", [])
        return [it.get("embedding") for it in items if it.get("embedding")]
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode("utf-8", errors="replace")
        logger.warning(f"voyage HTTP {e.code}: {body}")
        return None
    except Exception as e:
        logger.warning(f"voyage KO: {type(e).__name__}: {e}")
        return None


def encode_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def backfill(
    limit: int, batch_size: int = 128, max_workers: int = 8, dry_run: bool = False
) -> dict:
    if batch_size > 128:
        batch_size = 128
        logger.info("batch_size capped 128 (Voyage limit)")

    key = _get_key()
    logger.info(f"voyage key OK (len={len(key)})")

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
        # Fetch larger pool for parallelization
        pool_size = min(limit - processed, batch_size * max_workers * 4)
        rows = conn.execute(
            "SELECT id, text FROM rag_chunks "
            "WHERE embedding IS NULL AND text IS NOT NULL "
            "AND length(text) > 50 "
            "ORDER BY ingested_at DESC LIMIT ?",
            (pool_size,),
        ).fetchall()
        if not rows:
            logger.info("no more NULL chunks")
            break

        # Split en sous-batches de batch_size (128 max Voyage)
        sub_batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
        t0 = time.time()
        n_batch = len(rows)

        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(voyage_batch, [r[1] for r in sb], key): sb for sb in sub_batches}
            for fut in as_completed(futures):
                sb = futures[fut]
                vecs = fut.result()
                if vecs and len(vecs) == len(sb):
                    if not dry_run:
                        for (cid, _), vec in zip(sb, vecs):
                            if vec and len(vec) >= 256:
                                conn.execute(
                                    "UPDATE rag_chunks SET embedding=? WHERE id=?",
                                    (encode_blob(vec), cid),
                                )
                                success += 1
                    else:
                        success += len(vecs)
                processed += len(sb)
        if not dry_run:
            conn.commit()

        dt = time.time() - t0
        elapsed = time.time() - t_start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total_null - processed) / rate if rate > 0 else 0
        logger.info(
            f"  batch {n_batch} in {dt:.1f}s ({1000 * dt / n_batch:.0f}ms/chunk) "
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
        "dry_run": dry_run,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=250000)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(
        json.dumps(backfill(args.limit, args.batch_size, args.max_workers, args.dry_run), indent=2)
    )


if __name__ == "__main__":
    main()
