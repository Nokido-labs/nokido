"""Step 3: cron daily — recalcule epistemic_weight pour chaque chunk actif.

Equation (de forge_epistemic_simulator.py):
    weight = alpha*trust_weight + beta*recency_decay
           + gamma*citation_norm + delta*peer_review_bonus
           + epsilon*refutation_penalty

Ecrit dans rag_chunks.epistemic_weight (denormalise pour retrieval rapide).

Usage:
    LAFORGE_PYTHON tools/forge_epistemic_recompute.py             # update all active
    LAFORGE_PYTHON tools/forge_epistemic_recompute.py --dry-run

Scheduled task (Windows):
    schtasks /Create /SC DAILY /TN LaForge-EpistemicRecompute /TR ^
      __import__("os").path.expanduser("~/miniforge3/python.exe ^
       %NOKIDO_WORKSPACE%/LaForge/tools/forge_epistemic_recompute.py") ^
      /ST 03:00
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

# Reuse equation depuis simulator
from nokido_agent.tools.forge_epistemic_simulator import (
    DEFAULT_ALPHA,
    DEFAULT_BETA,
    DEFAULT_DELTA,
    DEFAULT_EPSILON,
    DEFAULT_GAMMA,
    EpistemicChunk,
    epistemic_weight,
)

logger = logging.getLogger("epistemic_recompute")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# Map domain → half-life heuristique (calibrer via dataset historique)
DOMAIN_HALF_LIFE = {
    "watch_veille": 1.5,  # veille generaliste
    "stegano": 1.0,  # velocite tres haute
    "ai_safety": 0.8,  # tres tres rapide
    "cybersec_exploit": 0.5,  # 0day/exploit valides quelques mois
    "math_proof": 50.0,  # quasi eternel
    "physics_classic": 30.0,
}
DEFAULT_HALF_LIFE = 2.0


def _domain_half_life(domain: str | None) -> float:
    if not domain:
        return DEFAULT_HALF_LIFE
    for prefix, hl in DOMAIN_HALF_LIFE.items():
        if prefix in domain.lower():
            return hl
    return DEFAULT_HALF_LIFE


def _parse_year(ingested_at: str | None, fallback: float = 2024.5) -> float:
    if not ingested_at:
        return fallback
    try:
        dt = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))
        return dt.year + (dt.timetuple().tm_yday - 1) / 365.25
    except (ValueError, AttributeError):
        return fallback


def _now_year() -> float:
    now = datetime.now(tz=UTC)
    return now.year + (now.timetuple().tm_yday - 1) / 365.25


def _peer_reviewed_heuristic(source: str | None, author: str | None) -> bool:
    """Heuristique simple: detecte editeurs peer-reviewed connus."""
    if not source:
        return False
    src = source.lower()
    peer_indicators = [
        "ieee.org",
        "acm.org",
        "springer.com",
        "elsevier.com",
        "sciencedirect.com",
        "nature.com",
        "science.org",
        "mit press",
        "oup.com",
        "wiley.com",
        "taylorfrancis",
        "doi.org/10.",
    ]
    return any(ind in src for ind in peer_indicators)


def _trust_weight_heuristic(source: str | None, author: str | None) -> float:
    """Heuristique trust_weight si pas deja stocke."""
    if not source:
        return 0.3
    src = source.lower()
    if "arxiv.org/abs" in src or "openreview.net" in src:
        return 0.7
    if "doi.org" in src or any(
        p in src for p in ("ieee.org", "acm.org", "springer", "elsevier", "nature.com")
    ):
        return 0.95
    if "github.com" in src:
        return 0.6
    if "blog" in src or "substack" in src or "medium.com" in src:
        return 0.4
    return 0.5


def _count_refutations(conn, chunk_id: str) -> int:
    """Count claim_reevaluations of type 'contradicts'/'supersedes' targeting this chunk's claims."""
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM claim_reevaluations r
            JOIN chunk_claims c ON c.id = r.older_claim_id
            WHERE c.chunk_id = ?
              AND r.reevaluation_type IN ('contradicts', 'supersedes')
        """,
            (chunk_id,),
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        # Tables n'existent pas encore (migration pas faite)
        return 0


def recompute(dry_run: bool = False, limit: int | None = None) -> dict:
    if not DB.exists():
        return {"error": f"DB missing: {DB}"}
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Check epistemic_weight column existe (migration 1 faite ?)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()}
    if "epistemic_weight" not in cols:
        logger.error(
            "rag_chunks.epistemic_weight absent. Run tools/forge_epistemic_migrate.py first."
        )
        return {"error": "migration_required"}

    where = "(active IS NULL OR active = 1)"
    sql = f"SELECT id, source, author, domain, ingested_at FROM rag_chunks WHERE {where}"
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = conn.execute(sql).fetchall()
    logger.info(f"to process: {len(rows)} active chunks")
    if not rows:
        return {"processed": 0}

    t_now = _now_year()
    n_updated = 0
    n_skipped = 0
    t0 = time.time()

    for chunk_id, source, author, domain, ingested_at in rows:
        pub_year = _parse_year(ingested_at, fallback=t_now - 0.5)
        half_life = _domain_half_life(domain)
        peer_rev = _peer_reviewed_heuristic(source, author)
        trust = _trust_weight_heuristic(source, author)
        n_refs = _count_refutations(conn, chunk_id)

        chunk = EpistemicChunk(
            id=chunk_id,
            publication_year=pub_year,
            trust_weight=trust,
            citation_count=0,  # TODO: integrate Semantic Scholar / OpenAlex API
            peer_reviewed=peer_rev,
            domain_half_life_years=half_life,
            refutations=[(pub_year + 0.1, "ref") for _ in range(n_refs)],
        )
        w = epistemic_weight(
            chunk,
            t_now,
            alpha=DEFAULT_ALPHA,
            beta=DEFAULT_BETA,
            gamma=DEFAULT_GAMMA,
            delta=DEFAULT_DELTA,
            epsilon=DEFAULT_EPSILON,
        )

        if dry_run:
            n_skipped += 1
            if n_skipped <= 5:
                logger.info(f"  DRY {chunk_id} w={w:.3f} (peer={peer_rev} half_life={half_life})")
        else:
            conn.execute(
                "UPDATE rag_chunks SET epistemic_weight = ?, last_validated_at = ? WHERE id = ?",
                (w, datetime.now(tz=UTC).isoformat(), chunk_id),
            )
            n_updated += 1
            if n_updated % 1000 == 0:
                conn.commit()
                logger.info(f"  progress: {n_updated}/{len(rows)}")

    if not dry_run:
        conn.commit()
    elapsed = time.time() - t0

    # Stats finales
    stats = conn.execute("""
        SELECT
            COUNT(*) FILTER (WHERE active=1 OR active IS NULL) AS n_active,
            AVG(epistemic_weight) FILTER (WHERE active=1 OR active IS NULL) AS avg_w,
            MIN(epistemic_weight) FILTER (WHERE active=1 OR active IS NULL) AS min_w,
            MAX(epistemic_weight) FILTER (WHERE active=1 OR active IS NULL) AS max_w
        FROM rag_chunks
    """).fetchone()

    conn.close()
    result = {
        "processed": n_updated if not dry_run else n_skipped,
        "elapsed_s": round(elapsed, 2),
        "n_active": stats[0],
        "avg_weight": round(stats[1] or 0, 3),
        "min_weight": round(stats[2] or 0, 3),
        "max_weight": round(stats[3] or 0, 3),
        "dry_run": dry_run,
    }
    logger.info(f"[OK] {result}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, help="Limit N chunks (testing)")
    args = ap.parse_args()
    result = recompute(dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
