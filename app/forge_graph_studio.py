"""
forge_graph_studio.py — Nokido Universal Graph Studio v1
==========================================================
Plateforme générale d'étude de graphes — indépendante du domaine.

Fonctionnalités :
    ┌─ CHARGEMENT ──────────────────────────────────────────────────────────┐
    │  load_csv(edges, nodes)   CSV → GraphStudio                          │
    │  load_json(path)          JSON adjacency / d3 / cytoscape            │
    │  load_matrix(A)           matrice numpy/scipy → GraphStudio          │
    │  load_nx(G)               networkx → GraphStudio                     │
    │  load_pyg(data)           torch_geometric.Data → GraphStudio         │
    │  generators               erdos_renyi, barabasi_albert, grid, tree,  │
    │                           karate_club, les_miserables, florentine    │
    └───────────────────────────────────────────────────────────────────────┘
    ┌─ ANALYSE ─────────────────────────────────────────────────────────────┐
    │  centrality()             degree, betweenness, closeness, eigenvector│
    │  communities()            Louvain, Girvan-Newman, k-cliques           │
    │  paths(src, dst)          shortest path, all simple paths            │
    │  clustering()             local + global clustering coefficient       │
    │  components()             connected, strongly connected              │
    │  motifs()                 triangles, squares, stars                  │
    │  spectral()               eigenvalues laplacien, spectre             │
    └───────────────────────────────────────────────────────────────────────┘
    ┌─ GNN ─────────────────────────────────────────────────────────────────┐
    │  node2vec_embed()         embeddings Node2Vec (random walks)         │
    │  gnn_node_classify()      GNN node classification (labels requis)    │
    │  gnn_link_predict()       link prediction                            │
    │  gnn_graph_classify()     classification de graphes entiers          │
    │  gnn_embed()              embedding de graphe (unsupervised)         │
    └───────────────────────────────────────────────────────────────────────┘
    ┌─ VISUALISATION ───────────────────────────────────────────────────────┐
    │  draw(layout)             spring/circular/spectral/kamada/shell      │
    │  draw_communities()       communautés colorées                       │
    │  draw_centrality(metric)  taille des nœuds ∝ centralité             │
    │  to_gephi()               export GEXF pour Gephi                    │
    │  to_cytoscape()           export JSON Cytoscape.js                  │
    └───────────────────────────────────────────────────────────────────────┘
    ┌─ EXPORT ──────────────────────────────────────────────────────────────┐
    │  summary()                stats globales                             │
    │  report()                 rapport complet JSON/markdown              │
    │  to_pyg()                 → torch_geometric.Data                    │
    │  to_nx()                  → networkx.Graph                          │
    └───────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json

# DEAD_IMPORT removed: import math
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import contextlib
import io
import sys as _sys

import networkx as nx
import numpy as np
import torch
from torch_geometric.data import Data
from torch_geometric.utils import to_networkx


# ── Leiden helpers (graphify-inspired) ───────────────────────────────────────


def _leiden_partition(G: nx.Graph) -> dict:
    """Leiden via graspologic, Louvain fallback. Returns {node: cid}."""
    try:
        from graspologic.partition import leiden

        old_err = _sys.stderr
        try:
            _sys.stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()):
                return leiden(G, random_seed=42)
        finally:
            _sys.stderr = old_err
    except ImportError:
        import inspect

        kw: dict = {"seed": 42, "threshold": 1e-4}
        if "max_level" in inspect.signature(nx.community.louvain_communities).parameters:
            kw["max_level"] = 10
        comms = nx.community.louvain_communities(G, **kw)
        return {n: cid for cid, nodes in enumerate(comms) for n in nodes}


def _gs_cohesion(G: nx.Graph, nodes: list) -> float:
    n = len(nodes)
    if n <= 1:
        return 1.0
    possible = n * (n - 1) / 2
    return round(G.subgraph(nodes).number_of_edges() / possible, 3) if possible else 0.0


def _gs_split_community(G: nx.Graph, nodes: list) -> list[list]:
    sub = G.subgraph(nodes)
    if sub.number_of_edges() == 0:
        return [[n] for n in nodes]
    try:
        part = _leiden_partition(sub)  # uses random_seed=42
        result: dict[int, list] = {}
        for n, cid in part.items():
            result.setdefault(cid, []).append(n)
        return list(result.values()) if len(result) > 1 else [list(nodes)]
    except Exception:
        return [list(nodes)]


def _leiden_communities(G: nx.Graph) -> list[set]:
    """Leiden + 2-pass cohesion split. Returns list of sets."""
    if G.number_of_nodes() == 0:
        return []
    Gu = G.to_undirected() if G.is_directed() else G

    isolates = [n for n in Gu.nodes() if Gu.degree(n) == 0]
    connected = Gu.subgraph([n for n in Gu.nodes() if Gu.degree(n) > 0])

    raw: dict[int, list] = {}
    if connected.number_of_nodes() > 0:
        for n, cid in _leiden_partition(connected).items():
            raw.setdefault(cid, []).append(n)

    next_cid = max(raw.keys(), default=-1) + 1
    for n in isolates:
        raw[next_cid] = [n]
        next_cid += 1

    # Split oversized communities (>25% graph, min 10)
    max_sz = max(10, int(Gu.number_of_nodes() * 0.25))
    pass1: list[list] = []
    for nodes in raw.values():
        if len(nodes) > max_sz:
            pass1.extend(_gs_split_community(Gu, nodes))
        else:
            pass1.append(nodes)

    # 2nd pass: cohesion re-split (doc-hub nodes bridging unrelated systems)
    final: list[list] = []
    for nodes in pass1:
        if len(nodes) >= 50 and _gs_cohesion(Gu, nodes) < 0.05:
            splits = _gs_split_community(Gu, nodes)
            final.extend(splits if len(splits) > 1 else [nodes])
        else:
            final.append(nodes)

    final.sort(key=len, reverse=True)
    return [set(nodes) for nodes in final]


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHSTUDIO — conteneur central
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class GraphStats:
    n_nodes: int
    n_edges: int
    density: float
    is_directed: bool
    is_connected: bool
    n_components: int
    avg_degree: float
    avg_clustering: float
    diameter: Optional[int]
    n_communities: Optional[int]
    largest_cc_frac: float


class GraphStudio:
    """
    Objet central de l'étude de graphe.
    Wraps un networkx.Graph/DiGraph avec toutes les méthodes d'analyse et GNN.
    """

    def __init__(
        self,
        G: nx.Graph,
        name: str = "graph",
        node_features: Optional[np.ndarray] = None,
        node_labels: Optional[dict] = None,
        edge_features: Optional[dict] = None,
    ):
        self.G = G
        self.name = name
        self._nf = node_features  # numpy [N, d]
        self._nl = node_labels  # {node_id: label_int}
        self._ef = edge_features  # {(u,v): feat}
        self._communities = None
        self._centrality = {}
        self._node2vec_emb = None
        self._stats_cache: dict = {}  # keyed on (n, m)
        self._centrality_cache: dict = {}  # keyed on (n, m, metrics_tuple)

    # ── Propriétés de base ────────────────────────────────────────────────

    @property
    def nodes(self):
        return list(self.G.nodes())

    @property
    def edges(self):
        return list(self.G.edges())

    @property
    def n(self):
        return self.G.number_of_nodes()

    @property
    def m(self):
        return self.G.number_of_edges()

    @property
    def directed(self):
        return self.G.is_directed()

    # ── CHARGEMENT ────────────────────────────────────────────────────────

    @classmethod
    def from_csv(
        cls,
        edges_path: str,
        nodes_path: str = "",
        src_col: str = "src",
        dst_col: str = "dst",
        weight_col: str = "",
        directed: bool = False,
        name: str = "",
    ) -> "GraphStudio":
        """Charge depuis CSV d'arêtes (et optionnellement de nœuds)."""
        import pandas as pd

        df = pd.read_csv(edges_path)
        G = nx.DiGraph() if directed else nx.Graph()
        for _, row in df.iterrows():
            u, v = row[src_col], row[dst_col]
            kwargs = {}
            if weight_col and weight_col in row:
                kwargs["weight"] = float(row[weight_col])
            G.add_edge(u, v, **kwargs)

        node_feat = None
        node_lab = None
        if nodes_path:
            ndf = pd.read_csv(nodes_path)
            # Features : colonnes numériques sauf 'id'
            feat_cols = [
                c
                for c in ndf.columns
                if c not in ("id", "label", "name") and ndf[c].dtype in (float, int, "float64", "int64")
            ]
            if feat_cols:
                node_feat = ndf[feat_cols].values.astype(np.float32)
            if "label" in ndf.columns:
                node_lab = dict(zip(ndf["id"], ndf["label"]))

        return cls(G, name=name or Path(edges_path).stem, node_features=node_feat, node_labels=node_lab)

    @classmethod
    def from_json(cls, path: str, name: str = "") -> "GraphStudio":
        """Charge depuis un fichier JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data, name=name or Path(path).stem)

    @classmethod
    def from_dict(cls, data: dict | list, name: str = "imported_graph") -> "GraphStudio":
        """
        Charge un graphe depuis un dictionnaire ou une liste.
        Formats supportés :
            - {"nodes": [...], "links": [...]}    (D3.js / Cytoscape)
            - {"nodes": [...], "edges": [...]}    (Alternatif)
            - {"adjacency": {...}}                 (adjacency list)
            - networkx adjacency JSON
            - liste d'arêtes [[u,v], ...]
        """
        if isinstance(data, dict):
            if "nodes" in data and ("links" in data or "edges" in data):
                # Format node-link (D3/Cytoscape)
                links = data.get("links", data.get("edges", []))
                G = nx.Graph()
                for n in data["nodes"]:
                    if isinstance(n, dict):
                        nid = n.get("id", n.get("name", str(n)))
                        attr = {k: v for k, v in n.items() if k not in ("id", "name")}
                        G.add_node(nid, **attr)
                    else:
                        G.add_node(n)
                for e in links:
                    if isinstance(e, dict):
                        u = e.get("source", e.get("src", e.get("u")))
                        v = e.get("target", e.get("dst", e.get("v")))
                        if u is not None and v is not None:
                            attr = {
                                k: v2 for k, v2 in e.items() if k not in ("source", "target", "src", "dst", "u", "v")
                            }
                            G.add_edge(u, v, **attr)
                    elif isinstance(e, (list, tuple)) and len(e) >= 2:
                        G.add_edge(e[0], e[1])
                return cls(G, name=name)

            if "adjacency" in data:
                G = nx.from_dict_of_dicts(data["adjacency"])
                return cls(G, name=name)

            # Tentative via networkx native
            try:
                G = nx.node_link_graph(data)
                return cls(G, name=name)
            except Exception:
                pass

        # Cas liste d'arêtes directe
        if isinstance(data, list):
            G = nx.Graph()
            for item in data:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    G.add_edge(item[0], item[1])
            return cls(G, name=name)

        raise ValueError("Format de données JSON non reconnu pour un graphe")

    @classmethod
    def from_matrix(
        cls, A: np.ndarray, directed: bool = False, node_ids: Optional[list] = None, name: str = "matrix_graph"
    ) -> "GraphStudio":
        """Charge depuis une matrice d'adjacence numpy/scipy."""
        try:
            from scipy.sparse import issparse

            if issparse(A):
                A = A.toarray()
        except ImportError:
            pass
        if directed:
            G = nx.from_numpy_array(A, create_using=nx.DiGraph())
        else:
            G = nx.from_numpy_array(A)
        if node_ids:
            mapping = {i: nid for i, nid in enumerate(node_ids)}
            G = nx.relabel_nodes(G, mapping)
        return cls(G, name=name)

    @classmethod
    def from_nx(cls, G: nx.Graph, name: str = "") -> "GraphStudio":
        return cls(G, name=name or "nx_graph")

    @classmethod
    def from_pyg(cls, data: Data, node_ids: Optional[list] = None, name: str = "pyg_graph") -> "GraphStudio":
        G = to_networkx(data, to_undirected=not data.is_directed() if hasattr(data, "is_directed") else True)
        if node_ids:
            G = nx.relabel_nodes(G, {i: nid for i, nid in enumerate(node_ids)})
        feat = data.x.numpy() if data.x is not None else None
        labs = None
        if data.y is not None:
            labs = {i: int(y) for i, y in enumerate(data.y.tolist())}
        return cls(G, name=name, node_features=feat, node_labels=labs)

    # ── GÉNÉRATEURS ───────────────────────────────────────────────────────

    @classmethod
    def erdos_renyi(cls, n: int, p: float, seed: int = 42) -> "GraphStudio":
        """Graphe aléatoire Erdős–Rényi G(n,p)."""
        return cls(nx.erdos_renyi_graph(n, p, seed=seed), f"ER_n{n}_p{p}")

    @classmethod
    def barabasi_albert(cls, n: int, m: int = 2, seed: int = 42) -> "GraphStudio":
        """Graphe scale-free Barabási–Albert (attachement préférentiel)."""
        return cls(nx.barabasi_albert_graph(n, m, seed=seed), f"BA_n{n}_m{m}")

    @classmethod
    def watts_strogatz(cls, n: int, k: int = 4, p: float = 0.1) -> "GraphStudio":
        """Petit-monde Watts–Strogatz."""
        return cls(nx.watts_strogatz_graph(n, k, p), f"WS_n{n}_k{k}_p{p}")

    @classmethod
    def karate_club(cls) -> "GraphStudio":
        """Zachary's karate club — graphe de référence benchmark."""
        G = nx.karate_club_graph()
        labs = {n: 0 if d["club"] == "Mr. Hi" else 1 for n, d in G.nodes(data=True)}
        return cls(G, "karate_club", node_labels=labs)

    @classmethod
    def grid(cls, rows: int, cols: int) -> "GraphStudio":
        return cls(nx.grid_2d_graph(rows, cols), f"grid_{rows}x{cols}")

    @classmethod
    def tree(cls, n: int, branching: int = 2) -> "GraphStudio":
        return cls(nx.balanced_tree(branching, n), f"tree_b{branching}_h{n}")

    @classmethod
    def complete(cls, n: int) -> "GraphStudio":
        return cls(nx.complete_graph(n), f"K{n}")

    @classmethod
    def les_miserables(cls) -> "GraphStudio":
        """Graphe des co-apparitions dans Les Misérables."""
        return cls(nx.les_miserables_graph(), "les_miserables")

    @classmethod
    def florentine_families(cls) -> "GraphStudio":
        """Graphe des familles florentines (Médicis)."""
        return cls(nx.florentine_families_graph(), "florentine_families")

    # ── ANALYSE ───────────────────────────────────────────────────────────

    def stats(self) -> GraphStats:
        """Calcule les statistiques globales du graphe."""
        cache_key = (self.n, self.m)
        if cache_key in self._stats_cache:
            return self._stats_cache[cache_key]
        G = self.G
        Gu = G.to_undirected() if G.is_directed() else G
        cc = list(nx.connected_components(Gu))
        largest_frac = max(len(c) for c in cc) / max(1, self.n) if cc else 0
        is_conn = nx.is_connected(Gu)
        try:
            diam = nx.diameter(Gu) if is_conn and self.n < 5000 else None
        except Exception:
            diam = None
        avg_clust = nx.average_clustering(Gu) if self.n < 10000 else 0.0
        degs = [d for _, d in G.degree()]
        result = GraphStats(
            n_nodes=self.n,
            n_edges=self.m,
            density=nx.density(G),
            is_directed=G.is_directed(),
            is_connected=is_conn,
            n_components=len(cc),
            avg_degree=sum(degs) / max(1, len(degs)),
            avg_clustering=avg_clust,
            diameter=diam,
            n_communities=len(self._communities) if self._communities else None,
            largest_cc_frac=largest_frac,
        )
        self._stats_cache[cache_key] = result
        return result

    def centrality(self, metrics: list[str] = None) -> dict[str, dict]:
        """
        Calcule les métriques de centralité.

        metrics : liste parmi ['degree','betweenness','closeness',
                                'eigenvector','pagerank','katz','harmonic']
        """
        if metrics is None:
            metrics = ["degree", "betweenness", "closeness", "pagerank"]
        cache_key = (self.n, self.m, tuple(sorted(metrics)))
        if cache_key in self._centrality_cache:
            return self._centrality_cache[cache_key]
        G = self.G
        result = {}
        for m in metrics:
            t0 = time.perf_counter()
            if m == "degree":
                result[m] = dict(nx.degree_centrality(G))
            elif m == "betweenness":
                result[m] = nx.betweenness_centrality(G, k=min(100, self.n) if self.n > 200 else None)
            elif m == "closeness":
                result[m] = dict(nx.closeness_centrality(G))
            elif m == "eigenvector":
                try:
                    result[m] = nx.eigenvector_centrality(G, max_iter=1000)
                except nx.PowerIterationFailedConvergence:
                    result[m] = dict(nx.degree_centrality(G))
            elif m == "pagerank":
                result[m] = nx.pagerank(G)
            elif m == "katz":
                result[m] = nx.katz_centrality(G)
            elif m == "harmonic":
                result[m] = nx.harmonic_centrality(G)
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"  [Centrality] {m}: {elapsed:.1f}ms")
        self._centrality = result
        self._centrality_cache[cache_key] = result
        return result

    def communities(self, method: str = "leiden", k: int = 4) -> list[set]:
        """
        Détection de communautés.

        method : 'leiden' | 'louvain' | 'girvan_newman' | 'label_propagation'
                 | 'greedy_modularity' | 'spectral'
        """
        G = self.G.to_undirected() if self.G.is_directed() else self.G
        t0 = time.perf_counter()

        if method == "leiden":
            result = _leiden_communities(G)

        elif method == "louvain":
            try:
                import community as cm

                partition = cm.best_partition(G)
                comms = {}
                for node, cid in partition.items():
                    comms.setdefault(cid, set()).add(node)
                result = list(comms.values())
            except ImportError:
                result = list(nx.community.greedy_modularity_communities(G))

        elif method == "girvan_newman":
            gn = nx.community.girvan_newman(G)
            for _ in range(k - 1):
                comms = next(gn)
            result = [set(c) for c in comms]

        elif method == "label_propagation":
            result = list(nx.community.label_propagation_communities(G))

        elif method == "greedy_modularity":
            result = list(nx.community.greedy_modularity_communities(G))

        elif method == "spectral":
            from sklearn.cluster import SpectralClustering

            A = nx.to_numpy_array(G)
            sc = SpectralClustering(n_clusters=k, affinity="precomputed", random_state=42)
            labels = sc.fit_predict(A)
            comms = {}
            for node, lab in zip(G.nodes(), labels):
                comms.setdefault(int(lab), set()).add(node)
            result = list(comms.values())

        else:
            result = list(nx.community.greedy_modularity_communities(G))

        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  [Communities] {method}: {len(result)} communautés {elapsed:.1f}ms")
        self._communities = result
        return result

    def paths(self, src: Any, dst: Any, k: int = 3) -> dict:
        """Chemins entre deux nœuds."""
        result = {"shortest": None, "length": None, "k_shortest": []}
        try:
            sp = nx.shortest_path(self.G, src, dst)
            result["shortest"] = sp
            result["length"] = len(sp) - 1
        except nx.NetworkXNoPath:
            result["shortest"] = []
        try:
            from itertools import islice

            all_paths = nx.shortest_simple_paths(self.G, src, dst)
            result["k_shortest"] = list(islice(all_paths, k))
        except Exception:
            pass
        return result

    def clustering(self) -> dict:
        """Coefficients de clustering par nœud + global."""
        G = self.G.to_undirected() if self.G.is_directed() else self.G
        local = nx.clustering(G)
        global_c = nx.average_clustering(G)
        transitivity = nx.transitivity(G)
        return {"local": local, "global": global_c, "transitivity": transitivity}

    def spectral(self, k: int = 10) -> dict:
        """
        Analyse spectrale du laplacien.
        Retourne les k plus petites valeurs propres.
        """
        G = self.G.to_undirected() if self.G.is_directed() else self.G
        L = nx.laplacian_matrix(G).toarray().astype(np.float64)
        eigvals = np.linalg.eigvalsh(L)
        eigvals.sort()
        fiedler = float(eigvals[1]) if len(eigvals) > 1 else 0.0
        return {
            "eigenvalues": eigvals[:k].tolist(),
            "fiedler_value": fiedler,  # algébrique connectivity
            "spectral_gap": float(eigvals[1] - eigvals[0]) if len(eigvals) > 1 else 0.0,
            "spectral_radius": float(eigvals[-1]),
        }

    def top_nodes(self, metric: str = "pagerank", k: int = 10) -> list[tuple]:
        """Top-k nœuds par centralité."""
        if metric not in self._centrality:
            self.centrality([metric])
        c = self._centrality[metric]
        return sorted(c.items(), key=lambda x: -x[1])[:k]

    def god_nodes(self, top_n: int = 10) -> list[dict]:
        """Top-n nœuds les plus connectés, hors file-hubs et concept nodes.

        Exclut : label == basename(source_file), stubs .method(), nœuds sans source_file.
        Inspiré de graphify analyze.py — évite que CLAUDE.md ou __init__.py dominent.
        """
        from pathlib import Path as _P

        G = self.G
        result = []
        for node_id, deg in sorted(G.degree(), key=lambda x: x[1], reverse=True):
            attrs = G.nodes[node_id]
            label = attrs.get("label", str(node_id))
            source = attrs.get("source_file", "")
            if source and label == _P(source).name:
                continue
            if label.startswith(".") and label.endswith("()"):
                continue
            if label.endswith("()") and deg <= 1:
                continue
            if not source or "." not in source.replace("\\", "/").split("/")[-1]:
                continue
            result.append({"id": node_id, "label": label, "degree": deg, "source_file": source})
            if len(result) >= top_n:
                break
        return result

    def motifs(self) -> dict:
        """Comptage de motifs locaux : triangles, étoiles."""
        G = self.G.to_undirected() if self.G.is_directed() else self.G
        triangles = sum(nx.triangles(G).values()) // 3
        return {
            "triangles": int(triangles),
            "n_cliques": sum(1 for _ in nx.find_cliques(G)) if self.n < 1000 else -1,
            "max_clique_size": len(max(nx.find_cliques(G), key=len)) if self.n < 1000 else -1,
        }

    # ── NODE2VEC EMBEDDINGS ────────────────────────────────────────────────

    def node2vec(
        self,
        dim: int = 64,
        walk_length: int = 30,
        num_walks: int = 200,
        p: float = 1.0,
        q: float = 1.0,
        workers: int = 1,
    ) -> np.ndarray:
        """
        Embeddings Node2Vec (random walks + Word2Vec).

        p : paramètre retour (BFS vs DFS)
        q : paramètre in-out (exploration)

        Retourne array [N, dim]
        """
        try:
            from node2vec import Node2Vec

            n2v = Node2Vec(
                self.G,
                dimensions=dim,
                walk_length=walk_length,
                num_walks=num_walks,
                p=p,
                q=q,
                workers=workers,
                quiet=True,
            )
            model = n2v.fit(window=10, min_count=1)
            emb = np.array([model.wv[str(n)] for n in self.G.nodes()])
            self._node2vec_emb = emb
            print(f"  [Node2Vec] embeddings: {emb.shape}")
            return emb
        except ImportError:
            print("  [Node2Vec] node2vec non installé — skip")
            return np.zeros((self.n, dim))

    # ── GNN ───────────────────────────────────────────────────────────────

    def to_pyg(self, feature_dim: int = 16) -> Data:
        """
        Convertit en torch_geometric.Data.
        Si pas de features, utilise les degrés + centralités comme features.
        """
        G = self.G
        nodes = list(G.nodes())
        n_idx = {n: i for i, n in enumerate(nodes)}

        # Features : degree + (node2vec si dispo) + node_features custom
        degs = np.array([G.degree(n) for n in nodes], dtype=np.float32).reshape(-1, 1)
        max_deg = degs.max() + 1e-8

        if self._nf is not None and len(self._nf) == len(nodes):
            x = torch.tensor(self._nf, dtype=torch.float32)
        elif self._node2vec_emb is not None:
            x = torch.tensor(self._node2vec_emb, dtype=torch.float32)
        else:
            # Features basiques : degree normalisé + log-degree + position spectrale
            deg_norm = degs / max_deg
            log_deg = np.log1p(degs)
            # One-hot local neighborhood density
            density = np.array(
                [nx.density(G.subgraph(list(G.neighbors(n)) + [n])) for n in nodes], dtype=np.float32
            ).reshape(-1, 1)
            x = torch.tensor(np.hstack([deg_norm, log_deg, density]), dtype=torch.float32)
            # Padding jusqu'à feature_dim
            if x.shape[1] < feature_dim:
                pad = torch.zeros(len(nodes), feature_dim - x.shape[1])
                x = torch.cat([x, pad], dim=1)

        # Arêtes
        src, dst = zip(*[(n_idx[u], n_idx[v]) for u, v in G.edges()]) if G.edges() else ([], [])
        if src:
            edge_index = torch.tensor([list(src) + list(dst), list(dst) + list(src)], dtype=torch.long)
        else:
            edge_index = torch.zeros(2, 0, dtype=torch.long)

        data = Data(x=x, edge_index=edge_index)
        data.num_nodes = len(nodes)
        data.node_ids = nodes

        # Labels
        if self._nl:
            y_vals = [self._nl.get(n, 0) for n in nodes]
            data.y = torch.tensor(y_vals, dtype=torch.long)

        return data

    def gnn_embed(self, hidden: int = 32, n_layers: int = 2, epochs: int = 100) -> np.ndarray:
        """
        Embedding de graphe non-supervisé via autoencodeur GNN.
        Retourne les embeddings de nœuds [N, hidden].
        """
        from app.forge_gnn import ForgeGNNLayer
        import torch.nn as nn
        import torch.nn.functional as F

        data = self.to_pyg()
        in_dim = data.x.shape[1]

        class GraphAutoEncoder(nn.Module):
            def __init__(self):
                super().__init__()
                self.enc = nn.ModuleList(
                    [ForgeGNNLayer(in_dim if i == 0 else hidden, hidden, heads=2) for i in range(n_layers)]
                )
                self.dec = nn.Linear(hidden, in_dim)

            def forward(self, x, edge_index):
                h = x
                for layer in self.enc:
                    h = layer(h, edge_index)
                return h, self.dec(h)

        model = GraphAutoEncoder()
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        for ep in range(epochs):
            model.train()
            opt.zero_grad()
            h, x_hat = model(data.x, data.edge_index)
            loss = F.mse_loss(x_hat, data.x)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            emb, _ = model(data.x, data.edge_index)
        result = emb.numpy()
        print(f"  [GNN Embed] {result.shape} (loss={float(loss):.5f})")
        return result

    def gnn_node_classify(self, hidden: int = 32, n_layers: int = 2, epochs: int = 200, lr: float = 1e-3) -> dict:
        """
        Classification de nœuds supervisée (nécessite node_labels).
        Retourne les prédictions + accuracy.
        """
        if not self._nl:
            raise ValueError("node_labels requis pour la classification de nœuds")
        from app.forge_gnn import NetworkGNN, GNNTrainer
        import torch.nn.functional as F

        data = self.to_pyg()
        n_cls = len(set(self._nl.values()))

        model = NetworkGNN(in_dim=data.x.shape[1], hidden=hidden, n_classes=n_cls, n_layers=n_layers)
        trainer = GNNTrainer(model, lr=lr)
        trainer.train(data, n_epochs=epochs, task="node", log_every=epochs // 5 or 1)

        model.eval()
        with torch.no_grad():
            logits = model(data.x, data.edge_index)
            preds = logits.argmax(dim=-1)
            if data.y is not None:
                acc = float((preds == data.y).float().mean())
            else:
                acc = None

        nodes = list(self.G.nodes())
        result = {n: int(preds[i]) for i, n in enumerate(nodes)}
        return {"predictions": result, "accuracy": acc, "n_classes": n_cls, "history": trainer.history[-5:]}

    def gnn_link_predict(self, hidden: int = 32, n_layers: int = 2, epochs: int = 100) -> dict:
        """
        Link prediction — score de probabilité pour chaque paire de nœuds.
        Retourne les top-20 liens manquants les plus probables.
        """
        from app.forge_gnn import KnowledgeGNN
        import torch.nn.functional as F

        data = self.to_pyg()
        model = KnowledgeGNN(in_dim=data.x.shape[1], hidden=hidden, n_layers=n_layers)
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)

        # Entraînement : liens positifs vs liens négatifs aléatoires
        edge_set = set(map(tuple, data.edge_index.t().tolist()))
        nodes_t = torch.arange(self.n)

        for ep in range(epochs):
            model.train()
            opt.zero_grad()
            # Positifs
            pos_src = data.edge_index[0, : min(64, data.edge_index.shape[1])]
            pos_dst = data.edge_index[1, : min(64, data.edge_index.shape[1])]
            # Négatifs
            neg_src = torch.randint(0, self.n, (len(pos_src),))
            neg_dst = torch.randint(0, self.n, (len(pos_src),))

            src = torch.cat([pos_src, neg_src])
            dst = torch.cat([pos_dst, neg_dst])
            y = torch.cat([torch.ones(len(pos_src)), torch.zeros(len(neg_src))])

            pred = model(data.x, data.edge_index, src, dst).squeeze()
            loss = F.binary_cross_entropy(pred, y)
            loss.backward()
            opt.step()

        # Prédire liens manquants
        model.eval()
        z = model.encode(data.x, data.edge_index)
        candidates = []
        with torch.no_grad():
            sample = min(200, self.n)
            for i in range(sample):
                for j in range(i + 1, sample):
                    if (i, j) not in edge_set and (j, i) not in edge_set:
                        s = model.decode_link(z, torch.tensor([i]), torch.tensor([j])).item()
                        candidates.append((i, j, s))
        candidates.sort(key=lambda x: -x[2])
        nodes = list(self.G.nodes())
        return {
            "top_missing_links": [
                {"src": nodes[i], "dst": nodes[j], "score": round(s, 4)} for i, j, s in candidates[:20]
            ],
            "final_loss": round(float(loss), 5),
        }

    # ── VISUALISATION ─────────────────────────────────────────────────────

    def draw(
        self,
        layout: str = "spring",
        figsize: tuple = (10, 8),
        save_path: str = "",
        show: bool = True,
        with_labels: bool = True,
        centrality_metric: str = "",
    ) -> None:
        """
        Visualise le graphe.

        layout : spring | circular | spectral | kamada_kawai | shell | random | planar
        centrality_metric : si fourni, taille des nœuds ∝ centralité
        """
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm

        G = self.G
        fig, ax = plt.subplots(figsize=figsize)
        ax.set_title(f"{self.name}  (n={self.n}, m={self.m})", fontsize=14)
        ax.axis("off")

        # Layout
        layouts = {
            "spring": lambda: nx.spring_layout(G, seed=42),
            "circular": nx.circular_layout,
            "spectral": nx.spectral_layout,
            "kamada_kawai": nx.kamada_kawai_layout,
            "shell": nx.shell_layout,
            "random": lambda: nx.random_layout(G, seed=42),
            "planar": nx.planar_layout,
        }
        pos = layouts.get(layout, layouts["spring"])()
        if callable(pos) and not isinstance(pos, dict):
            pos = pos()

        # Couleurs : communautés
        colors = ["#4C72B0"] * self.n
        if self._communities:
            palette = plt.cm.get_cmap("tab20", len(self._communities))
            color_map = {}
            for i, comm in enumerate(self._communities):
                for node in comm:
                    color_map[node] = palette(i)
            nodes = list(G.nodes())
            colors = [color_map.get(n, "#4C72B0") for n in nodes]

        # Taille des nœuds
        node_size = 300
        if centrality_metric:
            if centrality_metric not in self._centrality:
                self.centrality([centrality_metric])
            c = self._centrality[centrality_metric]
            max_c = max(c.values()) + 1e-8
            node_size = [max(100, 3000 * c.get(n, 0) / max_c) for n in G.nodes()]

        # Edge weights
        weights = None
        if nx.is_weighted(G):
            weights = [G[u][v].get("weight", 1.0) for u, v in G.edges()]
            max_w = max(weights) + 1e-8
            weights = [0.5 + 2.5 * (w / max_w) for w in weights]

        nx.draw_networkx(
            G,
            pos=pos,
            ax=ax,
            with_labels=with_labels,
            node_color=colors,
            node_size=node_size,
            width=weights or 1.0,
            alpha=0.85,
            font_size=8,
            arrows=G.is_directed(),
        )

        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            print(f"  [Draw] Sauvegardé → {save_path}")
        if show:
            plt.show()
        plt.close()

    def draw_communities(self, method: str = "louvain", layout: str = "spring", save_path: str = "") -> None:
        """Visualise les communautés avec couleurs distinctes."""
        if not self._communities:
            self.communities(method)
        self.draw(layout=layout, save_path=save_path)

    # ── EXPORT ────────────────────────────────────────────────────────────

    def to_nx(self) -> nx.Graph:
        return self.G.copy()

    def to_gephi(self, path: str) -> None:
        """Export au format GEXF (Gephi)."""
        nx.write_gexf(self.G, path)
        print(f"  [Export] GEXF → {path}")

    def to_cytoscape(self, path: str) -> None:
        """Export au format JSON Cytoscape.js."""
        data = {
            "elements": {
                "nodes": [{"data": {"id": str(n), **self.G.nodes[n]}} for n in self.G.nodes()],
                "edges": [{"data": {"source": str(u), "target": str(v), **self.G[u][v]}} for u, v in self.G.edges()],
            }
        }
        Path(path).write_text(json.dumps(data, indent=2))
        print(f"  [Export] Cytoscape.js JSON → {path}")

    def summary(self) -> str:
        """Résumé textuel du graphe."""
        s = self.stats()
        lines = [
            f"=== GraphStudio: {self.name} ===",
            f"  Nœuds          : {s.n_nodes}",
            f"  Arêtes         : {s.n_edges}",
            f"  Densité        : {s.density:.4f}",
            f"  Orienté        : {s.is_directed}",
            f"  Connecté       : {s.is_connected}",
            f"  Composantes    : {s.n_components}",
            f"  Degré moyen    : {s.avg_degree:.2f}",
            f"  Clustering moy : {s.avg_clustering:.4f}",
            f"  Diamètre       : {s.diameter}",
            f"  Communautés    : {s.n_communities}",
        ]
        return "\n".join(lines)

    def report(self, path: str = "") -> dict:
        """Rapport complet JSON."""
        s = self.stats()
        data = {
            "name": self.name,
            "stats": s.__dict__,
            "top_nodes_pagerank": self.top_nodes("pagerank", 10) if "pagerank" in self._centrality else [],
            "communities": [list(c) for c in (self._communities or [])],
        }
        if path:
            Path(path).write_text(json.dumps(data, indent=2, default=str))
            print(f"  [Report] JSON → {path}")
        return data

    def __repr__(self):
        return f"GraphStudio({self.name!r}, n={self.n}, m={self.m})"
