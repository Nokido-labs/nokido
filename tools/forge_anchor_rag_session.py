"""forge_anchor_rag_session.py — Ancre les decisions de la session RAG dans Nokido.

Nokido est l'intelligence persistante : toute decision architecturale doit
revenir en entree RAG indexee (anchor_solution -> rag_chunks + rag_fts +
lessons_learned.md). Ce script ancre l'overhaul + l'optimisation RAG 2026-05-21.

Run : run action=trusted_script path=tools/forge_anchor_rag_session.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nokido_agent.app.forge_self_correction import anchor_solution  # noqa: E402

ANCHORS = [
    (
        "RAG : tier vectoriel pollue a 80% (gitingest de libs externes "
        "mal-etiquete en domaines nokido_code/ami/general)",
        "Champ `origin` (provenance) derive de source+domain par regle unique, "
        "tiering par politique. tools/forge_tier_policy.py = HOT_TIER_SQL, source "
        "unique de verite. forge_rebuild_local + forge_embed_auto_trigger filtrent "
        "dessus : seul le contenu genuinement Nokido est vectorise.",
        "from forge_tier_policy import HOT_TIER_SQL  # clause WHERE tier chaud",
        "rag",
    ),
    (
        "RAG : les embeddings du code etaient vides a chaque restart du hub",
        "forge_rag_index_app.index_file faisait DELETE + INSERT sans la colonne "
        "embedding ni id (id=NULL, embeddings perdus) et son check `changed_only` "
        "ne matchait jamais. Fix : check hash via LIKE sur sources suffixees, "
        "preservation des embeddings par texte de chunk, id deterministe sha256.",
        "index_file : old_emb={text:embedding} sauve avant DELETE, repris a l'INSERT",
        "rag",
    ),
    (
        "RAG : chunking naif (120 mots + overlap) -> embeddings peu discriminants",
        "Chunker AST Python dans forge_rag_index_app._chunk_python : un chunk par "
        "fonction/methode/classe via ast.parse, ids symboliques source#Classe."
        "methode (Small-to-Big ready). Re-bench dense+rerank : R@10 0.72->0.85, "
        "NDCG@10 0.64->0.72 (n=102).",
        "_chunk_python : ast.parse(text), 1 chunk par FunctionDef/ClassDef",
        "rag",
    ),
    (
        "hub : le `rag` tool retournait 'Aucun resultat' sur toute requete",
        "handle_rag action=search appelait handle_search_recent : SQL LIKE primitif "
        "scope a domain=mcp_result. Remplace par pipeline hybride dans "
        "forge_mcp_registry._rag_dense_search : Self-Query pre-filtre langage + "
        "dense bge-m3 (:8099) + BM25 FTS5 code-tune (k1=1.2 b=0.5) + union + rerank "
        "cross-encoder (:8100) + context-reorder. query_log pour le predictif.",
        "_rag_dense_search : dense+BM25 union -> rerank :8100",
        "rag",
    ),
    (
        "Embeddings : stockage JSON-TEXT (~22 Ko/vecteur) = antipattern",
        "Tout embedding persistant doit etre BLOB float32 binaire (4096 o). "
        "forge_embed_json_to_blob.py reencode ; le JSON ne sert qu'au transport "
        "HTTP. Stockage = binaire exclusivement.",
        "struct.pack('1024f', *vec) pour le BLOB",
        "rag",
    ),
]


def main() -> None:
    ok = 0
    for problem, solution, example, domain in ANCHORS:
        try:
            anchor_solution(problem=problem, solution=solution, example=example, domain=domain)
            ok += 1
            print(f"[anchor] OK : {problem[:60]}")
        except Exception as e:  # noqa: BLE001
            print(f"[anchor] ERR {type(e).__name__}: {str(e)[:160]}")
    print(f"[anchor] {ok}/{len(ANCHORS)} decisions ancrees dans Nokido")


if __name__ == "__main__":
    main()
