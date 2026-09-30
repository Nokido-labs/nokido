"""forge_dep_manager.py — Dependency graph analyser for Nokido forge_*.py modules."""

import ast
import collections
from pathlib import Path


def build_dep_graph(app_dir: Path) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = collections.defaultdict(list)
    forge_modules = {f.stem: f for f in app_dir.glob("forge_*.py")}
    for module, filepath in forge_modules.items():
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("forge_"):
                        dep = alias.name.split(".")[0]
                        if dep != module:
                            graph[module].append(dep)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("forge_"):
                    dep = node.module.split(".")[0]
                    if dep != module:
                        graph[module].append(dep)
    return dict(graph)


def detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visited: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor in path:
                cycles.append(path[path.index(neighbor) :] + [neighbor])
            elif neighbor not in visited:
                dfs(neighbor, path)
        path.pop()

    for node in graph:
        if node not in visited:
            dfs(node, [])
    return cycles


def detect_missing(graph: dict[str, list[str]], app_dir: Path) -> list[tuple[str, str]]:
    existing = {f.stem for f in app_dir.glob("forge_*.py")}
    return [(mod, dep) for mod, deps in graph.items() for dep in deps if dep not in existing]


def export_dot(graph: dict[str, list[str]], output: Path) -> None:
    with open(output, "w", encoding="utf-8") as f:
        f.write('digraph nokido_deps {\n  node [shape="box"];\n')
        for module, deps in graph.items():
            for dep in deps:
                f.write(f'  "{module}" -> "{dep}";\n')
        f.write("}\n")


if __name__ == "__main__":
    app_dir = Path("app")
    graph = build_dep_graph(app_dir)
    cycles = detect_cycles(graph)
    missing = detect_missing(graph, app_dir)
    print(f"Modules: {len(graph)}  Deps: {sum(len(v) for v in graph.values())}")
    print(f"Cycles: {len(cycles)}  Missing: {len(missing)}")
    for c in cycles:
        print(f"  CYCLE: {' -> '.join(c)}")
    for mod, dep in missing[:10]:
        print(f"  MISSING: {mod} imports {dep}")
