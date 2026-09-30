"""tem_query_demo.py - Demo TEM composite search vs content-only.

Compare retrieval results :
- Standard : forge_rag_engine search(content_emb)
- TEM     : tem_search(content_emb, structure_emb)

Usage : LAFORGE_PYTHON tools/tem_query_demo.py "query text"
"""

__FORGE_COLOR__ = "memoire/rag : demo TEM, recherche composite contre contenu seul"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_embed_router import embed
from nokido_agent.app.forge_tem_factorize import tem_compose, tem_search


def main():
    if len(sys.argv) < 2:
        print("Usage: tem_query_demo.py <query>")
        return
    query = sys.argv[1]

    print(f"Query: {query}\n")
    content_emb = embed(query)
    if not content_emb:
        print("[FAIL] no content embedding")
        return
    print(f"content_emb dim={len(content_emb)} ok")

    # Structure : neutral (no specific chunk context), test fallback
    structure_emb = [0.0] * len(content_emb)
    composite = tem_compose(content_emb, structure_emb, alpha=0.85)
    print(f"composite dim={len(composite)}")

    # Standard search via TEM (compat content-only when no structure)
    try:
        results = tem_search(content_emb, None, k=5)
        print("\n=== Standard search (content-only) ===")
        for r in results[:5]:
            print(f"  - {r.get('source', '')[:60]} score={r.get('score', '?')}")
    except Exception as e:
        print(f"standard search KO: {e}")

    # TEM search with structure (degraded since neutral)
    try:
        results_tem = tem_search(content_emb, structure_emb, k=5)
        print("\n=== TEM search (composite content+structure) ===")
        for r in results_tem[:5]:
            print(f"  - {r.get('source', '')[:60]} score={r.get('score', '?')}")
    except Exception as e:
        print(f"TEM search KO: {e}")


if __name__ == "__main__":
    main()
