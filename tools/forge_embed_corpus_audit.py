"""forge_embed_corpus_audit.py — audit de ce qui est REELLEMENT vectorise (tier chaud).

Repond a "qu'est-ce qui est pertinent uniquement pour l'embedding ?" : compte les
chunks avec embedding NON-NULL (vectorises) vs FTS-only (embedding NULL), et donne
la composition par domain + source. Sert a verifier que seul le vrai-Nokido est
dans le tier vectoriel (pas les 278k libs externes gitingest mal-etiquetees).

Lecture seule (mode=ro), n'interfere pas avec le hub live. Usage :
    LAFORGE_PYTHON tools/forge_embed_corpus_audit.py
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def audit(db: Path = _DB) -> dict:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tot = c.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
    emb = c.execute("SELECT count(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
    by_domain = c.execute(
        "SELECT COALESCE(domain,'<null>'), count(*) FROM rag_chunks "
        "WHERE embedding IS NOT NULL GROUP BY domain ORDER BY 2 DESC LIMIT 15"
    ).fetchall()
    # heuristique pollution : sources qui ne sont pas du vrai code Nokido
    poll = c.execute(
        "SELECT count(*) FROM rag_chunks WHERE embedding IS NOT NULL AND ("
        "source LIKE '%gitingest%' OR source LIKE '%site-packages%' OR "
        "source LIKE '%/.venv/%' OR source LIKE '%apprendre_python%')"
    ).fetchone()[0]
    c.close()
    return {"total": tot, "embedded": emb, "fts_only": tot - emb,
            "suspect_pollution_in_embedded": poll, "by_domain_embedded": by_domain}


def main() -> int:
    import json
    r = audit()
    print(f"total={r['total']}  embedded(vectorise)={r['embedded']}  fts_only={r['fts_only']}")
    print(f"pollution suspecte DANS le tier vectorise = {r['suspect_pollution_in_embedded']}")
    print("composition tier vectorise par domain:")
    for d, n in r["by_domain_embedded"]:
        print(f"  {n:>7}  {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
