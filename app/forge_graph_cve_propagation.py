"""app/forge_graph_cve_propagation.py — Propagation BFS d'une CVE dans le graphe de code."""

from __future__ import annotations

from collections import deque


def propagate_cve(
    cve_id: str,
    entry_module: str,
    graph: dict[str, list[str]],
    max_depth: int = 3,
) -> dict:
    """BFS depuis entry_module, max_depth niveaux de profondeur.

    Returns: {cve_id, entry, affected, depth_map, risk_score}
    """
    if entry_module not in graph:
        return {
            "cve_id": cve_id,
            "entry": entry_module,
            "affected": [],
            "depth_map": {},
            "risk_score": 0.0,
        }

    visited: set[str] = {entry_module}
    queue: deque = deque([(entry_module, 0)])
    depth_map: dict[str, int] = {entry_module: 0}
    affected: list[str] = []

    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                d = depth + 1
                depth_map[neighbor] = d
                affected.append(neighbor)
                queue.append((neighbor, d))

    # risk_score = 1 / (1 + avg_depth_of_affected)
    if affected:
        avg_depth = sum(depth_map[m] for m in affected) / len(affected)
        risk_score = round(1.0 / (1.0 + avg_depth), 4)
    else:
        risk_score = 0.0

    return {
        "cve_id": cve_id,
        "entry": entry_module,
        "affected": affected,
        "depth_map": depth_map,
        "risk_score": risk_score,
    }


if __name__ == "__main__":
    import json

    g = {
        "forge_rag_engine.py": ["forge_rag_store.py", "forge_rag_qualify.py"],
        "forge_rag_store.py": ["forge_db.py"],
        "forge_rag_qualify.py": ["forge_db.py"],
        "forge_db.py": [],
    }
    result = propagate_cve("CVE-2024-3094", "forge_rag_engine.py", g, max_depth=3)
    print(json.dumps(result, indent=2))
