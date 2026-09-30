#!/usr/bin/env python3
"""
forge_graph_rag.py — Graph-RAG Layer for Nokido
=================================================
Transforms flat vector RAG (embeddings.db) into a navigable knowledge graph.
Instead of top-K by cosine, retrieves a sub-graph of N hops around query.

Three relation types (stored in SQLite alongside existing rag_chunks):
  1. CO_SOURCE  — chunks from the same source file/doc
  2. CO_DOMAIN  — chunks sharing the same domain tag
  3. SEMANTIC   — chunks with embedding cosine > threshold

Usage:
  from forge_graph_rag import GraphRAG
  grag = GraphRAG("path/to/embeddings.db")
  grag.build_graph()
  results = grag.traverse("SSRF Flask", hops=2, top_k=10)
"""

from __future__ import annotations

import json, sqlite3, struct, time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class GNode:
    chunk_id: str
    source: str
    domain: str
    text_preview: str = ""


@dataclass
class GEdge:
    src: str
    dst: str
    rel_type: str
    weight: float = 1.0


@dataclass
class TraversalResult:
    query: str
    seed_ids: list
    subgraph_nodes: list
    subgraph_edges: list
    ranked_chunks: list
    stats: dict = field(default_factory=dict)


def _blob_to_vec(blob):
    if not blob:
        return None
    try:
        # Tentative JSON
        if blob.startswith(b"[") or blob.startswith(b"["):
            import json

            return np.array(json.loads(blob.decode("utf-8")), dtype=np.float32)

        # Tentative binaire raw float32
        n = len(blob) // 4
        return np.frombuffer(blob, dtype=np.float32)
    except Exception:
        try:
            # Fallback struct unpack if needed
            n = len(blob) // 4
            return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)
        except Exception:
            return None


def _cosine_batch(query, matrix):
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms < 1e-9, 1.0, norms)
    normed = matrix / norms
    qn = np.linalg.norm(query)
    if qn < 1e-9:
        return np.zeros(len(matrix))
    return normed @ (query / qn)


class GraphRAG:
    SCHEMA_NODES = """CREATE TABLE IF NOT EXISTS rag_graph_nodes (
        chunk_id TEXT PRIMARY KEY, source TEXT, domain TEXT, degree INTEGER DEFAULT 0)"""
    SCHEMA_EDGES = """CREATE TABLE IF NOT EXISTS rag_graph_edges (
        src TEXT, dst TEXT, rel_type TEXT, weight REAL DEFAULT 1.0,
        PRIMARY KEY (src, dst, rel_type))"""

    def __init__(self, db_path, semantic_threshold=0.75, max_co_source=20, max_semantic_neighbors=8):
        self.db_path = str(db_path)
        self.semantic_threshold = semantic_threshold
        self.max_co_source = max_co_source
        self.max_semantic_neighbors = max_semantic_neighbors
        self._traverse_cache: dict = {}
        self._ensure_schema()

    def cache_clear(self) -> None:
        self._traverse_cache.clear()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _ensure_schema(self):
        with self._conn() as c:
            c.execute(self.SCHEMA_NODES)
            c.execute(self.SCHEMA_EDGES)
            c.execute("CREATE INDEX IF NOT EXISTS idx_gre_src ON rag_graph_edges(src)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_gre_dst ON rag_graph_edges(dst)")

    def ensure_fts5(self):
        """Create or rebuild FTS5 index on rag_chunks."""
        with self._conn() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "rag_fts" not in tables:
                conn.execute("""CREATE VIRTUAL TABLE rag_fts USING fts5(
                    chunk_id, text, source, domain,
                    tokenize='porter unicode61')""")
                rows = conn.execute("SELECT id, text, source, domain FROM rag_chunks WHERE text IS NOT NULL").fetchall()
                conn.executemany("INSERT INTO rag_fts(chunk_id, text, source, domain) VALUES (?,?,?,?)", rows)

    def build_graph(self, batch_size=200, include_ast=True):
        """Build graph with standard relations + optional AST structure."""
        t0 = time.time()
        stats = {"nodes": 0, "edges_co_source": 0, "edges_co_domain": 0, "edges_semantic": 0, "ast": {}}

        # ── 1. Basic & CO_SOURCE ───────────────────────────────────────
        with self._conn() as conn:
            conn.execute("DELETE FROM rag_graph_nodes")
            conn.execute("DELETE FROM rag_graph_edges WHERE rel_type IN ('CO_SOURCE', 'CO_DOMAIN', 'SEMANTIC')")
            rows = conn.execute("SELECT id, source, domain FROM rag_chunks").fetchall()
            if not rows:
                return stats
            conn.executemany("INSERT OR REPLACE INTO rag_graph_nodes (chunk_id,source,domain) VALUES (?,?,?)", rows)
            stats["nodes"] = len(rows)

            by_source = defaultdict(list)
            for cid, src, dom in rows:
                by_source[src].append(cid)
            co_src = []
            for src, cids in by_source.items():
                cids = cids[: self.max_co_source]
                for i in range(len(cids)):
                    for j in range(i + 1, len(cids)):
                        co_src.append((cids[i], cids[j], "CO_SOURCE", 0.8))
                        co_src.append((cids[j], cids[i], "CO_SOURCE", 0.8))
            if co_src:
                conn.executemany("INSERT OR IGNORE INTO rag_graph_edges VALUES (?,?,?,?)", co_src)
            stats["edges_co_source"] = len(co_src) // 2

        # ── 2. AST Intelligence (Bridging GraphLinker) ────────────────
        if include_ast:
            try:
                from nokido_agent.app.forge_graph_linker import GraphLinker

                linker = GraphLinker(db_path=self.db_path)
                ast_stats = linker.build_ast_edges(verbose=False)
                stats["ast"] = ast_stats
            except ImportError:
                print("⚠️ GraphLinker not found, skipping AST edges.")

        # ── 3. CO_DOMAIN ──────────────────────────────────────────────
        with self._conn() as conn:
            import random as _rng

            by_dom = defaultdict(list)
            for cid, src, dom in rows:
                by_dom[dom].append(cid)
            co_dom = []
            for dom, cids in by_dom.items():
                if len(cids) < 2 or dom == "general":
                    continue
                sample = cids if len(cids) <= 50 else _rng.Random(42).sample(cids, 50)
                for i in range(len(sample)):
                    for j in range(i + 1, min(i + 5, len(sample))):
                        co_dom.append((sample[i], sample[j], "CO_DOMAIN", 0.5))
                        co_dom.append((sample[j], sample[i], "CO_DOMAIN", 0.5))
            if co_dom:
                conn.executemany("INSERT OR IGNORE INTO rag_graph_edges VALUES (?,?,?,?)", co_dom)
            stats["edges_co_domain"] = len(co_dom) // 2

            # ── 4. SEMANTIC ───────────────────────────────────────────
            print("  Computing semantic edges...")
            emb_rows = conn.execute("SELECT id, embedding FROM rag_chunks WHERE embedding IS NOT NULL").fetchall()
            if len(emb_rows) > 10:
                vecs, valid_ids = [], []
                for cid, blob in emb_rows:
                    v = _blob_to_vec(blob)
                    if v is not None:
                        vecs.append(v)
                        valid_ids.append(cid)
                if len(vecs) > 10:
                    # Vérification de l'homogénéité des dimensions
                    dim_counts = defaultdict(int)
                    for v in vecs:
                        dim_counts[len(v)] += 1
                    majority_dim = max(dim_counts, key=dim_counts.get)

                    if len(dim_counts) > 1:
                        print(f"  ⚠️ Mixed dimensions detected: {dict(dim_counts)}. Keeping only dim {majority_dim}")
                        new_vecs, new_ids = [], []
                        for i, v in enumerate(vecs):
                            if len(v) == majority_dim:
                                new_vecs.append(v)
                                new_ids.append(valid_ids[i])
                        vecs, valid_ids = new_vecs, new_ids

                    if not vecs:
                        return stats
                    matrix = np.array(vecs, dtype=np.float32)
                    sem = []
                    for start in range(0, len(valid_ids), batch_size):
                        end = min(start + batch_size, len(valid_ids))
                        bv = matrix[start:end]
                        nb = np.linalg.norm(bv, axis=1, keepdims=True)
                        na = np.linalg.norm(matrix, axis=1, keepdims=True)
                        nb = np.where(nb < 1e-9, 1.0, nb)
                        na = np.where(na < 1e-9, 1.0, na)
                        sims = (bv / nb) @ (matrix / na).T
                        for bi in range(end - start):
                            gi = start + bi
                            row = sims[bi].copy()
                            row[gi] = -1
                            top_idx = np.argsort(row)[-self.max_semantic_neighbors :]
                            for ti in top_idx:
                                if row[ti] >= self.semantic_threshold:
                                    sem.append((valid_ids[gi], valid_ids[ti], "SEMANTIC", round(float(row[ti]), 4)))
                    if sem:
                        conn.executemany("INSERT OR IGNORE INTO rag_graph_edges VALUES (?,?,?,?)", sem)
                    stats["edges_semantic"] = len(sem)

            conn.execute("UPDATE rag_graph_nodes SET degree=(SELECT COUNT(*) FROM rag_graph_edges WHERE src=chunk_id)")

        stats["time_s"] = round(time.time() - t0, 2)
        print(f"  Built in {stats['time_s']}s")
        return stats

    def get_edge_stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT rel_type, COUNT(*), AVG(weight) FROM rag_graph_edges GROUP BY rel_type"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM rag_graph_edges").fetchone()[0]
            weights = [r[0] for r in conn.execute("SELECT weight FROM rag_graph_edges ORDER BY weight").fetchall()]
            p50 = weights[len(weights) // 2] if weights else 0.0
            by_type = {r[0]: {"count": r[1], "avg_weight": round(r[2], 4)} for r in rows}
            return {
                "total_edges": total,
                "by_type": by_type,
                "semantic_edges": by_type.get("SEMANTIC", {}).get("count", 0),
                "co_source_edges": by_type.get("CO_SOURCE", {}).get("count", 0),
                "co_domain_edges": by_type.get("CO_DOMAIN", {}).get("count", 0),
                "avg_weight": round(sum(weights) / len(weights), 4) if weights else 0.0,
                "p50_weight": round(p50, 4),
            }

    def personalized_pagerank(self, seed_chunk_ids: list, alpha: float = 0.85, max_iter: int = 30) -> dict:
        """Power-iteration PPR on rag_graph_edges. Returns dict[chunk_id -> score]."""
        if not seed_chunk_ids:
            return {}
        seed_set = set(seed_chunk_ids)
        with self._conn() as conn:
            rows = conn.execute("SELECT src_id, dst_id, weight FROM rag_graph_edges").fetchall()
        if not rows:
            return {n: 1.0 / len(seed_set) for n in seed_set}

        adj: dict = {}
        nodes: set = set()
        for src, dst, w in rows:
            adj.setdefault(src, []).append((dst, float(w)))
            nodes.add(src)
            nodes.add(dst)
        nodes.update(seed_set)

        # Normalize out-weights per source
        out_norm: dict = {}
        for src, nbrs in adj.items():
            total = sum(w for _, w in nbrs) or 1.0
            out_norm[src] = [(dst, w / total) for dst, w in nbrs]

        seed_uniform = 1.0 / len(seed_set)
        scores = {n: (seed_uniform if n in seed_set else 0.0) for n in nodes}

        for _ in range(max_iter):
            new_s: dict = {n: 0.0 for n in nodes}
            # Teleport to seeds
            for n in seed_set:
                new_s[n] += alpha * seed_uniform
            # Propagate
            for src in nodes:
                s = scores[src]
                if s == 0.0:
                    continue
                nbrs = out_norm.get(src)
                if not nbrs:
                    # dangling: redirect to seeds
                    contrib = (1 - alpha) * s * seed_uniform
                    for n in seed_set:
                        new_s[n] += contrib
                else:
                    contrib = (1 - alpha) * s
                    for dst, nw in nbrs:
                        new_s[dst] += contrib * nw
            scores = new_s

        return dict(sorted(((k, round(v, 6)) for k, v in scores.items() if v > 0), key=lambda x: -x[1]))

    def traverse(self, query, hops=2, top_k=10, query_embedding=None):
        _key = (query, hops, top_k)
        _cached = self._traverse_cache.get(_key)
        if _cached and time.time() - _cached[1] < 300:
            return _cached[0]
        t0 = time.time()
        with self._conn() as conn:
            seed_ids = self._text_seeds(conn, query, n=5)
            if not seed_ids:
                return TraversalResult(
                    query=query,
                    seed_ids=[],
                    subgraph_nodes=[],
                    subgraph_edges=[],
                    ranked_chunks=[],
                    stats={"error": "no seeds"},
                )
            visited = set(seed_ids)
            frontier = set(seed_ids)
            all_edges = []
            hop_dist = {sid: 0 for sid in seed_ids}
            for hop in range(1, hops + 1):
                if not frontier:
                    break
                ph = ",".join("?" * len(frontier))
                vh = ",".join("?" * len(visited))
                edges = conn.execute(
                    f"SELECT src,dst,rel_type,weight FROM rag_graph_edges WHERE src IN ({ph}) AND dst NOT IN ({vh}) LIMIT 200",
                    list(frontier) + list(visited),
                ).fetchall()
                new_f = set()
                for src, dst, rel, w in edges:
                    all_edges.append(GEdge(src=src, dst=dst, rel_type=rel, weight=w))
                    if dst not in visited:
                        visited.add(dst)
                        new_f.add(dst)
                        hop_dist[dst] = hop
                frontier = new_f
            ph = ",".join("?" * len(visited))
            chunk_rows = conn.execute(
                f"SELECT id,source,domain,text FROM rag_chunks WHERE id IN ({ph})", list(visited)
            ).fetchall()
            nodes = []
            chunks = []
            for cid, src, dom, text in chunk_rows:
                nodes.append(GNode(chunk_id=cid, source=src, domain=dom, text_preview=text[:100]))
                h = hop_dist.get(cid, hops + 1)
                score = 1.0 / (1 + h) + (1.0 if cid in seed_ids else 0.0)
                chunks.append(
                    {
                        "chunk_id": cid,
                        "text": text,
                        "source": src,
                        "domain": dom,
                        "score": round(score, 4),
                        "hop_distance": h,
                    }
                )
            chunks.sort(key=lambda x: -x["score"])
        _result = TraversalResult(
            query=query,
            seed_ids=seed_ids,
            subgraph_nodes=nodes,
            subgraph_edges=all_edges,
            ranked_chunks=chunks[:top_k],
            stats={
                "seeds": len(seed_ids),
                "visited": len(visited),
                "edges": len(all_edges),
                "time_s": round(time.time() - t0, 4),
            },
        )
        self._traverse_cache[_key] = (_result, time.time())
        return _result

    def _text_seeds(self, conn, query, n=5):
        """Seed nodes via FTS5 full-text search, fallback to LIKE."""
        words = query.lower().split()[:4]
        if not words:
            return []
        # Try FTS5 first (OR between words for broader recall)
        try:
            fts_query = " OR ".join(w for w in words if len(w) > 2)
            if fts_query:
                rows = conn.execute(
                    "SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH ? ORDER BY rank LIMIT ?", (fts_query, n)
                ).fetchall()
                if rows:
                    return [r[0] for r in rows]
        except Exception:
            pass
        # Fallback: LIKE
        conds = " OR ".join("LOWER(text) LIKE ?" for _ in words)
        rows = conn.execute(
            f"SELECT id FROM rag_chunks WHERE {conds} LIMIT ?", [f"%{w}%" for w in words] + [n]
        ).fetchall()
        return [r[0] for r in rows]

    def graph_stats(self):
        with self._conn() as conn:
            nn = conn.execute("SELECT COUNT(*) FROM rag_graph_nodes").fetchone()[0]
            ne = conn.execute("SELECT COUNT(*) FROM rag_graph_edges").fetchone()[0]
            by_rel = dict(conn.execute("SELECT rel_type,COUNT(*) FROM rag_graph_edges GROUP BY rel_type").fetchall())
            ad = conn.execute("SELECT AVG(degree) FROM rag_graph_nodes").fetchone()[0]
        return {"nodes": nn, "edges": ne, "by_relation": by_rel, "avg_degree": round(float(ad or 0), 2)}
