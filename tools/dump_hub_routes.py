"""Liste TOUTES les routes/mounts du portail :7400 -> identifier les UI reachable
non tuilees (RAG, Network, Deno, dashboard...). Introspection pure (pas d'auth)."""
import sys

# Racine DERIVEE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
ROOT = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app.web_hub.app import app  # noqa: E402

rows = []
for r in app.routes:
    path = getattr(r, "path", None) or getattr(r, "path_format", "?")
    methods = ",".join(sorted(getattr(r, "methods", []) or [])) or "MOUNT"
    name = getattr(r, "name", "") or ""
    rows.append((path, methods, name))
rows.sort()
for path, methods, name in rows:
    print(f"{path:<42}{methods:<22}{name}")
print("---", len(rows), "routes/mounts")
