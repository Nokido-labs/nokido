# -*- coding: utf-8 -*-
"""One-shot patcher: dedup GUI Phase 6 — :8766 /forge/{rag,swarm,postal} -> 302 :7400.

La GUI humaine vit sur web_hub :7400 (stylee z.ai, campagne 7/7 verte). Le hub :8766
= API/MCP/agent : il n'a pas a servir les MEMES pages HTML dupliquees. On remplace le
CORPS des 3 handlers (rag_ui/swarm_ui/postal_ui) par un redirect 302 vers :7400 ; def +
docstring GARDES (legacy), les API /api/{rag,swarm}/* restent servies ici. Reversible.

CRITICAL_FILE (nokido_hub.py) -> applique via owner trusted_script (miroir
forge_patch_mcpsec_fix3 / forge_patch_registry_tothread) : exact-match count==1 par bloc,
idempotent, AST compile AVANT ecriture, newline preserve. Abort sans ecrire au moindre
ecart. N'ACTIVE RIEN tant que le hub n'est pas redemarré (module en RAM inchange).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "tools", "nokido_hub.py")

REDIR = (
    '        # Dedup Phase 6 (2026-07-03) : GUI humaine = web_hub :7400 (stylee, verte).\n'
    '        # :8766 = API/MCP/agent -> page dupliquee redirigee ; API /api/* restent ici.\n'
    '        return Response(status_code=302, headers={{"Location": "http://127.0.0.1:7400/{route}"}})'
)

BLOCKS = [
    # rag_ui (chemin multi-ligne parenthese)
    ('        try:\n'
     '            html_path = (\n'
     '                Path(__file__).resolve().parent.parent / "app" / "web_hub" / "rag_dashboard.html"\n'
     '            )\n'
     '            return HTMLResponse(html_path.read_text(encoding="utf-8"))\n'
     '        except Exception as e:\n'
     '            return JSONResponse({"error": str(e)}, status_code=500)',
     REDIR.format(route="rag")),
    # swarm_ui (bearer inject)
    ('        try:\n'
     '            html_path = Path(__file__).resolve().parent.parent / "app" / "web_hub" / "swarm.html"\n'
     '            html = html_path.read_text(encoding="utf-8")\n'
     '            tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""\n'
     '            html = html.replace("__LAFORGE_BEARER__", tok)\n'
     '            return HTMLResponse(html)\n'
     '        except Exception as e:\n'
     '            return JSONResponse({"error": str(e)}, status_code=500)',
     REDIR.format(route="swarm")),
    # postal_ui
    ('        try:\n'
     '            html_path = Path(__file__).resolve().parent.parent / "app" / "web_hub" / "postal.html"\n'
     '            return HTMLResponse(html_path.read_text(encoding="utf-8"))\n'
     '        except Exception as e:\n'
     '            return JSONResponse({"error": str(e)}, status_code=500)',
     REDIR.format(route="postal")),
]

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "Dedup Phase 6" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for i, (old, _new) in enumerate(BLOCKS):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {i} found {n} times (expected 1) -> no write")
        sys.exit(2)

for old, new in BLOCKS:
    text = text.replace(old, new, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

open(TARGET, "wb").write(text.replace("\n", nl).encode("utf-8"))
print(f"OK: 3 handlers GUI :8766 -> 302 :7400 + AST valide. newline={nl!r}")
