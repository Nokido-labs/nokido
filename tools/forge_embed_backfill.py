"""Rattrapage : vectorise tous les rag_chunks avec embedding=NULL via embed_router
batch + concurrent. Beaucoup plus rapide que NokidoEmbedTrigger sequentiel.

Stack :
  - Recupere N chunks NULL par lot
  - embed_batch_fast (batch=32, workers=4) cascade Modal>Jina>brain_worker
  - UPDATE rag_chunks SET embedding=BLOB
  - Repeat jusqu a 0 NULL ou --limit atteint

Throughput cible : 100-500 chunks/min (vs 2/sec avec embed sequential).

Usage :
    LAFORGE_PYTHON tools/forge_embed_backfill.py --limit 1000 --dry-run
    LAFORGE_PYTHON tools/forge_embed_backfill.py --limit 50000
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_embed_router import embed_batch_fast, encode_blob, health_providers  # noqa: E402

logger = logging.getLogger("embed_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def backfill(
    limit: int = 10000, batch_size: int = 32, max_workers: int = 4, dry_run: bool = False,
    domain: str | None = None,
) -> dict:
    """Vectorise les chunks NULL, eventuellement bornes a un DOMAINE.

    `domain` ajoute le 2026-09-04. Sans lui, ce rattrapage prend les chunks NULL
    dans l'ordre — dont les 626 646 que `forge_tier_guard` REFUSE par
    RAISE(IGNORE). Il depenserait des embeddings pour des UPDATE que le trigger
    annule en silence : le compteur monterait, la couverture non.

    Les paliers vectorisables sont dans `forge_memory_availability.VECTORISABLES` ;
    `episodic_memory` en fait partie.
    """
    if not DB.exists():
        return {"error": f"DB missing: {DB}"}

    health = health_providers()
    logger.info(f"providers: {health}")

    conn = sqlite3.connect(str(DB), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")

    # Compte initial. Filtre par domaine quand il est demande : compter les
    # 736 272 NULL globaux alors qu'on n'en traite qu'un sous-ensemble ferait
    # lire un progres de 0,3 % la ou le lot est termine.
    if domain:
        total_null = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL AND domain = ?",
            (domain,),
        ).fetchone()[0]
        logger.info(f"NULL embeddings to backfill (domain={domain}): {total_null}")
    else:
        total_null = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL"
        ).fetchone()[0]
        logger.info(f"NULL embeddings to backfill: {total_null}")

    processed = 0
    success = 0
    t_start = time.time()

    while processed < limit:
        remaining = min(limit - processed, batch_size * max_workers * 4)
        if domain:
            rows = conn.execute(
                "SELECT id, text FROM rag_chunks "
                "WHERE embedding IS NULL AND text IS NOT NULL "
                "AND length(text) > 50 AND domain = ? "
                "ORDER BY ingested_at DESC LIMIT ?",
                (domain, remaining),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, text FROM rag_chunks "
                "WHERE embedding IS NULL AND text IS NOT NULL "
                "AND length(text) > 50 "
                "ORDER BY ingested_at DESC LIMIT ?",
                (remaining,),
            ).fetchall()
        if not rows:
            logger.info("no more NULL chunks to process")
            break

        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]

        logger.info(f"processing batch of {len(texts)} chunks...")
        t0 = time.time()
        vecs = embed_batch_fast(texts, batch_size=batch_size, max_workers=max_workers)
        dt = time.time() - t0
        ok_count = sum(1 for v in vecs if v)
        logger.info(
            f"  embed batch {len(texts)} chunks in {dt:.1f}s ({1000 * dt / len(texts):.0f}ms/chunk avg, {ok_count}/{len(texts)} OK)"
        )

        if dry_run:
            processed += len(rows)
            success += ok_count
            continue

        # Update DB
        for cid, vec in zip(ids, vecs):
            if vec and len(vec) >= 256:
                conn.execute(
                    "UPDATE rag_chunks SET embedding = ? WHERE id = ?", (encode_blob(vec), cid)
                )
                success += 1
            processed += 1
        conn.commit()

        # Stats running
        elapsed = time.time() - t_start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total_null - processed) / rate if rate > 0 else 0
        logger.info(
            f"  TOTAL processed={processed} success={success} "
            f"rate={rate * 60:.0f}/min ETA={eta / 60:.1f}min"
        )

    conn.close()
    return {
        "processed": processed,
        "success": success,
        "total_null_remaining": total_null - success,
        "elapsed_s": round(time.time() - t_start, 1),
        "rate_per_min": round(processed * 60 / max(1, time.time() - t_start), 1),
        "dry_run": dry_run,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10000, help="Max chunks par run")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--max-workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = backfill(
        limit=args.limit,
        batch_size=args.batch_size,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
