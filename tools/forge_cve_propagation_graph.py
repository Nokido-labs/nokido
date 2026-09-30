"""
tools/forge_cve_propagation_graph.py — CVE transitive propagation through dependency graph.
Loads from OSV.dev API, BFS propagation, risk scoring, DOT export (no graphviz dep).
"""

from collections import deque
from dataclasses import dataclass, field

try:
    import requests as _req
except ImportError:
    import sys

    sys.exit("pip install requests")

try:
    import networkx as nx
except ImportError:
    import sys

    sys.exit("pip install networkx")

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

OSV_API = "https://api.osv.dev/v1/query"


@dataclass
class CVENode:
    id: str
    severity: str
    cvss: float
    affected_packages: list[str] = field(default_factory=list)


@dataclass
class DepNode:
    name: str
    version: str
    deps: list[str] = field(default_factory=list)


class CVEPropagationGraph:
    def __init__(self):
        self.packages: dict[str, DepNode] = {}
        self.cves: dict[str, CVENode] = {}
        self.graph: nx.DiGraph = nx.DiGraph()
        self._propagated: dict[str, list[str]] = {}

    def add_package(self, node: DepNode):
        self.packages[node.name] = node
        self.graph.add_node(node.name)

    def add_cve(self, cve: CVENode):
        self.cves[cve.id] = cve

    def build_dep_graph(self):
        for pkg, node in self.packages.items():
            for dep in node.deps:
                if dep not in self.packages:
                    self.packages[dep] = DepNode(name=dep, version="?")
                    self.graph.add_node(dep)
                self.graph.add_edge(pkg, dep)

    def propagate_cves(self) -> dict[str, list[str]]:
        affected: dict[str, list[str]] = {p: [] for p in self.packages}

        # Seed direct CVEs
        for cve in self.cves.values():
            for pkg in cve.affected_packages:
                affected.setdefault(pkg, []).append(cve.id)

        # BFS transitive propagation (reverse: dependents inherit CVEs of deps)
        rev = self.graph.reverse()
        for pkg in tqdm(list(self.packages), desc="propagating CVEs", unit="pkg"):
            if not affected.get(pkg):
                continue
            queue = deque([pkg])
            visited = {pkg}
            while queue:
                cur = queue.popleft()
                for parent in rev.successors(cur):
                    if parent not in visited:
                        affected.setdefault(parent, [])
                        for cve_id in affected[cur]:
                            if cve_id not in affected[parent]:
                                affected[parent].append(cve_id)
                        visited.add(parent)
                        queue.append(parent)

        self._propagated = affected
        return affected

    def risk_score(self, pkg: str) -> float:
        propagated = self._propagated or self.propagate_cves()
        return sum(self.cves[c].cvss for c in propagated.get(pkg, []) if c in self.cves)

    def top_at_risk(self, k: int = 10) -> list[tuple[str, float]]:
        scores = [(p, self.risk_score(p)) for p in self.packages]
        return sorted(scores, key=lambda x: x[1], reverse=True)[:k]

    def to_dot(self) -> str:
        lines = ["digraph CVEPropagation {", "  rankdir=LR;"]
        for pkg in self.packages:
            risk = self.risk_score(pkg)
            color = "salmon" if risk > 7 else ("gold" if risk > 3 else "lightgreen")
            cve_count = len(self._propagated.get(pkg, []))
            lines.append(
                f'  "{pkg}" [style=filled fillcolor={color} label="{pkg}\\nrisk={risk:.1f} cves={cve_count}"];'
            )
        for src, dst in self.graph.edges():
            lines.append(f'  "{src}" -> "{dst}";')
        lines.append("}")
        return "\n".join(lines)


def load_from_osv(ecosystem: str = "PyPI") -> "CVEPropagationGraph":
    g = CVEPropagationGraph()
    try:
        r = _req.post(OSV_API, json={"query": {"package": {"ecosystem": ecosystem}}}, timeout=15)
        r.raise_for_status()
        vulns = r.json().get("vulns", [])[:20]
    except Exception as e:
        print(f"[WARN] OSV API: {e} — using empty graph")
        return g

    for v in vulns:
        pkgs = []
        for aff in v.get("affected", []):
            name = aff.get("package", {}).get("name", "")
            if name:
                pkgs.append(name)
                g.add_package(DepNode(name=name, version="?"))
        severity = v.get("database_specific", {}).get("severity", "UNKNOWN")
        cvss = float(
            v.get("database_specific", {}).get("cvss_v3", {}).get("baseScore", 5.0)
            if isinstance(v.get("database_specific", {}).get("cvss_v3"), dict)
            else 5.0
        )
        g.add_cve(
            CVENode(id=v.get("id", "?"), severity=severity, cvss=cvss, affected_packages=pkgs)
        )

    g.build_dep_graph()
    return g


if __name__ == "__main__":
    print("Loading CVEs from OSV.dev (PyPI)...")
    g = load_from_osv()
    print(f"Packages: {len(g.packages)}  CVEs: {len(g.cves)}")
    g.propagate_cves()
    print("\nTop 10 at-risk packages:")
    for pkg, risk in g.top_at_risk(10):
        print(f"  {pkg:<35} risk={risk:.1f}")
    dot = g.to_dot()
    from pathlib import Path

    out = Path(__file__).parent.parent / "sandbox" / "cve_propagation.dot"
    out.parent.mkdir(exist_ok=True)
    out.write_text(dot)
    print(f"\nDOT saved: {out}")
