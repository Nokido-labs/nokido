#!/usr/bin/env python3
"""_grant_deep_explore.py — grant forge_deep_explore dans forge_tools (source de vérité
RBAC exec, lue live par dispatch). min_ring=4 -> exécutable par TOUT client (ring<=4).
Sans ça : tool listé mais 'not allowed' à l'exécution. Idempotent. Pas de reload requis."""

__FORGE_COLOR__ = "immunitaire/rbac : (gele) grant ponctuel de forge_deep_explore dans forge_tools"  # organe declare le 2026-09-06 (audit de raccordement)
import sqlite3
import pathlib

DB = pathlib.Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
c = sqlite3.connect(str(DB))
cols = [r[1] for r in c.execute("PRAGMA table_info(forge_tools)").fetchall()]
print("forge_tools cols:", cols)

exists = c.execute("SELECT 1 FROM forge_tools WHERE tool_name=?", ("forge_deep_explore",)).fetchone()
if exists:
    c.execute("UPDATE forge_tools SET min_ring=4, is_active=1 WHERE tool_name=?", ("forge_deep_explore",))
    print("UPDATED existing row")
else:
    # construire un INSERT avec uniquement les colonnes connues + valeurs sûres
    vals = {"tool_name": "forge_deep_explore", "min_ring": 4, "is_active": 1}
    if "description" in cols:
        vals["description"] = "Honeypot delegation: local sovereign recon (0 cloud token)."
    if "category" in cols:
        vals["category"] = "recon"
    use = [k for k in vals if k in cols]
    sql = f"INSERT INTO forge_tools ({','.join(use)}) VALUES ({','.join('?' for _ in use)})"
    try:
        c.execute(sql, [vals[k] for k in use])
        print("INSERTED row")
    except Exception as e:
        print("INSERT failed:", type(e).__name__, str(e)[:120])
c.commit()
print("now:", c.execute("SELECT tool_name,min_ring,is_active FROM forge_tools WHERE tool_name='forge_deep_explore'").fetchall())
c.close()
