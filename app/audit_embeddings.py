import sqlite3
import os
import sys
from pathlib import Path
from collections import Counter


def audit_missing_embeddings():
    db_path = "LaForge/RAG/embeddings.db"
    if not os.path.exists(db_path):
        print(f"Erreur: DB non trouvée à {db_path}")
        return

    conn = sqlite3.connect(db_path)
    # On regarde les sources des chunks qui n'ont pas de vecteur
    rows = conn.execute("SELECT source, domain FROM rag_chunks WHERE embedding IS NULL").fetchall()
    conn.close()

    if not rows:
        print("✅ Aucun chunk sans embedding détecté.")
        return

    print(f"📊 Audit de {len(rows)} chunks sans embeddings :\n")

    # Statistiques par domaine
    domains = Counter([r[1] for r in rows])
    print("Par domaine :")
    for dom, count in domains.most_common():
        print(f"  - {dom:15}: {count}")

    # Top sources problématiques
    print("\nTop 10 sources sans vecteurs :")
    sources = Counter([r[0].split("#")[0] for r in rows])
    for src, count in sources.most_common(10):
        print(f"  - {src:50}: {count} chunks")


if __name__ == "__main__":
    audit_missing_embeddings()
