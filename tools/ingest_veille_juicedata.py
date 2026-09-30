#!/usr/bin/env python3
"""Trigger one-shot de l'ingestion gitingest + verif RAG (juicedata)."""
import sys
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def rag_count():
    db = ROOT / "RAG" / "embeddings.db"
    if not db.exists():
        return f"no db at {db}"
    try:
        con = sqlite3.connect(str(db), timeout=15)
        n = con.execute(
            "SELECT count(*) FROM rag_fts WHERE rag_fts MATCH ?",
            ("juicefs OR juicesync OR juicedata",),
        ).fetchone()[0]
        con.close()
        return n
    except Exception as e:
        return f"query_err: {e}"


def main():
    print(f"[avant] rag matches juicefs* = {rag_count()}")
    files = sorted((ROOT / "data" / "gitingest").glob("juicedata_*.txt"))
    print(f"dumps presents: {[f.name for f in files]}")
    try:
        from nokido_agent.app.forge_autonomous_loops import pat_repo_ingestion
        res = pat_repo_ingestion()
        print(f"pat_repo_ingestion -> {res}")
    except Exception as e:
        print(f"trigger ERR: {e}")
    print(f"[apres] rag matches juicefs* = {rag_count()}")


if __name__ == "__main__":
    main()
