#!/usr/bin/env python3
"""
forge_nlgraph_runner.py — NLGraph Benchmark Runner for Nokido
===============================================================
Tests LLM graph reasoning across 8 tasks of increasing complexity.

Usage:
    python app/forge_nlgraph_runner.py --run --model qwen2.5-coder:7b
    python app/forge_nlgraph_runner.py --run --model qwen3:8b --tasks connectivity,cycle
    python app/forge_nlgraph_runner.py --compare
"""

from __future__ import annotations

import json, hashlib, itertools, random, re, time, urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

OLLAMA_URL = "http://localhost:11434"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "nlgraph"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TASKS = [
    "connectivity",
    "cycle",
    "shortest_path",
    "bipartite",
    "topological_sort",
    "max_flow",
    "gnn_simulate",
    "hamilton",
]

DIFFICULTY = {
    "easy": {"n": 6, "p": 0.3, "instances": 10},
    "medium": {"n": 12, "p": 0.25, "instances": 8},
    "hard": {"n": 20, "p": 0.2, "instances": 5},
}


@dataclass
class TestCase:
    task: str
    difficulty: str
    graph_id: str
    graph_text: str
    question: str
    ground_truth: str
    metadata: dict = field(default_factory=dict)


class GraphGenerator:
    def __init__(self, seed=42):
        self.rng = random.Random(seed)
        self.seed = seed

    def _gid(self, t, d, i):
        return f"{t}_{d}_{i}_{hashlib.md5(f'{t}{d}{i}{self.seed}'.encode()).hexdigest()[:6]}"

    def _ser(self, G, directed=False, node_values=None):
        d = "directed" if directed else "undirected"
        lines = [f"In an {d} graph,"]
        lines.append(f"the nodes are {', '.join(str(n) for n in sorted(G.nodes()))},")
        lines.append("and the edges are:")
        for u, v, data in G.edges(data=True):
            w = data.get("capacity", "")
            lines.append(f"  ({u}, {v})" + (f" (capacity {w})" if w else ""))
        if node_values:
            lines.append("\nNode values: " + ", ".join(f"{k}={v}" for k, v in sorted(node_values.items())))
        return "\n".join(lines)

    def gen_connectivity(self, n, p):
        G = nx.erdos_renyi_graph(n, p, seed=self.rng.randint(0, 9999))
        a, b = self.rng.sample(sorted(G.nodes()), 2)
        conn = nx.has_path(G, a, b) if G.number_of_edges() > 0 else False
        return G, f"Is there a path between node {a} and node {b}? Answer YES or NO.", "YES" if conn else "NO"

    def gen_cycle(self, n, p):
        if self.rng.random() < 0.33:
            G = nx.random_labeled_tree(n, seed=self.rng.randint(0, 9999))
        else:
            G = nx.erdos_renyi_graph(n, p, seed=self.rng.randint(0, 9999))
        has = len(nx.cycle_basis(G)) > 0
        return G, "Does this graph contain a cycle? Answer YES or NO.", "YES" if has else "NO"

    def gen_shortest_path(self, n, p):
        G = nx.erdos_renyi_graph(n, max(p, 0.35), seed=self.rng.randint(0, 9999))
        nodes = sorted(G.nodes())
        for _ in range(30):
            a, b = self.rng.sample(nodes, 2)
            if nx.has_path(G, a, b):
                break
        else:
            a, b = nodes[0], nodes[1]
        path = nx.shortest_path(G, a, b) if nx.has_path(G, a, b) else [a]
        return G, f"What is the shortest path from {a} to {b}? Give as A -> B -> C.", " -> ".join(str(x) for x in path)

    def gen_bipartite(self, n, p):
        # Force ~50% non-bipartite by alternating
        force_non_bipartite = self.rng.random() < 0.5
        if force_non_bipartite:
            # Create non-bipartite: odd cycle guaranteed
            G = nx.cycle_graph(3)  # triangle = odd cycle
            # Add extra nodes connected randomly
            for node in range(3, n):
                G.add_node(node)
                targets = self.rng.sample(range(node), min(2, node))
                for t in targets:
                    G.add_edge(node, t)
        elif self.rng.random() < 0.5:
            G = nx.complete_bipartite_graph(n // 2, n - n // 2)
        else:
            # Generate until bipartite (use higher seed range)
            for attempt in range(50):
                G = nx.erdos_renyi_graph(n, p, seed=self.rng.randint(0, 99999))
                if nx.is_bipartite(G):
                    break
        return G, "Is this graph bipartite? Answer YES or NO.", "YES" if nx.is_bipartite(G) else "NO"

    def gen_topological_sort(self, n, p):
        G = nx.gnp_random_graph(n, p, directed=True, seed=self.rng.randint(0, 9999))
        dag = nx.DiGraph()
        order = list(range(n))
        self.rng.shuffle(order)
        rank = {v: i for i, v in enumerate(order)}
        for u, v in G.edges():
            if rank[u] < rank[v]:
                dag.add_edge(u, v)
        dag.add_nodes_from(range(n))
        topo = list(nx.topological_sort(dag))
        return dag, "Give a valid topological ordering. Format: A -> B -> C.", " -> ".join(str(x) for x in topo)

    def gen_max_flow(self, n, p):
        G = nx.gnp_random_graph(n, max(p, 0.3), directed=True, seed=self.rng.randint(0, 9999))
        dag = nx.DiGraph()
        order = list(range(n))
        self.rng.shuffle(order)
        rank = {v: i for i, v in enumerate(order)}
        for u, v in G.edges():
            if rank[u] < rank[v]:
                dag.add_edge(u, v, capacity=self.rng.randint(1, 10))
        dag.add_nodes_from(range(n))
        src, snk = order[0], order[-1]
        try:
            fv = int(nx.maximum_flow_value(dag, src, snk))
        except:
            fv = 0
        return dag, f"What is the maximum flow from node {src} to node {snk}?", str(fv)

    def gen_gnn_simulate(self, n, p):
        G = nx.erdos_renyi_graph(min(n, 8), max(p, 0.3), seed=self.rng.randint(0, 9999))
        nv = {nd: self.rng.randint(1, 9) for nd in G.nodes()}
        new = {v: nv[v] + sum(nv[u] for u in G.neighbors(v)) for v in G.nodes()}
        t = self.rng.choice(sorted(G.nodes()))
        q = f"After one round of sum-aggregation message passing, what is the new value of node {t}?"
        return G, q, str(new[t]), nv

    def gen_hamilton(self, n, p):
        n = min(n, 8)
        if self.rng.random() < 0.4:
            G = nx.path_graph(n)
            has_ham = True
        else:
            G = nx.erdos_renyi_graph(n, max(p, 0.3), seed=self.rng.randint(0, 9999))
            nodes = list(G.nodes())
            has_ham = any(
                all(G.has_edge(perm[i], perm[i + 1]) for i in range(len(perm) - 1))
                for perm in itertools.permutations(nodes)
            )
        return (
            G,
            "Does this graph have a Hamiltonian path (visits every node exactly once)? Answer YES or NO.",
            "YES" if has_ham else "NO",
        )

    def generate_all(self, difficulty="easy"):
        cfg = DIFFICULTY[difficulty]
        cases = []
        for task in TASKS:
            gen_fn = getattr(self, f"gen_{task}")
            for i in range(cfg["instances"]):
                self.rng = random.Random(42 + hash(f"{task}_{difficulty}_{i}"))
                gid = self._gid(task, difficulty, i)
                try:
                    result = gen_fn(cfg["n"], cfg["p"])
                    if task == "gnn_simulate":
                        G, question, truth, nv = result
                        gt = self._ser(G, node_values=nv)
                    else:
                        G, question, truth = result
                        gt = self._ser(G, directed=(task in ("topological_sort", "max_flow")))
                    cases.append(
                        TestCase(
                            task=task,
                            difficulty=difficulty,
                            graph_id=gid,
                            graph_text=gt,
                            question=question,
                            ground_truth=truth,
                            metadata={"n": G.number_of_nodes(), "m": G.number_of_edges()},
                        )
                    )
                except Exception as e:
                    print(f"  [SKIP] {task}/{difficulty}/{i}: {e}")
        return cases
