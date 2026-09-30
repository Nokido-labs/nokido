"""
tools/forge_graph_lru_expand.py — Graph engine with LRU cache + Personalized PageRank (PPR).
Integrates with forge_graph_universal via SQLite forge_graph table.
"""

import sqlite3
import time
from collections import defaultdict
from functools import lru_cache

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x


class GraphLRUCache:
    def __init__(self, maxsize: int = 512, ttl_seconds: float = 300.0):
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._neighbors: dict[str, list] = {}
        self._weights: dict[tuple, float] = {}
        self._ts: dict[str, float] = {}
        self._hits = self._misses = 0

        @lru_cache(maxsize=maxsize)
        def _cached_neighbors(node_id: str) -> tuple:
            self._misses += 1
            return tuple(self._neighbors.get(node_id, []))

        self._fn = _cached_neighbors

    def _expired(self, node_id: str) -> bool:
        ts = self._ts.get(node_id)
        return ts is not None and (time.monotonic() - ts) > self._ttl

    def get_neighbors(self, node_id: str) -> list:
        if self._expired(node_id):
            self.invalidate(node_id)
            return []
        self._hits += 1
        return list(self._fn(node_id))

    def get_edge_weight(self, src: str, dst: str) -> float:
        return self._weights.get((src, dst), 0.0)

    def set_neighbors(self, node_id: str, neighbors: list):
        self._neighbors[node_id] = neighbors
        self._ts[node_id] = time.monotonic()
        self._fn.cache_clear()

    def set_edge(self, src: str, dst: str, weight: float):
        self._weights[(src, dst)] = weight
        self._neighbors.setdefault(src, [])
        if dst not in self._neighbors[src]:
            self._neighbors[src].append(dst)
        self._ts[src] = time.monotonic()
        self._fn.cache_clear()

    def invalidate(self, node_id: str):
        self._neighbors.pop(node_id, None)
        self._ts.pop(node_id, None)
        self._fn.cache_clear()

    def __len__(self) -> int:
        now = time.monotonic()
        return sum(1 for k, ts in self._ts.items() if (now - ts) <= self._ttl)

    def stats(self) -> dict:
        info = self._fn.cache_info()
        return {
            "hits": info.hits,
            "misses": info.misses,
            "maxsize": info.maxsize,
            "currsize": info.currsize,
            "live_entries": len(self),
        }


def personalized_pagerank(
    graph: dict, seed_nodes: list[str], alpha: float = 0.85, max_iter: int = 50
) -> dict[str, float]:
    all_nodes = set(graph)
    scores: dict[str, float] = dict.fromkeys(all_nodes, 0.0)
    seed_weight = 1.0 / max(len(seed_nodes), 1)
    for s in seed_nodes:
        if s in scores:
            scores[s] = seed_weight

    for _ in tqdm(range(max_iter), desc="PPR iterations", unit="iter", leave=False):
        new_scores: dict[str, float] = defaultdict(float)
        for node, node_score in scores.items():
            neighbors = graph.get(node, {})
            total_w = sum(neighbors.values()) or 1.0
            for neighbor, weight in neighbors.items():
                new_scores[neighbor] += alpha * node_score * (weight / total_w)
        # teleport to seed
        for s in seed_nodes:
            new_scores[s] += (1.0 - alpha) * seed_weight
        scores = dict(new_scores)

    return scores


def top_k_by_ppr(graph: dict, seed_nodes: list[str], k: int = 10) -> list[tuple[str, float]]:
    ppr = personalized_pagerank(graph, seed_nodes)
    return sorted(ppr.items(), key=lambda x: x[1], reverse=True)[:k]


class ExpandedGraphEngine:
    def __init__(self, db_path: str | None = None):
        self.graph: dict[str, dict[str, float]] = {}
        self.cache = GraphLRUCache()
        if db_path:
            self._load_from_db(db_path)

    def _load_from_db(self, db_path: str):
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT src, dst, weight FROM forge_graph").fetchall()
            conn.close()
            for src, dst, weight in tqdm(rows, desc="loading graph", unit="edge"):
                self.update_edge(src, dst, float(weight))
        except Exception as e:
            print(f"[WARN] forge_graph table not found or error: {e}")

    def query(self, seed: list[str], k: int = 10) -> list[tuple[str, float]]:
        return top_k_by_ppr(self.graph, seed, k)

    def update_edge(self, src: str, dst: str, weight: float = 1.0):
        self.graph.setdefault(src, {})[dst] = weight
        self.cache.set_edge(src, dst, weight)

    def add_nodes(self, nodes: list[str]):
        for n in nodes:
            self.graph.setdefault(n, {})


if __name__ == "__main__":
    import random

    random.seed(42)

    engine = ExpandedGraphEngine()
    nodes = [f"node_{i}" for i in range(100)]
    engine.add_nodes(nodes)

    # Synthetic sparse graph: ~5 edges per node
    for i in range(100):
        for _ in range(5):
            j = random.randint(0, 99)
            if j != i:
                engine.update_edge(f"node_{i}", f"node_{j}", round(random.random(), 3))

    seeds = ["node_0", "node_1"]
    print(f"Top 10 by PPR from seeds {seeds}:")
    for node, score in engine.query(seeds, k=10):
        print(f"  {node}: {score:.4f}")

    print("\nCache stats:", engine.cache.stats())
