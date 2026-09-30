"""
tools/forge_edge_scoring.py — Unified edge scoring for Nokido knowledge graph.
Combines semantic similarity, temporal recency, trust weight, co-occurrence frequency.
"""

import math
import sqlite3
import time
from collections import Counter
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(LAFORGE_ROOT / "RAG" / "embeddings.db")

TRUST_MAP = {
    "rag": 1.0,
    "doc": 0.9,
    "sdk_gitingest": 0.8,
    "ctf": 0.7,
    "ctf_writeup": 0.7,
    "compacted": 0.6,
}
HALF_LIFE_SECS = 7 * 86400  # 7 days


def semantic_score(text_a: str, text_b: str) -> float:
    wa = Counter(text_a.lower().split())
    wb = Counter(text_b.lower().split())
    common = set(wa) & set(wb)
    if not common:
        return 0.0
    dot = sum(wa[w] * wb[w] for w in common)
    mag_a = math.sqrt(sum(v * v for v in wa.values()))
    mag_b = math.sqrt(sum(v * v for v in wb.values()))
    return dot / (mag_a * mag_b) if mag_a * mag_b else 0.0


def temporal_score(created_at: int, now: int | None = None) -> float:
    if now is None:
        now = int(time.time())
    delta = max(0, now - created_at)
    return 0.5 ** (delta / HALF_LIFE_SECS)


def trust_score(domain: str) -> float:
    return TRUST_MAP.get(domain, 0.5)


def _sources_fts(conn, kw: list) -> set | None:
    """Sources dont un chunk MATCHe les mots-cles, via rag_fts (FTS5 INDEXE).
    None = rag_fts indisponible/illisible -> l'appelant retombe sur LIKE."""
    q = " ".join(kw).replace('"', " ").strip()
    if not q:
        return set()
    try:
        rows = conn.execute(
            "SELECT DISTINCT source FROM rag_fts WHERE rag_fts MATCH ?",
            ('"' + q + '"',)).fetchall()
    except sqlite3.OperationalError:
        return None  # pas de table rag_fts, ou syntaxe MATCH refusee
    return {r[0] for r in rows}


def cooccurrence_score(src_text: str, dst_text: str, db_path: str) -> float:
    """Proxy de co-occurrence : nb de sources ou src ET dst apparaissent.

    ⚠️ L'ancienne version faisait `text LIKE '%mot%'` sur `rag_chunks` (466k+
    lignes) A CHAQUE ARETE, nichee dans un sous-select -> DEUX full scans par
    appel (le wildcard en tete rend le LIKE NON indexable), et `unified_score`
    l'appelle pour chaque paire. Regle d'or Nokido : jamais de LIKE primitif ->
    rag_fts. On interroge donc l'index FTS5 pour chaque cote et on intersecte les
    sources cote Python : deux SEARCH indexes au lieu de deux SCAN complets.
    Repli sur l'ancien LIKE si rag_fts est absent (correct, lent).
    """
    src_kw = src_text.split()[:2]
    dst_kw = dst_text.split()[:2]
    if not src_kw or not dst_kw:
        return 0.0
    try:
        conn = sqlite3.connect(db_path)
        try:
            s_src = _sources_fts(conn, src_kw)
            s_dst = _sources_fts(conn, dst_kw)
            if s_src is None or s_dst is None:
                src_q = "%" + " ".join(src_kw) + "%"
                dst_q = "%" + " ".join(dst_kw) + "%"
                count = conn.execute(
                    "SELECT COUNT(DISTINCT source) FROM rag_chunks WHERE text LIKE ? "
                    "AND source IN (SELECT source FROM rag_chunks WHERE text LIKE ?)",
                    (src_q, dst_q)).fetchone()[0]
            else:
                count = len(s_src & s_dst)
            return min(count / 10.0, 1.0)
        finally:
            conn.close()
    except Exception:
        return 0.0


def unified_score(
    text_a: str,
    text_b: str,
    domain_a: str,
    domain_b: str,
    created_a: int,
    created_b: int,
    db_path: str,
    weights: dict | None = None,
) -> float:
    if weights is None:
        weights = {"semantic": 0.4, "temporal": 0.3, "trust": 0.2, "cooccurrence": 0.1}
    sem = semantic_score(text_a, text_b)
    temp = (temporal_score(created_a) + temporal_score(created_b)) / 2.0
    trust = (trust_score(domain_a) + trust_score(domain_b)) / 2.0
    coocc = cooccurrence_score(text_a, text_b, db_path)
    return (
        weights["semantic"] * sem
        + weights["temporal"] * temp
        + weights["trust"] * trust
        + weights["cooccurrence"] * coocc
    )


class EdgeScorer:
    def __init__(self, db_path: str = DEFAULT_DB, maxsize: int = 1024):
        self.db_path = db_path
        # lru_cache on a plain function; wrap per instance
        self._cache: dict = {}
        self._hits = self._misses = 0

    def score(
        self, text_a: str, text_b: str, domain_a: str, domain_b: str, created_a: int, created_b: int
    ) -> float:
        key = (text_a[:40], text_b[:40], domain_a, domain_b, created_a, created_b)
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        result = unified_score(
            text_a, text_b, domain_a, domain_b, created_a, created_b, self.db_path
        )
        self._cache[key] = result
        return result

    def stats(self) -> dict:
        return {"hits": self._hits, "misses": self._misses, "cached": len(self._cache)}


def score_all_edges(edges: list[tuple], db_path: str = DEFAULT_DB) -> list[tuple[float, tuple]]:
    scorer = EdgeScorer(db_path)
    results = []
    for edge in tqdm(edges, desc="scoring edges", unit="edge"):
        text_a, text_b, domain_a, domain_b, created_a, created_b = edge
        s = scorer.score(text_a, text_b, domain_a, domain_b, created_a, created_b)
        results.append((s, edge))
    return sorted(results, key=lambda x: x[0], reverse=True)


if __name__ == "__main__":
    now = int(time.time())
    edges = [
        (
            "neural network training",
            "deep learning optimizer",
            "rag",
            "doc",
            now - 86400,
            now - 3600,
        ),
        (
            "SQL injection bypass",
            "CVE-2023-1234 exploit",
            "ctf",
            "ctf_writeup",
            now - 86400 * 10,
            now - 86400 * 2,
        ),
        ("forge_rag_engine search", "BM25 retrieval", "rag", "rag", now - 3600, now - 1800),
        (
            "Python async coroutine",
            "JavaScript Promise",
            "doc",
            "sdk_gitingest",
            now - 86400 * 30,
            now - 86400 * 5,
        ),
        ("heap tcache poisoning", "glibc allocator", "ctf", "ctf", now - 86400 * 3, now - 86400),
    ]
    results = score_all_edges(edges)
    print("\nEdge scores (highest first):")
    for score, edge in results:
        print(f"  {score:.3f}  {edge[0][:30]!r} ↔ {edge[1][:30]!r}")
