"""
app/forge_project_state_graph.py — Software-creator project state as directed graph.
Tracks module status (STUB/IMPL/TESTED/BLOCKED), deps, critical path, DOT export.
"""

import ast
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x


@dataclass
class ModuleNode:
    id: str
    name: str
    path: str
    status: str  # STUB | IMPL | TESTED | BLOCKED
    deps: List[str] = field(default_factory=list)
    test_coverage: bool = False
    pylint_score: float = 0.0


class ProjectStateGraph:
    def __init__(self):
        self.nodes: Dict[str, ModuleNode] = {}
        self.edges: Dict[str, List[str]] = {}

    def add_module(self, node: ModuleNode):
        self.nodes[node.id] = node
        self.edges.setdefault(node.id, [])

    def add_dependency(self, src_id: str, dst_id: str):
        if src_id in self.nodes and dst_id in self.nodes:
            if dst_id not in self.edges[src_id]:
                self.edges[src_id].append(dst_id)

    def get_blocked(self) -> List[ModuleNode]:
        blocked = []
        for node in self.nodes.values():
            for dep_id in self.edges.get(node.id, []):
                dep = self.nodes.get(dep_id)
                if dep and dep.status == "STUB":
                    blocked.append(node)
                    break
        return blocked

    def get_ready_to_test(self) -> List[ModuleNode]:
        ready = []
        for node in self.nodes.values():
            if node.status != "IMPL":
                continue
            if all(self.nodes[d].status == "TESTED" for d in self.edges.get(node.id, []) if d in self.nodes):
                ready.append(node)
        return ready

    def critical_path(self) -> List[str]:
        """Longest dependency chain using DFS memoization."""
        memo: Dict[str, List[str]] = {}

        def _dfs(nid: str, visiting: set) -> List[str]:
            if nid in memo:
                return memo[nid]
            if nid in visiting:
                return [nid]
            visiting = visiting | {nid}
            best: List[str] = []
            for dep in self.edges.get(nid, []):
                path = _dfs(dep, visiting)
                if len(path) > len(best):
                    best = path
            result = [nid] + best
            memo[nid] = result
            return result

        longest: List[str] = []
        for nid in self.nodes:
            p = _dfs(nid, set())
            if len(p) > len(longest):
                longest = p
        return longest

    def to_dot(self) -> str:
        colors = {"STUB": "salmon", "IMPL": "gold", "TESTED": "lightgreen", "BLOCKED": "lightgray"}
        lines = ["digraph ProjectState {", "  rankdir=LR;"]
        for nid, node in self.nodes.items():
            color = colors.get(node.status, "white")
            lines.append(f'  "{nid}" [label="{node.name}\\n{node.status}" style=filled fillcolor={color}];')
        for src, dsts in self.edges.items():
            for dst in dsts:
                lines.append(f'  "{src}" -> "{dst}";')
        lines.append("}")
        return "\n".join(lines)

    def save(self, path: str):
        data = {
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": self.edges,
        }
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str) -> "ProjectStateGraph":
        data = json.loads(Path(path).read_text())
        g = cls()
        for nd in data["nodes"]:
            g.add_module(ModuleNode(**nd))
        g.edges = data["edges"]
        return g


def scan_project(root_dir: str) -> ProjectStateGraph:
    graph = ProjectStateGraph()
    root = Path(root_dir)
    forge_files = list(root.rglob("forge_*.py"))

    for fp in tqdm(forge_files, desc="scanning modules", unit="file"):
        try:
            src = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        module_id = fp.stem
        line_count = len(src.splitlines())
        status = "IMPL" if line_count >= 50 else "STUB"

        test_file = fp.parent / f"test_{fp.name}"
        if test_file.exists():
            status = "TESTED"

        deps: List[str] = []
        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top.startswith("forge_"):
                            deps.append(top)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    if top.startswith("forge_"):
                        deps.append(top)
        except SyntaxError:
            pass

        graph.add_module(
            ModuleNode(
                id=module_id,
                name=fp.name,
                path=str(fp),
                status=status,
                deps=list(set(deps)),
                test_coverage=test_file.exists(),
            )
        )

    # Wire deps
    for node in graph.nodes.values():
        for dep_id in node.deps:
            graph.add_dependency(node.id, dep_id)

    # Mark BLOCKED
    blocked = {n.id for n in graph.get_blocked()}
    for nid in blocked:
        if graph.nodes[nid].status != "TESTED":
            graph.nodes[nid].status = "BLOCKED"

    return graph


if __name__ == "__main__":
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent)
    print(f"Scanning: {root}")
    g = scan_project(root)

    total = len(g.nodes)
    by_status: Dict[str, int] = {}
    for n in g.nodes.values():
        by_status[n.status] = by_status.get(n.status, 0) + 1

    print(f"\nModules: {total}")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")

    cp = g.critical_path()
    print(f"\nCritical path ({len(cp)} nodes): {' → '.join(cp[:8])}{'...' if len(cp) > 8 else ''}")

    blocked = g.get_blocked()
    print(f"Blocked: {[n.id for n in blocked[:5]]}")

    ready = g.get_ready_to_test()
    print(f"Ready to test: {[n.id for n in ready[:5]]}")

    out = Path(root) / "sandbox" / "project_state.json"
    g.save(str(out))
    print(f"\nSaved: {out}")
