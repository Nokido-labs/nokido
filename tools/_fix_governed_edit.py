#!/usr/bin/env python3
"""_fix_governed_edit.py — ouvre governed_edit au client ring 3 (le dernier pont
gouverné avant la castration #4). governed_edit = écriture in-process GOUVERNÉE
(AST + scan secret + tree_lock) -> strictement + sûr que le Write natif non-gouverné.
3 gates : _ALLOWED_TOOLS + _TOOL_MIN_RING(1->3) + forge_tools DB. Idempotent."""

__FORGE_COLOR__ = "immunitaire/rbac : (gele) ouverture ponctuelle de governed_edit au ring 3"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
import sqlite3
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
done = []

# gate 1 : _TOOL_MIN_RING 1 -> 3 (ring 3 = CLAUDE/GEMINI clients)
REG = ROOT / "app" / "forge_mcp_registry.py"
rsrc = REG.read_text(encoding="utf-8")
OLD_R = '        "governed_edit": 1,'
NEW_R = '        "governed_edit": 3,'
if NEW_R in rsrc:
    done.append("min_ring: déjà 3")
elif rsrc.count(OLD_R) == 1:
    rsrc = rsrc.replace(OLD_R, NEW_R)
    try:
        compile(rsrc, str(REG), "exec")
    except SyntaxError as e:
        print(f"ABORT registry SyntaxError: {e}"); sys.exit(2)
    REG.write_text(rsrc, encoding="utf-8")
    done.append("min_ring 1->3")
else:
    print(f"ABORT: ancre _TOOL_MIN_RING governed_edit matches {rsrc.count(OLD_R)}x"); sys.exit(1)

# gate 2 : _ALLOWED_TOOLS
MID = ROOT / "tools" / "hub_middleware.py"
msrc = MID.read_text(encoding="utf-8")
if '"governed_edit"' in msrc:
    done.append("_ALLOWED_TOOLS: déjà")
else:
    OLD_M = '''    # Bouton rouge declaratif : ensure service state (anti-bricolage infra client)
    "nokido_ensure_service",
}'''
    NEW_M = '''    # Bouton rouge declaratif : ensure service state (anti-bricolage infra client)
    "nokido_ensure_service",
    # Edition GOUVERNEE in-process (pont client : remplace le Write natif non-gouverne)
    "governed_edit",
}'''
    if msrc.count(OLD_M) != 1:
        print(f"ABORT: ancre _ALLOWED_TOOLS matches {msrc.count(OLD_M)}x"); sys.exit(1)
    msrc = msrc.replace(OLD_M, NEW_M)
    try:
        compile(msrc, str(MID), "exec")
    except SyntaxError as e:
        print(f"ABORT middleware SyntaxError: {e}"); sys.exit(2)
    MID.write_text(msrc, encoding="utf-8")
    done.append("_ALLOWED_TOOLS: ajouté")

# gate 3 : forge_tools DB
c = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"))
cols = [r[1] for r in c.execute("PRAGMA table_info(forge_tools)").fetchall()]
if c.execute("SELECT 1 FROM forge_tools WHERE tool_name='governed_edit'").fetchone():
    c.execute("UPDATE forge_tools SET min_ring=3, is_active=1 WHERE tool_name='governed_edit'")
    done.append("forge_tools: UPDATED min_ring=3")
else:
    vals = {"tool_name": "governed_edit", "min_ring": 3, "is_active": 1}
    if "description" in cols:
        vals["description"] = "Governed in-process edit (AST+secret+lock) — client edit bridge."
    if "category" in cols:
        vals["category"] = "edit"
    use = [k for k in vals if k in cols]
    c.execute(f"INSERT INTO forge_tools ({','.join(use)}) VALUES ({','.join('?' for _ in use)})",
              [vals[k] for k in use])
    done.append("forge_tools: INSERTED min_ring=3")
c.commit()
row = c.execute("SELECT tool_name,min_ring,is_active FROM forge_tools WHERE tool_name='governed_edit'").fetchall()
c.close()

print("OK governed_edit ouvert ring 3 :", " | ".join(done), "| DB:", row)
