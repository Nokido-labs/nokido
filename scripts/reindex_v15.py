import asyncio
import sys
import io
from pathlib import Path

# Fix Windows encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Setup du path pour importer LaForge/app
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from forge_app_context import app_ctx
from forge_rag_engine import get_rag

async def slow_reindex():
    print("🧠 Initialisation du contexte LaForge...")
    ctx = app_ctx()  # Force le chargement des settings
    if ctx.settings is None:
        import types
        ctx.settings = types.SimpleNamespace()
    if not hasattr(ctx.settings, "rag_dir") or ctx.settings.rag_dir is None:
        ctx.settings.rag_dir = str(ROOT / "RAG" / "rag_files")
        
    rag = get_rag(db_path=str(ROOT / "RAG" / "embeddings.db"))
    app_dir = ROOT / "app"
    
    print("⏳ Démarrage du RAG Reindex (Mode Slow / 1024d Stable IDs)...")
    count = 0
    for p in app_dir.rglob("*.py"):
        if "_attic" in str(p) or "_archive" in str(p) or "archive" in str(p):
            continue
        try:
            # Audit 2026-06-17 : Utilisation d'IDs déterministes (hash source+text) 
            # pour éviter les doublons et permettre le refresh du sidecar de Claude.
            print(f"  -> Vectorizing: {p.name} (1024d)")
            await rag.add_document(p.resolve()) # add_document doit déjà gérer le REPLACE par ID
            count += 1
            await asyncio.sleep(0.5) 
        except Exception as e:
            print(f"  [X] Erreur sur {p.name}: {e}")
            
    print(f"✅ Reindex terminé. {count} modules ingérés dans la matrice.")

if __name__ == "__main__":
    asyncio.run(slow_reindex())
