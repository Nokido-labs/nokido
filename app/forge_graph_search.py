# forge_graph_search.py — Interface CLI pour Graph-RAG
# Usage depuis MCP: run(action='python', code='from forge_graph_search import search; print(search("query"))')
# Usage CLI: python app/forge_graph_search.py "SSRF Flask"
from __future__ import annotations
import json, sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

DB_PATH = str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")


def search(query, hops=2, top_k=5):
    """Recherche Graph-RAG et retourne les chunks pertinents."""
    from nokido_agent.app.forge_graph_rag import GraphRAG

    grag = GraphRAG(DB_PATH)
    result = grag.traverse(query, hops=hops, top_k=top_k)

    output = []
    for c in result.ranked_chunks:
        output.append(
            {
                "domain": c["domain"],
                "source": c["source"].split("/")[-1].split("\\")[-1][:50],
                "score": c["score"],
                "hop": c["hop_distance"],
                "text": c["text"][:200],
            }
        )

    return {
        "query": query,
        "seeds": len(result.seed_ids),
        "nodes": len(result.subgraph_nodes),
        "edges": len(result.subgraph_edges),
        "time_ms": round(result.stats.get("time_s", 0) * 1000),
        "chunks": output,
    }


def stats():
    """Retourne les statistiques du Graph-RAG."""
    from nokido_agent.app.forge_graph_rag import GraphRAG

    grag = GraphRAG(DB_PATH)
    return grag.graph_stats()


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "SSRF exploit"
    result = search(query)
    print(json.dumps(result, indent=2, ensure_ascii=False))
