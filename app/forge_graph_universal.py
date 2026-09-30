"""
forge_graph_universal.py — Nokido Universal Graph Engine v2
============================================================
Module graph généraliste : cyber, documents, science, finance, médecine...
Exploite la base vectorielle RAG (dim=1024) comme source native de graphe.
"""

from __future__ import annotations
import ast as _ast, json, sqlite3, warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Callable, TypeVar
import numpy as np
from functools import lru_cache

T = TypeVar("T")


def lru_cache_wrapper(
    maxsize: Optional[int] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Wrapper for lru_cache that caches success and exceptions"""

    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        @lru_cache(maxsize=maxsize)
        def wrapper(*args, **kwargs):
            try:
                return ("success", f(*args, **kwargs))
            except Exception as e:
                return ("error", e)

        def wrapped(*args, **kwargs):
            result = wrapper(*args, **kwargs)
            if result[0] == "error":
                raise result[1]
            return result[1]

        return wrapped

    return decorator


try:
    import networkx as nx

    NX_AVAILABLE = True
except ImportError:
    NX_AVAILABLE = False


@dataclass
class GraphNode:
    id: str
    label: str
    domain: str = "general"
    meta: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[np.ndarray] = None

    def to_dict(self):
        return {"id": self.id, "label": self.label, "domain": self.domain, "meta": self.meta}


@dataclass
class GraphEdge:
    src: str
    dst: str
    weight: float = 1.0
    relation: str = "related"
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {"src": self.src, "dst": self.dst, "weight": self.weight, "relation": self.relation}


EMBED_DIM = 1024  # BGE-M3 via brain_worker :5557


class RAGVectorSource:
    """Graphe sémantique depuis la base vectorielle Nokido (dim=1024, cosine)."""

    def __init__(self, db_path, domain_filter=None, sim_threshold=0.82, top_k=5, max_nodes=300, expected_dim=EMBED_DIM):
        self.db_path = Path(db_path)
        self.domain_filter = domain_filter
        self.sim_threshold = sim_threshold
        self.top_k = top_k
        self.max_nodes = max_nodes
        self.expected_dim = expected_dim

    def load(self):
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        q = "SELECT id, text, source, domain, embedding FROM rag_chunks WHERE embedding IS NOT NULL"
        p = []
        if self.domain_filter:
            q += " AND domain = ?"
            p.append(self.domain_filter)
        q += f" LIMIT {self.max_nodes}"
        cur.execute(q, p)
        rows = cur.fetchall()
        conn.close()
        nodes, vecs = [], []
        skipped_dim = 0
        for eid, text, src, dom, emb_raw in rows:
            try:
                vec = np.array(json.loads(emb_raw.decode()), dtype=np.float32)
            except Exception:
                continue
            if vec.shape[0] != self.expected_dim:
                skipped_dim += 1
                continue
            nodes.append(
                GraphNode(
                    id=eid,
                    label=text[:120].replace("\n", " "),
                    domain=dom or "general",
                    meta={"source": src, "full_text": text},
                    embedding=vec,
                )
            )
            vecs.append(vec)
        if skipped_dim:
            warnings.warn(
                f"RAGVectorSource: {skipped_dim} embeddings ignorés (dim≠{self.expected_dim}) — relancer embed_direct.py"
            )
        if len(vecs) < 2:
            return nodes, []
        V = np.stack(vecs)
        V_norm = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-8)
        sim = V_norm @ V_norm.T
        edges = []
        for i in range(len(nodes)):
            s = sim[i].copy()
            s[i] = -1
            for j in np.argsort(s)[::-1][: self.top_k]:
                sim_score = float(sim[i, j])
                if sim_score >= self.sim_threshold:
                    # Edge scoring: boost if same domain or source
                    weight = sim_score
                    if nodes[i].domain == nodes[j].domain:
                        weight *= 1.1
                    src_i = nodes[i].meta.get("source")
                    src_j = nodes[j].meta.get("source")
                    if src_i and src_i == src_j:
                        weight *= 1.2
                    weight = min(round(weight, 4), 1.0)

                    edges.append(
                        GraphEdge(src=nodes[i].id, dst=nodes[j].id, weight=weight, relation="semantic_similarity")
                    )
        return nodes, edges


class CSVSource:
    """Graphe depuis CSV edges/nodes."""

    def __init__(self, edges_path, nodes_path=None, src_col="src", dst_col="dst", weight_col="weight"):
        self.edges_path = Path(edges_path)
        self.nodes_path = Path(nodes_path) if nodes_path else None
        self.src_col = src_col
        self.dst_col = dst_col
        self.weight_col = weight_col

    def load(self):
        import csv

        nodes: Dict[str, GraphNode] = {}
        if self.nodes_path and self.nodes_path.exists():
            with open(self.nodes_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    nid = row.get("id", row.get("name", ""))
                    if nid:
                        nodes[nid] = GraphNode(id=nid, label=row.get("label", nid), domain=row.get("domain", "general"))
        edges = []
        with open(self.edges_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                s, d = row[self.src_col], row[self.dst_col]
                w = float(row.get(self.weight_col, 1.0))
                edges.append(GraphEdge(src=s, dst=d, weight=w))
                for nid in (s, d):
                    if nid not in nodes:
                        nodes[nid] = GraphNode(id=nid, label=nid)
        return list(nodes.values()), edges


class CodeASTSource:
    """Code Python → graphe d'appels de fonctions."""

    def __init__(self, code_or_path):
        p = Path(code_or_path)
        self.code = p.read_text(encoding="utf-8") if p.exists() else str(code_or_path)

    def load(self):
        tree = _ast.parse(self.code)
        nodes: Dict[str, GraphNode] = {"<module>": GraphNode(id="<module>", label="<module>", domain="code")}
        edges = []
        cur = ["<module>"]

        class V(_ast.NodeVisitor):
            def visit_FunctionDef(self, n):
                nodes[n.name] = GraphNode(id=n.name, label=n.name, domain="code", meta={"lineno": n.lineno})
                edges.append(GraphEdge(src=cur[-1], dst=n.name, relation="defines"))
                cur.append(n.name)
                self.generic_visit(n)
                cur.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, n):
                callee = (
                    n.func.id
                    if isinstance(n.func, _ast.Name)
                    else n.func.attr
                    if isinstance(n.func, _ast.Attribute)
                    else None
                )
                if callee:
                    edges.append(GraphEdge(src=cur[-1], dst=callee, relation="calls"))
                    if callee not in nodes:
                        nodes[callee] = GraphNode(id=callee, label=callee, domain="code")
                self.generic_visit(n)

        V().visit(tree)
        return list(nodes.values()), edges


class UniversalGraph:
    """
    Conteneur graph généraliste — backend NetworkX.
    Domaines : cyber, documents, science, finance, médecine, général.
    """

    def __init__(self, name="graph", directed=False):
        self.name = name
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        self._nx = None
        self.directed = directed
        self._neigh_cache: Dict[tuple, "UniversalGraph"] = {}

    @classmethod
    def from_source(cls, source, name="graph", directed=False):
        g = cls(name=name, directed=directed)
        nodes, edges = source.load()
        for n in nodes:
            g.add_node(n)
        for e in edges:
            g.add_edge(e)
        return g

    @classmethod
    @lru_cache_wrapper(maxsize=16)
    def from_rag(
        cls, db_path="RAG/embeddings.db", domain_filter=None, sim_threshold=0.82, top_k=5, max_nodes=300, name=None
    ):
        """Construit un graphe sémantique depuis la base vectorielle Nokido."""
        src = RAGVectorSource(db_path, domain_filter, sim_threshold, top_k, max_nodes)
        return cls.from_source(src, name=name or f"rag_{domain_filter or 'all'}")

    @classmethod
    def from_csv(cls, edges_path, nodes_path=None, **kw):
        return cls.from_source(CSVSource(edges_path, nodes_path, **kw))

    @classmethod
    def from_code(cls, code_or_path):
        return cls.from_source(CodeASTSource(code_or_path), name="ast_graph")

    @classmethod
    def from_networkx(cls, G, name="nx_graph"):
        g = cls(name=name, directed=G.is_directed())
        for nid, data in G.nodes(data=True):
            g.add_node(
                GraphNode(
                    id=str(nid),
                    label=str(data.get("label", nid)),
                    domain=data.get("domain", "general"),
                    meta=dict(data),
                )
            )
        for u, v, data in G.edges(data=True):
            g.add_edge(
                GraphEdge(
                    src=str(u), dst=str(v), weight=data.get("weight", 1.0), relation=data.get("relation", "related")
                )
            )
        return g

    def add_node(self, node: GraphNode):
        self._nodes[node.id] = node
        self._nx = None
        self._neigh_cache.clear()

    def add_edge(self, edge: GraphEdge):
        self._edges.append(edge)
        self._nx = None
        self._neigh_cache.clear()

    @property
    def G(self):
        if not NX_AVAILABLE:
            raise ImportError("networkx requis")
        if self._nx is None:
            self._nx = nx.DiGraph() if self.directed else nx.Graph()
            for nid, n in self._nodes.items():
                self._nx.add_node(nid, **n.to_dict())
            for e in self._edges:
                if e.src in self._nodes and e.dst in self._nodes:
                    self._nx.add_edge(e.src, e.dst, weight=e.weight, relation=e.relation)
        return self._nx

    def stats(self):
        g = self.G
        return {
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
            "density": round(nx.density(g), 4),
            "components": nx.number_connected_components(g)
            if not self.directed
            else nx.number_weakly_connected_components(g),
            "avg_degree": round(sum(d for _, d in g.degree()) / max(g.number_of_nodes(), 1), 2),
            "directed": self.directed,
        }

    def personalized_pagerank(self, personalization: Dict[str, float], alpha: float = 0.85) -> List[Tuple[str, float]]:
        """Calcule le PageRank personnalisé (PPR) pour mettre en avant un sous-graphe."""
        g = self.G
        try:
            scores = nx.pagerank(g, alpha=alpha, personalization=personalization, weight="weight")
            return [(nid, round(s, 4)) for nid, s in sorted(scores.items(), key=lambda x: -x[1])]
        except Exception as e:
            warnings.warn(f"PPR failed: {e}")
            return []

    def top_central_nodes(self, n=10, metric="betweenness"):
        """metric: betweenness | pagerank | degree | eigenvector | closeness"""
        g = self.G
        if metric == "betweenness":
            scores = nx.betweenness_centrality(g, weight="weight")
        elif metric == "pagerank":
            scores = nx.pagerank(g, weight="weight")
        elif metric == "degree":
            scores = nx.degree_centrality(g)
        elif metric == "closeness":
            scores = nx.closeness_centrality(g)
        elif metric == "eigenvector":
            try:
                scores = nx.eigenvector_centrality(g, weight="weight", max_iter=500)
            except:
                scores = nx.degree_centrality(g)
        else:
            raise ValueError(f"metric inconnue: {metric}")
        return [(nid, round(s, 4)) for nid, s in sorted(scores.items(), key=lambda x: -x[1])[:n]]

    def communities(self, algorithm="label_propagation"):
        """algorithm: louvain | label_propagation | greedy_modularity"""
        g = self.G
        if not self.directed and not nx.is_connected(g):
            g = g.subgraph(max(nx.connected_components(g), key=len)).copy()
        if algorithm == "louvain":
            try:
                from community import best_partition

                p = best_partition(g)
                r = defaultdict(list)
                for node, cid in p.items():
                    r[cid].append(node)
                return dict(r)
            except ImportError:
                algorithm = "label_propagation"
        if algorithm == "label_propagation":
            comms = nx.community.label_propagation_communities(g)
        elif algorithm == "greedy_modularity":
            comms = nx.community.greedy_modularity_communities(g)
        else:
            raise ValueError(f"algorithm inconnu: {algorithm}")
        return {i: list(c) for i, c in enumerate(comms)}

    def shortest_path(self, src, dst):
        try:
            return nx.shortest_path(self.G, src, dst, weight="weight")
        except nx.NetworkXNoPath:
            return []

    def neighborhood(self, node_id, depth=1):
        key = (node_id, depth)
        if key not in self._neigh_cache:
            ego = nx.ego_graph(self.G, node_id, radius=depth)
            self._neigh_cache[key] = UniversalGraph.from_networkx(ego, name=f"ego_{node_id}_d{depth}")
        return self._neigh_cache[key]

    def semantic_search(self, query, top_k=5):
        """Recherche sémantique — text ou embedding."""
        # Essayer sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer("all-MiniLM-L6-v2")
            q_vec = model.encode(query, normalize_embeddings=True)
            results = []
            for nid, n in self._nodes.items():
                if n.embedding is not None:
                    emb = n.embedding / (np.linalg.norm(n.embedding) + 1e-8)
                    results.append((nid, float(np.dot(q_vec, emb))))
            return sorted(results, key=lambda x: -x[1])[:top_k]
        except ImportError:
            pass
        # Fallback textuel
        ql = query.lower()
        results = [(nid, sum(w in n.label.lower() for w in ql.split())) for nid, n in self._nodes.items()]
        return sorted([(nid, s) for nid, s in results if s > 0], key=lambda x: -x[1])[:top_k]

    def ask(self, question, llm_fn=None):
        """Raisonnement LLM sur le graphe (G2P)."""
        relevant = self.semantic_search(question, top_k=10)
        sub_nodes = set()
        for nid, _ in relevant:
            sub_nodes.add(nid)
            sub_nodes.update(nx.neighbors(self.G, nid))
        sub = self.G.subgraph(sub_nodes)
        prompt = (
            f"Question : {question}\n\n"
            f"Graphe pertinent :\n{UniversalGraph.from_networkx(sub).to_prompt(20, 30)}\n\n"
            f"Nœuds clés :\n"
            + "\n".join(
                f"  - {nid} (sim={sc:.3f}): {self._nodes[nid].label[:80]}"
                for nid, sc in relevant[:5]
                if nid in self._nodes
            )
        )
        return llm_fn(prompt) if llm_fn else prompt

    def to_prompt(self, max_nodes=30, max_edges=50):
        g = self.G
        lines = [f"# {self.name} | {g.number_of_nodes()} nœuds, {g.number_of_edges()} arêtes", ""]
        for i, (nid, data) in enumerate(g.nodes(data=True)):
            if i >= max_nodes:
                lines.append(f"  ...+{g.number_of_nodes() - max_nodes}")
                break
            lines.append(f"  [{data.get('domain', '?')}] {nid}: {data.get('label', '')[:60]}")
        lines.append("")
        for i, (u, v, data) in enumerate(g.edges(data=True)):
            if i >= max_edges:
                lines.append(f"  ...+{g.number_of_edges() - max_edges}")
                break
            lines.append(f"  {u} --[{data.get('relation', '→')} w={data.get('weight', 1):.2f}]--> {v}")
        return "\n".join(lines)

    def to_cytoscape(self, path=None):
        data = {
            "elements": {
                "nodes": [{"data": {"id": nid, **n.to_dict()}} for nid, n in self._nodes.items()],
                "edges": [
                    {
                        "data": {
                            "id": f"{e.src}__{e.dst}",
                            "source": e.src,
                            "target": e.dst,
                            "weight": e.weight,
                            "relation": e.relation,
                        }
                    }
                    for e in self._edges
                ],
            }
        }
        if path:
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return data

    def to_mermaid(self, max_edges=40):
        lines = ["graph LR"]
        for i, e in enumerate(self._edges):
            if i >= max_edges:
                break
            sl = self._nodes.get(e.src, GraphNode(id=e.src, label=e.src)).label[:25].replace('"', "")
            dl = self._nodes.get(e.dst, GraphNode(id=e.dst, label=e.dst)).label[:25].replace('"', "")
            si = re.sub(r"[^a-zA-Z0-9]", "_", e.src)[:15]
            di = re.sub(r"[^a-zA-Z0-9]", "_", e.dst)[:15]
            lines.append(f'    {si}["{sl}"] -->|{e.relation}| {di}["{dl}"]')
        return "\n".join(lines)

    def to_pyg(self):
        import torch
        from torch_geometric.data import Data

        ids = list(self._nodes.keys())
        idx = {nid: i for i, nid in enumerate(ids)}
        doms = sorted({n.domain for n in self._nodes.values()})
        didx = {d: i for i, d in enumerate(doms)}
        feats = []
        for nid in ids:
            n = self._nodes[nid]
            if n.embedding is not None:
                feats.append(n.embedding)
            else:
                oh = np.zeros(len(doms), dtype=np.float32)
                oh[didx.get(n.domain, 0)] = 1.0
                feats.append(oh)
        x = torch.tensor(np.stack(feats), dtype=torch.float)
        ei, ea = [], []
        for e in self._edges:
            if e.src in idx and e.dst in idx:
                ei.append([idx[e.src], idx[e.dst]])
                ea.append(e.weight)
        if ei:
            ei_t = torch.tensor(ei, dtype=torch.long).t().contiguous()
            ea_t = torch.tensor(ea, dtype=torch.float)
        else:
            ei_t = torch.zeros((2, 0), dtype=torch.long)
            ea_t = torch.zeros(0)
        return Data(x=x, edge_index=ei_t, edge_attr=ea_t, num_nodes=len(ids))

    def to_json(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    def to_dict(self):
        return {
            "name": self.name,
            "stats": self.stats(),
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
        }

    def __repr__(self):
        s = self.stats()
        return f"UniversalGraph(name={self.name!r}, nodes={s['nodes']}, edges={s['edges']}, density={s['density']})"


import re  # nécessaire pour to_mermaid


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions graph standalone (opèrent sur nx.Graph brut, pas UniversalGraph)
# ─────────────────────────────────────────────────────────────────────────────


def score_edge(G, u: str, v: str) -> float:
    """Score unifié d'une arête (u, v) dans un graphe networkx.

    score = 0.4 * cosine_sim(embedding)
          + 0.3 * jaccard(tags)
          + 0.3 * recency_decay(ts)

    Retourne 0.0 si attributs manquants ou nœuds absents.
    Nodes doivent avoir attrs: embedding list[float], tags list[str], ts float.
    """
    if u not in G or v not in G:
        return 0.0
    du, dv = G.nodes[u], G.nodes[v]

    cosine = 0.0
    eu, ev = du.get("embedding"), dv.get("embedding")
    if eu is not None and ev is not None:
        try:
            a, b = np.asarray(eu, dtype=np.float32), np.asarray(ev, dtype=np.float32)
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            if na > 0 and nb > 0:
                cosine = float(np.dot(a, b) / (na * nb))
        except Exception:
            pass

    jaccard = 0.0
    tu, tv = set(du.get("tags") or []), set(dv.get("tags") or [])
    union = tu | tv
    if union:
        jaccard = len(tu & tv) / len(union)

    recency = 0.0
    tsu, tsv = du.get("ts"), dv.get("ts")
    if tsu is not None and tsv is not None:
        import math

        recency = math.exp(-abs(float(tsu) - float(tsv)) / 86400.0)

    return round(0.4 * cosine + 0.3 * jaccard + 0.3 * recency, 6)


def score_all_edges(G) -> None:
    """Met à jour le weight de chaque arête avec score_edge(). In-place."""
    for u, v, data in G.edges(data=True):
        data["weight"] = score_edge(G, u, v) or data.get("weight", 1.0)


def compute_ppr(G, source_node: str, alpha: float = 0.85) -> dict:
    """Personalized PageRank centré sur source_node.

    Retourne {node_id: float} trié par score décroissant.
    Retourne {} si source_node absent du graphe ou networkx indisponible.
    """
    if not NX_AVAILABLE or source_node not in G:
        return {}
    try:
        scores = nx.pagerank(
            G,
            alpha=alpha,
            personalization={source_node: 1.0},
            weight="weight",
            max_iter=200,
        )
        return dict(sorted(scores.items(), key=lambda x: -x[1]))
    except Exception:
        return {}
