"""forge_spatial_reasoning.py — grid representation RAG (hippocampe-inspired).

Inspire de :
  - O'Keefe/Nadel hippocampe cognitive map (place cells)
  - Moser entorhinal grid cells (multi-scale spatial code)
  - Tolman-Eichenbaum Machine TEM (relational inference)
  - RatSLAM (continuous attractor networks navigation)
  - DeepMind 'Vector-based navigation using grid-like representations'

Idee : projeter embeddings BGE-M3 (1024D) vers grille 2D (UMAP/PCA) + cluster
en 'place cells'. Recherche RAG par 'proximite spatiale' au lieu de juste cosine.

Avantages :
  - Navigation analogique : 'concepts proches dans la map' = related themes
  - Visualisation cognitive : voir le knowledge graph
  - Compression : 1024D -> 2D pour cache leger
  - Multi-scale : ajouter grids 2D+5D+10D (comme grid cells multi-echelle)

API :
    sm = SpatialMap()
    sm.build_from_chunks(domain_filter='watch_veille')      # offline indexing
    sm.locate(text) -> (x, y, place_cell_id)
    sm.neighbors(x, y, radius=0.5) -> list[chunk_id]
    sm.path(start_text, end_text) -> list[place_cells]    # trajectoire
"""

from __future__ import annotations
import argparse
import json
import logging
import math
import pickle
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
MAP_CACHE = ROOT / "data" / "spatial_map.pkl"
MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("spatial_reasoning")


def _embedding_from_blob(blob: bytes) -> list[float] | None:
    """rag_chunks.embedding peut etre BLOB float32 binaire OU JSON TEXT."""
    if not blob:
        return None
    if isinstance(blob, bytes):
        try:
            import struct

            n = len(blob) // 4
            return list(struct.unpack(f"{n}f", blob))
        except Exception:
            pass
    if isinstance(blob, str):
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return None
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --- Reduction 1024D -> 2D ---


def _reduce_to_2d(embeddings: list[list[float]]) -> list[tuple[float, float]]:
    """PCA pure-python si scikit absent, sinon UMAP/PCA via sklearn."""
    if not embeddings:
        return []
    try:
        from sklearn.decomposition import PCA
        import numpy as np

        X = np.array(embeddings)
        pca = PCA(n_components=2)
        reduced = pca.fit_transform(X)
        return [(float(x), float(y)) for x, y in reduced]
    except ImportError:
        # Fallback : PCA pure-python (slow mais marche)
        return _pca_naive_2d(embeddings)


def _pca_naive_2d(embeddings: list[list[float]]) -> list[tuple[float, float]]:
    """PCA pure-python 2 composantes. Pour bootstrap sans sklearn."""
    n = len(embeddings)
    if n == 0:
        return []
    dim = len(embeddings[0])
    # Centrer
    means = [sum(e[i] for e in embeddings) / n for i in range(dim)]
    centered = [[e[i] - means[i] for i in range(dim)] for e in embeddings]
    # Projection sur 2 directions arbitraires (first dim + median dim) - approximation
    # Pour vraie PCA : SVD ou power iteration. Ici approche heuristique.
    return [(c[0] / max(1, dim), c[dim // 2] / max(1, dim)) for c in centered]


# --- Place cells (clusters) ---


def _kmeans_simple(points: list[tuple[float, float]], k: int = 50, max_iter: int = 20) -> list[int]:
    """KMeans 2D simple. Retourne assign[i] = cluster_idx."""
    if not points:
        return []
    try:
        from sklearn.cluster import KMeans
        import numpy as np

        X = np.array(points)
        km = KMeans(n_clusters=min(k, len(points)), random_state=42, n_init=10)
        return km.fit_predict(X).tolist()
    except ImportError:
        # Fallback naif : bin sur grille
        if not points:
            return []
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        side = int(math.sqrt(k))
        dx = (xmax - xmin) / max(1, side) or 1
        dy = (ymax - ymin) / max(1, side) or 1
        return [min(side - 1, int((p[0] - xmin) / dx)) * side + min(side - 1, int((p[1] - ymin) / dy)) for p in points]


# --- SpatialMap ---


@dataclass
class SpatialMap:
    coords: dict[str, tuple[float, float]] = field(default_factory=dict)
    place_cells: dict[str, int] = field(default_factory=dict)
    cell_centers: dict[int, tuple[float, float]] = field(default_factory=dict)
    embeddings: dict[str, list[float]] = field(default_factory=dict)

    def build_from_chunks(self, domain_filter: str | None = None, limit: int = 5000, n_place_cells: int = 50):
        """Index offline : load chunks + reduce dim + cluster en place cells."""
        conn = sqlite3.connect(str(DB), timeout=30)
        try:
            where = "WHERE (active IS NULL OR active = 1)"
            params: list = []
            if domain_filter:
                where += " AND domain LIKE ?"
                params.append(f"%{domain_filter}%")
            params.append(limit)

            cur = conn.execute(
                f"""
                SELECT id, embedding FROM rag_chunks
                {where}
                LIMIT ?
            """,
                params,
            )

            chunk_ids = []
            embeddings = []
            for row in cur.fetchall():
                emb = _embedding_from_blob(row[1])
                if emb and len(emb) >= 32:
                    chunk_ids.append(row[0])
                    embeddings.append(emb)
                    self.embeddings[row[0]] = emb
        finally:
            conn.close()

        if not embeddings:
            logger.warning("aucun embedding trouve")
            return

        logger.info(f"reducing {len(embeddings)} embeddings to 2D...")
        coords_2d = _reduce_to_2d(embeddings)
        for cid, xy in zip(chunk_ids, coords_2d):
            self.coords[cid] = xy

        logger.info(f"clustering {len(coords_2d)} points en {n_place_cells} place cells...")
        clusters = _kmeans_simple(coords_2d, k=n_place_cells)
        cluster_points: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for cid, c, xy in zip(chunk_ids, clusters, coords_2d):
            self.place_cells[cid] = c
            cluster_points[c].append(xy)

        # Centres des place cells
        for c, pts in cluster_points.items():
            xc = sum(p[0] for p in pts) / len(pts)
            yc = sum(p[1] for p in pts) / len(pts)
            self.cell_centers[c] = (xc, yc)

        logger.info(f"map built: {len(self.coords)} chunks, {len(self.cell_centers)} place cells")
        self.save()

    def save(self, path: Path = MAP_CACHE):
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "coords": self.coords,
                    "place_cells": self.place_cells,
                    "cell_centers": self.cell_centers,
                },
                f,
            )
        logger.info(f"saved to {path}")

    def load(self, path: Path = MAP_CACHE) -> bool:
        if not path.exists():
            return False
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.coords = data.get("coords", {})
        self.place_cells = data.get("place_cells", {})
        self.cell_centers = data.get("cell_centers", {})
        return True

    def locate(self, chunk_id: str) -> tuple[float, float, int] | None:
        if chunk_id not in self.coords:
            return None
        x, y = self.coords[chunk_id]
        pc = self.place_cells.get(chunk_id, -1)
        return (x, y, pc)

    def neighbors(self, x: float, y: float, radius: float = 0.5, limit: int = 20) -> list[tuple[str, float]]:
        """Chunks dans rayon euclidien autour de (x, y)."""
        nbrs = []
        for cid, (cx, cy) in self.coords.items():
            d = math.sqrt((cx - x) ** 2 + (cy - y) ** 2)
            if d <= radius:
                nbrs.append((cid, d))
        nbrs.sort(key=lambda x: x[1])
        return nbrs[:limit]

    def neighbors_of(self, chunk_id: str, radius: float = 0.5) -> list[tuple[str, float]]:
        loc = self.locate(chunk_id)
        if not loc:
            return []
        return self.neighbors(loc[0], loc[1], radius)

    def cell_chunks(self, place_cell_id: int) -> list[str]:
        return [cid for cid, c in self.place_cells.items() if c == place_cell_id]

    def stats(self) -> dict:
        return {
            "n_chunks": len(self.coords),
            "n_place_cells": len(self.cell_centers),
            "avg_chunks_per_cell": (len(self.coords) // max(1, len(self.cell_centers))),
        }


# --- CLI ---


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="Build map from rag_chunks")
    ap.add_argument("--domain", default="watch_veille")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--n-cells", type=int, default=50)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--locate", help="Locate chunk_id")
    ap.add_argument("--neighbors", help="chunk_id pour list neighbors")
    args = ap.parse_args()

    sm = SpatialMap()
    if args.build:
        sm.build_from_chunks(domain_filter=args.domain, limit=args.limit, n_place_cells=args.n_cells)

    sm.load()

    if args.stats:
        print(json.dumps(sm.stats(), indent=2))
    if args.locate:
        print(json.dumps({"chunk": args.locate, "location": sm.locate(args.locate)}, indent=2))
    if args.neighbors:
        nbrs = sm.neighbors_of(args.neighbors, radius=1.0)[:10]
        print(json.dumps({"chunk": args.neighbors, "neighbors": nbrs}, indent=2))


if __name__ == "__main__":
    main()
