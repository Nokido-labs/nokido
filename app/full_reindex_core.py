
__FORGE_COLOR__ = "memoire/rag : reindexation complete du coeur"  # organe declare le 2026-09-06 (audit de raccordement)
import os

# Bypasser le wizard interactif SSH avant d'importer quoi que ce soit
os.environ["LAFORGE_ENV"] = "test"
os.environ["SSH_HOST"] = "127.0.0.1"
os.environ["SSH_USER"] = "dummy"
os.environ["PRIVATE_KEY_PATH"] = "dummy.key"

import asyncio
import sys
from pathlib import Path

# Injection du path pour trouver les modules
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_rag_engine import get_rag


async def reindex():
    # On initialise le RAG avec le db_path reel
    db_path = str(ROOT / "RAG" / "embeddings.db")
    rag = get_rag(db_path=db_path)
    print(f"📥 Début de la ré-indexation du Core (DB: {db_path})...")

    # Dossiers à indexer (relatifs à ROOT)
    dirs = [ROOT / "app", ROOT / "tools"]
    count = 0

    for d in dirs:
        p = Path(d)
        if not p.exists():
            continue

        for f in p.rglob("*.py"):
            # Ignorer les fichiers temporaires et les backups
            if any(x in str(f) for x in ["tmp_", "test_", "backup", ".bak"]):
                continue

            print(f"  -> Indexation : {f}")
            await rag.add_document(f)
            count += 1

    print(f"\n✅ Ré-indexation terminée : {count} fichiers ingérés.")


if __name__ == "__main__":
    asyncio.run(reindex())
