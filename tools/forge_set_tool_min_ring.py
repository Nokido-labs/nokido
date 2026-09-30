#!/usr/bin/env python3
"""forge_set_tool_min_ring.py — setter gouverne du min_ring d'un tool.

Contrepartie ECRITURE de check_forge_tools.py (qui ne fait que lire).
Source de verite = table forge_tools dans RAG/embeddings.db, lue LIVE par
forge_mcp_registry._get_ring_needed a chaque appel (no reload requis).

Usage (via run action=trusted_script, script_args) :
    --tool <name> --ring <0..4> [--dry]

min_ring = ring MAX autorise (gate: caller_ring <= min_ring). Ex min_ring=2
=> rings 0,1,2 OK ; ring 3 (Gemini) refuse.
"""

__FORGE_COLOR__ = "immunitaire/rbac : setter gouverne du min_ring d'un tool"  # organe declare le 2026-09-06 (audit de raccordement)
import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True)
    ap.add_argument("--ring", required=True, type=int)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    if a.ring < 0 or a.ring > 4:
        print(f"REFUS: ring {a.ring} hors bornes 0..4")
        return 2

    c = sqlite3.connect(str(DB), timeout=10)
    row = c.execute(
        "SELECT tool_name, min_ring, is_active FROM forge_tools WHERE tool_name=?",
        (a.tool,),
    ).fetchone()
    if not row:
        print(f"REFUS: tool '{a.tool}' absent de forge_tools")
        c.close()
        return 3

    print(f"AVANT: {row[0]} min_ring={row[1]} is_active={row[2]}")
    if a.dry:
        print("DRY: aucune ecriture")
        c.close()
        return 0
    if row[1] == a.ring:
        print(f"NOOP: min_ring deja {a.ring}")
        c.close()
        return 0

    c.execute(
        "UPDATE forge_tools SET min_ring=? WHERE tool_name=?", (a.ring, a.tool)
    )
    c.commit()
    after = c.execute(
        "SELECT min_ring FROM forge_tools WHERE tool_name=?", (a.tool,)
    ).fetchone()
    c.close()
    print(f"APRES: {a.tool} min_ring={after[0]} (live-read gate, no reload)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
