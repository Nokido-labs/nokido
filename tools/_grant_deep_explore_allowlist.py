#!/usr/bin/env python3
"""_grant_deep_explore_allowlist.py — ajoute forge_deep_explore à _ALLOWED_TOOLS
de hub_middleware.py (allowlist STATIQUE /mcp ; sans ça : tool registré+RBAC mais
400 'not allowed' à l'exécution — gotcha documenté L142-144). Idempotent. Reload requis."""

__FORGE_COLOR__ = "immunitaire/rbac : (gele) ajout ponctuel de forge_deep_explore a l'allowlist"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
import pathlib

F = pathlib.Path(__file__).resolve().parent.parent / "tools" / "hub_middleware.py"
src = F.read_text(encoding="utf-8")

if '"forge_deep_explore"' in src:
    print("SKIP: déjà dans _ALLOWED_TOOLS")
    sys.exit(0)

OLD = '''    "forge_stats",
    "skill",
}'''
NEW = '''    "forge_stats",
    "skill",
    # Honeypot delegation : recon LOCALE souveraine (anti-fuite-tokens, 0 token cloud)
    "forge_deep_explore",
}'''

n = src.count(OLD)
if n != 1:
    print(f"ABORT: anchor matches {n}x (need 1)")
    sys.exit(1)
src = src.replace(OLD, NEW)

try:
    compile(src, str(F), "exec")
except SyntaxError as e:
    print(f"ABORT SyntaxError: {e}")
    sys.exit(2)

F.write_text(src, encoding="utf-8")
print("OK: forge_deep_explore ajouté à _ALLOWED_TOOLS")
