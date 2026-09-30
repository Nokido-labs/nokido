"""Backfill hybride : Jina v3 cloud (free 1M tok/mois) primaire,
brain_worker DirectML fallback quand quota Jina epuise OU erreur HTTP.

Skip Voyage (3 RPM sans CB). Skip Modal (credit epuise).
Respecte HOT_TIER_SQL si patche, mais here applique sur 3.3k restants legit
post-archive gitingest.

Usage : LAFORGE_PYTHON tools/forge_embed_backfill_hybrid.py
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("hybrid_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

JINA_URL = "https://api.jina.ai/v1/embeddings"


def _get_jina_key():
    try:
        from nokido_agent.app.forge_secrets import get_secret

        k = get_secret("JINA_API_KEY")
        if k:
            return k.strip()
    except Exception:
        pass
    import os

    return get_secret("JINA_API_KEY") or "".strip()


def jina_batch(texts, key, timeout=30.0):
    body = json.dumps(
        {
            "model": "jina-embeddings-v3",
            "task": "retrieval.passage",
            "dimensions": 1024,
            "input": [t[:8000] for t in texts],
        }
    ).encode()
    req = urllib.request.Request(
        JINA_URL,
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
        logger.warning(f"Jina HTTP {e.code}: {body}")
        return None
    except Exception as e:
        logger.warning(f"Jina KO: {type(e).__name__}: {e}")
        return None


def brain_batch(texts, timeout_s=180.0):
    import msgpack
    import zmq

    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, 10000)
    s.connect("tcp://127.0.0.1:5557")
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
            st = r.get("status", "pending")
            if st == "completed":
                d = r.get("data", {})
                return d.get("vecs", []) if isinstance(d, dict) else d
            if st == "error":
                logger.warning(f"brain_worker err: {r.get('error')}")
                return None
        return None
    except Exception as e:
        logger.warning(f"brain_worker KO: {e}")
        return None
    finally:
        s.close()


def encode_blob(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def backfill(limit=10000, jina_batch_size=128, brain_batch_size=32):
    jina_key = _get_jina_key()
    if not jina_key:
        logger.warning("JINA_API_KEY missing -> brain_worker only")
    else:
        logger.info(f"jina key OK (len={len(jina_key)})")

    conn = sqlite3.connect(str(DB), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")

    total_null = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL").fetchone()[
        0
    ]
    logger.info(f"NULL chunks: {total_null}")

    processed = 0
    success = 0
    jina_quota_exhausted = False
    t_start = time.time()

    while processed < limit:
        bs = brain_batch_size if jina_quota_exhausted or not jina_key else jina_batch_size
        rows = conn.execute(
            "SELECT id, text FROM rag_chunks "
            "WHERE embedding IS NULL AND text IS NOT NULL AND length(text) > 50 "
            "ORDER BY ingested_at DESC LIMIT ?",
            (bs,),
        ).fetchall()
        if not rows:
            logger.info("done")
            break

        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]

        t0 = time.time()
        vecs = None
        provider = ""

        if jina_key and not jina_quota_exhausted:
            vecs = jina_batch(texts, jina_key, timeout=30.0)
            provider = "jina"
            if vecs is None:
                # Check if quota exhausted (HTTP 402 / 429)
                logger.info("jina fail -> fallback brain_worker for this batch + future")
                jina_quota_exhausted = True
                vecs = brain_batch(texts, timeout_s=180.0)
                provider = "brain_worker"

        if vecs is None:
            vecs = brain_batch(texts, timeout_s=180.0)
            provider = "brain_worker"

        dt = time.time() - t0

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

        elapsed = time.time() - t_start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total_null - processed) / rate if rate > 0 else 0
        logger.info(
            f"[{provider:13}] batch {len(rows)} in {dt:.1f}s ({1000 * dt / len(rows):.0f}ms/chunk) "
            f"| TOTAL processed={processed} success={success} "
            f"rate={rate * 60:.0f}/min ETA={eta / 60:.1f}min"
        )

    conn.close()
    return {
        "processed": processed,
        "success": success,
        "jina_quota_exhausted": jina_quota_exhausted,
        "elapsed_s": round(time.time() - t_start, 1),
        "rate_per_min": round(processed * 60 / max(1, time.time() - t_start), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--jina-batch", type=int, default=128)
    ap.add_argument("--brain-batch", type=int, default=32)
    args = ap.parse_args()
    print(json.dumps(backfill(args.limit, args.jina_batch, args.brain_batch), indent=2))


if __name__ == "__main__":
    main()
