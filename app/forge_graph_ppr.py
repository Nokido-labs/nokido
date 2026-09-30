"""app/forge_graph_ppr.py — Personalized PageRank sur graphe de code."""

from __future__ import annotations


def ppr(
    graph: dict[str, list[str]],
    seed: str,
    alpha: float = 0.85,
    max_iter: int = 50,
) -> dict[str, float]:
    """Power-iteration PPR. Téléportation vers seed uniquement (pas uniforme).

    graph: {node: [out_neighbors]}
    seed:  noeud de départ (reçoit toute la masse de téléportation)
    """
    nodes = list(graph)
    if seed not in graph:
        return {}

    scores: dict[str, float] = {n: 0.0 for n in nodes}
    scores[seed] = 1.0

    for _ in range(max_iter):
        new_scores: dict[str, float] = {n: 0.0 for n in nodes}

        # Teleportation: 100% vers seed
        new_scores[seed] += 1.0 - alpha

        # Propagation depuis chaque noeud vers ses voisins
        for node in nodes:
            neighbors = graph[node]
            if not neighbors:
                # Dangling node: reverse vers seed
                new_scores[seed] += alpha * scores[node]
            else:
                share = alpha * scores[node] / len(neighbors)
                for nb in neighbors:
                    if nb in new_scores:
                        new_scores[nb] += share

        # Convergence
        delta = sum(abs(new_scores[n] - scores[n]) for n in nodes)
        scores = new_scores
        if delta < 1e-6:
            break

    # Normalise
    total = sum(scores.values()) or 1.0
    return {n: s / total for n, s in scores.items()}


def top_k(scores: dict[str, float], k: int = 10) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]


if __name__ == "__main__":
    g = {
        "forge_goap.py": ["forge_trajectory.py", "forge_llm_router.py"],
        "forge_trajectory.py": ["forge_rag_engine.py"],
        "forge_llm_router.py": ["forge_rag_engine.py", "forge_ollama.py"],
        "forge_rag_engine.py": [],
        "forge_ollama.py": [],
    }
    scores = ppr(g, seed="forge_goap.py")
    for node, score in top_k(scores, k=5):
        print(f"  {score:.4f}  {node}")
