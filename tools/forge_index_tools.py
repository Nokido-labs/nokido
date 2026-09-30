"""One-shot : indexe tools/ dans le RAG (comble le trou des 241 modules tools/forge_*
jamais vectorisés). Diagnostic : teste changed_only puis force. cf census 2026-06-05."""
import sys
from pathlib import Path

# Chemins DERIVES du fichier (phase 0 du renommage vers Nokido) : tools/ -> parent.parent.
_RACINE = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RACINE))
from nokido_agent.app.forge_rag_index_app import index_app_dir  # noqa: E402

tools = _RACINE / "tools"
print("[1] changed_only=True ...")
try:
    s1 = index_app_dir(target_dir=tools, changed_only=True, verbose=False)
    print("   ", s1)
except Exception as e:
    print("   ERR", type(e).__name__, e)
print("[2] changed_only=False (force) ...")
try:
    s2 = index_app_dir(target_dir=tools, changed_only=False, verbose=False)
    print("   ", s2)
except Exception as e:
    print("   ERR", type(e).__name__, e)
