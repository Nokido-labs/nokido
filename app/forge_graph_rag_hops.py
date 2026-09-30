"""forge_graph_rag_hops.py — GraphRAG hop expansion layer.

Wrap autour RAGEngine + forge_graph_universal pour expansion BFS k-hop
des resultats top-K initial. Pattern Wang RAG 2026 / Microsoft GraphRAG.

Workflow :
  1. RAGEngine.search(query) -> top_k chunks initiaux (seed)
  2. Pour chaque seed, expand via graph edges (cooccurrence, hebbian, citation)
  3. Score combine : alpha*relevance_initial + beta*hop_distance_decay + gamma*centrality
  4. Re-rank et retourne top_n final

API :
    graph_rag_search(query, k_seed=10, hops=2, alpha=0.6, beta=0.3, gamma=0.1)
"""

from __future__ import annotations
import argparse
import json
import logging
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("graph_rag_hops")


def _conn():
    c = sqlite3.connect(str(DB), timeout=30)
    c.row_factory = sqlite3.Row
    return c


# --- Helpers graph Nokido ---


def _has_table(conn, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _expand_via_hebbian(conn, seed_ids: list[str], hops: int = 1) -> dict[str, float]:
    """BFS expansion via biblio_link hebbian_idea edges. Retourne {chunk_id: hop_distance}."""
    if not _has_table(conn, "biblio_link"):
        return {}
    visited = {sid: 0 for sid in seed_ids}
    frontier = list(seed_ids)
    for hop in range(1, hops + 1):
        next_frontier = []
        for node in frontier:
            placeholders_skip = ",".join("?" * len(visited))
            rows = conn.execute(
                f"""
                SELECT DISTINCT dst_id FROM biblio_link
                WHERE src_id = ? AND kind = 'hebbian_idea'
                  AND dst_id NOT IN ({placeholders_skip})
                LIMIT 20
            """,
                [node] + list(visited.keys()),
            ).fetchall()
            for r in rows:
                dst = r[0]
                if dst not in visited:
                    visited[dst] = hop
                    next_frontier.append(dst)
        frontier = next_frontier
        if not frontier:
            break
    return visited


def _expand_via_claim_relations(conn, seed_chunk_ids: list[str], hops: int = 1) -> dict[str, float]:
    """BFS via chunk_claims + claim_reevaluations. Si chunk A a un claim refute par chunk B,
    B est expansion 1-hop."""
    if not (_has_table(conn, "chunk_claims") and _has_table(conn, "claim_reevaluations")):
        return {}
    placeholders = ",".join("?" * len(seed_chunk_ids))
    seed_claims = conn.execute(
        f"""
        SELECT id FROM chunk_claims WHERE chunk_id IN ({placeholders})
    """,
        seed_chunk_ids,
    ).fetchall()
    seed_claim_ids = [r[0] for r in seed_claims]
    if not seed_claim_ids:
        return {}

    visited = {sid: 0 for sid in seed_chunk_ids}
    frontier_claims = seed_claim_ids
    for hop in range(1, hops + 1):
        if not frontier_claims:
            break
        ph = ",".join("?" * len(frontier_claims))
        related_claims = conn.execute(
            f"""
            SELECT DISTINCT newer_claim_id FROM claim_reevaluations
            WHERE older_claim_id IN ({ph})
            UNION
            SELECT DISTINCT older_claim_id FROM claim_reevaluations
            WHERE newer_claim_id IN ({ph})
        """,
            frontier_claims + frontier_claims,
        ).fetchall()
        new_claim_ids = [r[0] for r in related_claims if r[0]]
        if not new_claim_ids:
            break
        # Map back to chunks
        ph2 = ",".join("?" * len(new_claim_ids))
        new_chunks = conn.execute(
            f"""
            SELECT DISTINCT chunk_id FROM chunk_claims WHERE id IN ({ph2})
        """,
            new_claim_ids,
        ).fetchall()
        next_chunk_ids = []
        for r in new_chunks:
            cid = r[0]
            if cid and cid not in visited:
                visited[cid] = hop
                next_chunk_ids.append(cid)
        frontier_claims = new_claim_ids
    return visited


# --- Combined scoring ---


def _hop_decay(hop_dist: int, half_life_hops: float = 1.0) -> float:
    """Score decay exponentiel par hop."""
    return math.exp(-hop_dist * math.log(2) / half_life_hops)


def _fetch_chunks(conn, chunk_ids: list[str]) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    ph = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"""
        SELECT id, text, source, domain, epistemic_weight, ingested_at
        FROM rag_chunks
        WHERE id IN ({ph}) AND (active IS NULL OR active = 1)
    """,
        chunk_ids,
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


# --- API principale ---


def graph_rag_search(
    query: str,
    k_seed: int = 10,
    hops: int = 2,
    alpha: float = 0.6,
    beta: float = 0.3,
    gamma: float = 0.1,
    top_n: int = 15,
    min_weight: float = 0.0,
) -> list[dict]:
    """Search avec hop expansion.

    Score = alpha*epistemic_weight_seed + beta*hop_decay + gamma*centrality_proxy

    Args:
        query: search terms
        k_seed: top-K seed chunks (avant expansion)
        hops: max hops BFS expansion
        alpha: weight epistemic du seed
        beta: weight hop_decay (proches > lointains)
        gamma: weight centrality (chunks recherches plusieurs fois = central)
    """
    conn = _conn()
    try:
        # 1. Seed search par LIKE simple (a remplacer par FTS5 production)
        seeds = conn.execute(
            """
            SELECT id, text, source, domain, epistemic_weight, ingested_at
            FROM rag_chunks
            WHERE (active IS NULL OR active = 1)
              AND text LIKE ?
              AND (epistemic_weight >= ? OR epistemic_weight IS NULL)
            ORDER BY epistemic_weight DESC NULLS LAST
            LIMIT ?
        """,
            (f"%{query}%", min_weight, k_seed),
        ).fetchall()
        seed_chunks = [dict(s) for s in seeds]
        seed_ids = [s["id"] for s in seed_chunks]
        if not seed_ids:
            return []

        # 2. Expansion multi-source
        hebbian_hops = _expand_via_hebbian(conn, seed_ids, hops=hops)
        claim_hops = _expand_via_claim_relations(conn, seed_ids, hops=hops)

        # 3. Merge hop distances (min entre sources)
        all_hops: dict[str, int] = {}
        for cid, h in hebbian_hops.items():
            all_hops[cid] = h
        for cid, h in claim_hops.items():
            all_hops[cid] = min(all_hops.get(cid, h), h)

        # 4. Fetch chunks expanded
        expanded_ids = [cid for cid in all_hops if cid not in {s["id"] for s in seed_chunks}]
        expanded_chunks = _fetch_chunks(conn, expanded_ids)

        # 5. Centrality proxy : count occurrences cross-expansion
        centrality = defaultdict(int)
        for cid in hebbian_hops:
            centrality[cid] += 1
        for cid in claim_hops:
            centrality[cid] += 1

        # 6. Score combine + collect
        scored = []
        for s in seed_chunks:
            cid = s["id"]
            ew = s.get("epistemic_weight") or 0.5
            hd = _hop_decay(0)
            cen = centrality.get(cid, 1) / 2.0
            score = alpha * ew + beta * hd + gamma * cen
            s["score"] = round(score, 4)
            s["hop_distance"] = 0
            s["centrality"] = cen
            scored.append(s)

        for cid, chunk in expanded_chunks.items():
            h = all_hops.get(cid, hops)
            ew = chunk.get("epistemic_weight") or 0.5
            hd = _hop_decay(h)
            cen = centrality.get(cid, 1) / 2.0
            score = alpha * ew + beta * hd + gamma * cen
            chunk["score"] = round(score, 4)
            chunk["hop_distance"] = h
            chunk["centrality"] = cen
            scored.append(chunk)

        # 7. Sort + truncate
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_n]
    finally:
        conn.close()


# --- CLI ---


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k-seed", type=int, default=10)
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--top-n", type=int, default=15)
    ap.add_argument("--alpha", type=float, default=0.6)
    ap.add_argument("--beta", type=float, default=0.3)
    ap.add_argument("--gamma", type=float, default=0.1)
    args = ap.parse_args()

    results = graph_rag_search(
        args.query,
        k_seed=args.k_seed,
        hops=args.hops,
        top_n=args.top_n,
        alpha=args.alpha,
        beta=args.beta,
        gamma=args.gamma,
    )
    print(
        json.dumps(
            [
                {
                    "id": r["id"],
                    "score": r["score"],
                    "hop": r["hop_distance"],
                    "source": r.get("source", "?"),
                    "text_preview": (r.get("text") or "")[:150],
                }
                for r in results
            ],
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
