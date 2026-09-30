import sys
import os
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Setup
sys.path.insert(0, os.path.abspath("app"))

from nokido_agent.app.forge_graph_rag import GraphRAG


async def test_graph():
    grag = GraphRAG("RAG/embeddings.db")
    print("--- GRAPH STATS ---")
    print(grag.graph_stats())

    print("\n--- TRAVERSAL (Nokido.py) ---")
    res = grag.traverse("Nokido.py", hops=1)
    print(f"Seeds: {res.seed_ids}")
    print(f"Found {len(res.subgraph_edges)} edges.")

    imports = [e for e in res.subgraph_edges if e.rel_type == "IMPORTS"]
    print(f"Imports detected: {len(imports)}")
    for e in imports[:10]:
        print(f"  {e.src} -> {e.dst}")


if __name__ == "__main__":
    import asyncio

    # GraphRAG methods are synchronous in this version
    grag = GraphRAG("RAG/embeddings.db")
    print("--- GRAPH STATS ---")
    print(grag.graph_stats())

    print("\n--- TRAVERSAL (Nokido.py) ---")
    res = grag.traverse("Nokido.py", hops=1)
    print(f"Seeds: {res.seed_ids}")
    print(f"Found {len(res.subgraph_edges)} edges.")

    imports = [e for e in res.subgraph_edges if e.rel_type == "IMPORTS"]
    print(f"Imports detected: {len(imports)}")
    for e in imports[:10]:
        print(f"  {e.src} -> {e.dst}")
