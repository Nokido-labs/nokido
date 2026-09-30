#!/usr/bin/env python3
"""_grant_ensure_service.py — gates 3 & 4 pour nokido_ensure_service :
forge_tools DB (RBAC exec, min_ring=4, lu live) + hub_middleware._ALLOWED_TOOLS
(allowlist statique /mcp, reload requis). Idempotent."""

__FORGE_COLOR__ = "immunitaire/rbac : (gele) gates 3 et 4 de nokido_ensure_service, ponctuel"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
import sqlite3
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = "nokido_ensure_service"

# --- gate 3 : forge_tools DB ---
DB = ROOT / "RAG" / "embeddings.db"
c = sqlite3.connect(str(DB))
cols = [r[1] for r in c.execute("PRAGMA table_info(forge_tools)").fetchall()]
if c.execute("SELECT 1 FROM forge_tools WHERE tool_name=?", (TOOL,)).fetchone():
    c.execute("UPDATE forge_tools SET min_ring=4, is_active=1 WHERE tool_name=?", (TOOL,))
    print("forge_tools: UPDATED")
else:
    vals = {"tool_name": TOOL, "min_ring": 4, "is_active": 1}
    if "description" in cols:
        vals["description"] = "Declarative red button: ensure a Nokido service state (hub-orchestrated)."
    if "category" in cols:
        vals["category"] = "ops"
    use = [k for k in vals if k in cols]
    c.execute(f"INSERT INTO forge_tools ({','.join(use)}) VALUES ({','.join('?' for _ in use)})",
              [vals[k] for k in use])
    print("forge_tools: INSERTED")
c.commit()
print("forge_tools now:", c.execute("SELECT tool_name,min_ring,is_active FROM forge_tools WHERE tool_name=?", (TOOL,)).fetchall())
c.close()

# --- gate 4 : hub_middleware._ALLOWED_TOOLS ---
F = ROOT / "tools" / "hub_middleware.py"
src = F.read_text(encoding="utf-8")
if f'"{TOOL}"' in src:
    print("_ALLOWED_TOOLS: déjà présent")
    sys.exit(0)
OLD = '''    # Honeypot delegation : recon LOCALE souveraine (anti-fuite-tokens, 0 token cloud)
    "forge_deep_explore",
}'''
NEW = '''    # Honeypot delegation : recon LOCALE souveraine (anti-fuite-tokens, 0 token cloud)
    "forge_deep_explore",
    # Bouton rouge declaratif : ensure service state (anti-bricolage infra client)
    "nokido_ensure_service",
}'''
n = src.count(OLD)
if n != 1:
    print(f"ABORT _ALLOWED_TOOLS anchor matches {n}x (need 1)")
    sys.exit(1)
src = src.replace(OLD, NEW)
try:
    compile(src, str(F), "exec")
except SyntaxError as e:
    print(f"ABORT SyntaxError: {e}")
    sys.exit(2)
F.write_text(src, encoding="utf-8")
print("_ALLOWED_TOOLS: ajouté")
