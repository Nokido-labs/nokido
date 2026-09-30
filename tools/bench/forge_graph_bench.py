#!/usr/bin/env python3
"""
forge_graph_bench.py — Benchmark de raisonnement sur graphes pour Nokido
==========================================================================
Implémente les 3 benchmarks Gemini faisables:

1. FCG (Function Call Graph) : Analyse de dépendances Python via AST
   → Objectif: identifier les nœuds critiques (fonctions vulnérables)

2. G2P (Graph-to-Prompt) : Convertir un graphe en prompt LLM
   → Objectif: le LLM raisonne sur la topologie sans GNN

3. Attack Path : Trouver le chemin d'attaque dans un graphe de permissions
   → Objectif: shortest path vers un nœud privilégié

Usage:
    python3 forge_graph_bench.py --bench fcg --target /path/to/project
    python3 forge_graph_bench.py --bench g2p --test
    python3 forge_graph_bench.py --bench attack_path --test
"""

import ast
import json
import time
from pathlib import Path

try:
    import networkx as nx
except ImportError:
    nx = None


# ── 1. FUNCTION CALL GRAPH (FCG) ──────────────────────────────


class FCGAnalyzer:
    """Construit et analyse le graphe d'appels de fonctions d'un projet Python."""

    DANGEROUS_CALLS = {
        "eval",
        "exec",
        "pickle.loads",
        "yaml.load",
        "subprocess.call",
        "subprocess.Popen",
        "os.system",
        "__import__",
        "compile",
        "input",
    }
    DANGEROUS_IMPORTS = {"pickle", "marshal", "shelve", "os", "subprocess", "ctypes", "socket"}

    def __init__(self):
        self.graph = nx.DiGraph() if nx else {}
        self.dangerous_nodes: set[str] = set()
        self.files_parsed = 0

    def analyze_file(self, filepath: str) -> dict:
        """Parse un fichier Python et extrait le graphe d'appels."""
        try:
            source = Path(filepath).read_text(errors="replace")
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            return {"error": f"SyntaxError in {filepath}"}

        module = Path(filepath).stem
        self.files_parsed += 1

        # Extraire les fonctions définies
        functions = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fname = f"{module}.{node.name}"
                functions[fname] = node
                self.graph.add_node(fname, file=filepath, line=node.lineno, type="function")

        # Extraire les appels
        for fname, fnode in functions.items():
            for node in ast.walk(fnode):
                if isinstance(node, ast.Call):
                    callee = self._resolve_call(node)
                    if callee:
                        full_callee = f"{module}.{callee}" if "." not in callee else callee
                        self.graph.add_edge(fname, full_callee)

                        # Marquer les appels dangereux
                        if callee in self.DANGEROUS_CALLS:
                            self.dangerous_nodes.add(fname)
                            self.graph.nodes[fname]["dangerous"] = True

        # Extraire les imports dangereux
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in self.DANGEROUS_IMPORTS:
                        self.dangerous_nodes.add(f"{module}.<import:{alias.name}>")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in self.DANGEROUS_IMPORTS:
                    self.dangerous_nodes.add(f"{module}.<import:{node.module}>")

        return {"functions": len(functions), "dangerous": len(self.dangerous_nodes)}

    def analyze_project(self, project_dir: str, max_files: int = 50) -> dict:
        """Analyse un projet complet."""
        t0 = time.time()
        results = {"files": 0, "functions": 0, "edges": 0, "dangerous": 0}

        for py_file in sorted(Path(project_dir).rglob("*.py"))[:max_files]:
            if any(
                skip in str(py_file) for skip in ["__pycache__", ".git", "node_modules", "venv"]
            ):
                continue
            r = self.analyze_file(str(py_file))
            results["files"] += 1

        results["functions"] = self.graph.number_of_nodes()
        results["edges"] = self.graph.number_of_edges()
        results["dangerous"] = len(self.dangerous_nodes)
        results["time_s"] = round(time.time() - t0, 2)
        return results

    def find_impact_radius(self, node: str, max_depth: int = 5) -> dict:
        """Trouve tous les nœuds impactés par un nœud vulnérable."""
        if not nx:
            return {"error": "networkx required"}

        # Nœuds qui APPELLENT le nœud vulnérable (callers)
        callers = set()
        try:
            callers = nx.ancestors(self.graph, node)
        except nx.NetworkXError:
            pass

        # Nœuds APPELÉS par le nœud vulnérable (callees)
        callees = set()
        try:
            callees = nx.descendants(self.graph, node)
        except nx.NetworkXError:
            pass

        return {
            "node": node,
            "callers": len(callers),
            "callees": len(callees),
            "total_impact": len(callers | callees),
            "caller_list": sorted(callers)[:10],
            "callee_list": sorted(callees)[:10],
        }

    def _resolve_call(self, node: ast.Call) -> str | None:
        """Résout le nom d'une fonction appelée."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
            return node.func.attr
        return None

    def get_critical_nodes(self, top_n: int = 10) -> list[dict]:
        """Retourne les nœuds les plus critiques (centralité + dangerosité)."""
        if not nx or self.graph.number_of_nodes() == 0:
            return []

        # Centralité de betweenness (nœuds "ponts")
        try:
            centrality = nx.betweenness_centrality(self.graph)
        except:
            centrality = {}

        nodes = []
        for n in self.graph.nodes:
            score = centrality.get(n, 0)
            if n in self.dangerous_nodes:
                score += 1.0  # boost dangereux
            nodes.append(
                {
                    "node": n,
                    "centrality": round(score, 4),
                    "dangerous": n in self.dangerous_nodes,
                    "in_degree": self.graph.in_degree(n),
                    "out_degree": self.graph.out_degree(n),
                }
            )

        return sorted(nodes, key=lambda x: x["centrality"], reverse=True)[:top_n]


# ── 2. GRAPH-TO-PROMPT (G2P) ──────────────────────────────────


class GraphToPrompt:
    """Convertit un graphe networkx en prompt textuel pour un LLM."""

    @staticmethod
    def serialize_graph(G, max_nodes: int = 50) -> str:
        """Sérialise un graphe en format textuel compact pour prompt LLM."""
        lines = []
        nodes = list(G.nodes(data=True))[:max_nodes]
        edges = list(G.edges)[: max_nodes * 2]

        lines.append(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        lines.append("")
        lines.append("Nodes:")
        for n, attrs in nodes:
            attr_str = ", ".join(f"{k}={v}" for k, v in attrs.items() if k != "embedding")
            lines.append(f"  [{n}] {attr_str}")

        lines.append("")
        lines.append("Edges:")
        for u, v in edges:
            lines.append(f"  {u} -> {v}")

        return "\n".join(lines)

    @staticmethod
    def query_template(graph_text: str, question: str) -> str:
        """Génère un prompt complet pour questionner un LLM sur un graphe."""
        return f"""Analyze the following graph structure and answer the question.

{graph_text}

Question: {question}

Provide a precise, technical answer based only on the graph data above."""


# ── 3. ATTACK PATH FINDER ─────────────────────────────────────


class AttackPathFinder:
    """Trouve les chemins d'attaque dans un graphe de permissions."""

    @staticmethod
    def build_sample_ad_graph() -> "nx.DiGraph":
        """Construit un graphe AD simulé pour benchmark."""
        G = nx.DiGraph()

        # Utilisateurs
        for u in ["alice", "bob", "charlie", "dave", "eve", "mallory"]:
            G.add_node(u, type="user", compromised=False)

        # Groupes
        for g in ["IT-Staff", "HR", "Dev-Team", "Domain-Admins", "Backup-Operators"]:
            G.add_node(g, type="group")

        # Machines
        for m in ["WS-01", "WS-02", "SRV-DC01", "SRV-FILE", "SRV-WEB"]:
            G.add_node(m, type="computer")

        # Memberships
        G.add_edge("alice", "IT-Staff", relation="MemberOf")
        G.add_edge("bob", "HR", relation="MemberOf")
        G.add_edge("charlie", "Dev-Team", relation="MemberOf")
        G.add_edge("dave", "IT-Staff", relation="MemberOf")
        G.add_edge("eve", "Backup-Operators", relation="MemberOf")
        G.add_edge("mallory", "Dev-Team", relation="MemberOf")

        # Admin local
        G.add_edge("IT-Staff", "WS-01", relation="AdminTo")
        G.add_edge("IT-Staff", "WS-02", relation="AdminTo")
        G.add_edge("Dev-Team", "SRV-WEB", relation="AdminTo")
        G.add_edge("Backup-Operators", "SRV-FILE", relation="AdminTo")

        # Sessions (qui est connecté où)
        G.add_edge("WS-01", "dave", relation="HasSession")
        G.add_edge("SRV-DC01", "Domain-Admins", relation="HasSession")
        G.add_edge("SRV-FILE", "Domain-Admins", relation="HasSession")

        # ACE dangereuses
        G.add_edge("Backup-Operators", "SRV-DC01", relation="CanRDP")
        G.add_edge("IT-Staff", "Backup-Operators", relation="GenericAll")
        G.add_edge("charlie", "SRV-FILE", relation="WriteDacl")

        return G

    @staticmethod
    def find_attack_paths(G, start: str, target: str, max_depth: int = 6) -> list[list[str]]:
        """Trouve tous les chemins d'attaque du start vers le target."""
        if not nx:
            return []
        try:
            paths = list(nx.all_simple_paths(G, start, target, cutoff=max_depth))
            return sorted(paths, key=len)[:5]
        except (nx.NetworkXError, nx.NodeNotFound):
            return []

    @staticmethod
    def find_shortest_to_da(G) -> dict:
        """Trouve le chemin le plus court vers Domain-Admins depuis chaque utilisateur."""
        results = {}
        users = [n for n, d in G.nodes(data=True) if d.get("type") == "user"]

        for user in users:
            paths = []
            # Vers Domain-Admins directement
            try:
                path = nx.shortest_path(G, user, "Domain-Admins")
                paths.append(path)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

            # Vers SRV-DC01 (qui a une session DA)
            try:
                path = nx.shortest_path(G, user, "SRV-DC01")
                paths.append(path)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

            if paths:
                shortest = min(paths, key=len)
                results[user] = {
                    "path": shortest,
                    "hops": len(shortest) - 1,
                    "via": shortest[1] if len(shortest) > 1 else None,
                }
            else:
                results[user] = {"path": [], "hops": -1, "via": None}

        return results


# ── BENCHMARK RUNNER ───────────────────────────────────────────


def run_fcg_benchmark(target_dir: str = None) -> dict:
    """Benchmark FCG sur un projet Python."""
    if not target_dir:
        # Auto-test sur Nokido lui-même
        target_dir = str(Path(__file__).parent)

    analyzer = FCGAnalyzer()
    results = analyzer.analyze_project(target_dir)
    critical = analyzer.get_critical_nodes(5)

    # Impact des nœuds dangereux
    impacts = []
    for node in list(analyzer.dangerous_nodes)[:3]:
        imp = analyzer.find_impact_radius(node)
        impacts.append(imp)

    return {
        "benchmark": "FCG",
        "target": target_dir,
        "results": results,
        "critical_nodes": critical,
        "dangerous_impacts": impacts,
        "score": min(100, results["functions"] * 2) if results["functions"] else 0,
    }


def run_attack_path_benchmark() -> dict:
    """Benchmark Attack Path sur graphe AD simulé."""
    finder = AttackPathFinder()
    G = finder.build_sample_ad_graph()

    t0 = time.time()
    paths = finder.find_shortest_to_da(G)
    dt = time.time() - t0

    # Score: combien d'utilisateurs ont un chemin vers DA ?
    reachable = sum(1 for v in paths.values() if v["hops"] > 0)
    shortest = min((v["hops"] for v in paths.values() if v["hops"] > 0), default=0)

    return {
        "benchmark": "AttackPath",
        "graph_size": f"{G.number_of_nodes()} nodes, {G.number_of_edges()} edges",
        "users_with_path": reachable,
        "total_users": len([n for n, d in G.nodes(data=True) if d.get("type") == "user"]),
        "shortest_path_hops": shortest,
        "paths": {k: v for k, v in paths.items() if v["hops"] > 0},
        "time_s": round(dt, 4),
        "score": 100 if shortest <= 3 else 50 if shortest <= 5 else 0,
    }


def run_g2p_benchmark() -> dict:
    """Benchmark G2P: sérialiser un graphe et vérifier la qualité du prompt."""
    finder = AttackPathFinder()
    G = finder.build_sample_ad_graph()

    g2p = GraphToPrompt()
    prompt_text = g2p.serialize_graph(G)

    question = "Which user has the shortest attack path to Domain-Admins? Describe the path."
    full_prompt = g2p.query_template(prompt_text, question)

    return {
        "benchmark": "G2P",
        "graph_nodes": G.number_of_nodes(),
        "prompt_length": len(full_prompt),
        "prompt_tokens_approx": len(full_prompt) // 4,
        "prompt_preview": full_prompt[:300] + "...",
        "score": 100 if len(full_prompt) < 2000 else 70,  # compact = better
    }


def run_all_benchmarks(target_dir: str = None) -> dict:
    """Lance tous les benchmarks."""
    results = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "benchmarks": {}}

    print("Running FCG benchmark...")
    results["benchmarks"]["fcg"] = run_fcg_benchmark(target_dir)

    print("Running Attack Path benchmark...")
    results["benchmarks"]["attack_path"] = run_attack_path_benchmark()

    print("Running G2P benchmark...")
    results["benchmarks"]["g2p"] = run_g2p_benchmark()

    # Score global
    scores = [b["score"] for b in results["benchmarks"].values()]
    results["global_score"] = round(sum(scores) / len(scores))

    return results


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--bench", choices=["fcg", "g2p", "attack_path", "all"], default="all")
    p.add_argument("--target", default=None)
    args = p.parse_args()

    if args.bench == "all":
        r = run_all_benchmarks(args.target)
    elif args.bench == "fcg":
        r = run_fcg_benchmark(args.target)
    elif args.bench == "attack_path":
        r = run_attack_path_benchmark()
    elif args.bench == "g2p":
        r = run_g2p_benchmark()

    print(json.dumps(r, indent=2, default=str))
