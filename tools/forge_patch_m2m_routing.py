#!/usr/bin/env python3
"""Patcher one-shot CRITICAL_FILE : routage M2M vers AGY.

app/forge_mcp_registry.py — deux corrections idempotentes :
  1. _to_map (notify) : alias ANTIGRAVITY/AGY -> agt_antigravity.
  2. handle_task_assign : canonicalise ag_raw AGY==ANTIGRAVITY.

Cause : notify/task.assign visaient agt_agy (inbox jamais drainee, 10 unread)
au lieu de agt_antigravity (46 read, canal reel d'AGY). trusted_script = chemin
officiel d'ecriture d'un CRITICAL_FILE (governed_edit refuse le gate critique).
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "app" / "forge_mcp_registry.py"

R1_SEARCH = (
    '            "cline": "agt_cline",\n'
    '            "hub": "agt_hub",\n'
    "        }\n"
)
R1_REPLACE = (
    '            "cline": "agt_cline",\n'
    '            "hub": "agt_hub",\n'
    '            # ANTIGRAVITY (alias AGY) : identite canonique ring1, inbox agt_antigravity\n'
    '            "ANTIGRAVITY": "agt_antigravity",\n'
    '            "AGY": "agt_antigravity",\n'
    '            "antigravity": "agt_antigravity",\n'
    '            "agy": "agt_antigravity",\n'
    "        }\n"
)
R2_SEARCH = (
    '        ag_raw = (args.get("agent") or "WORKER").upper()\n'
    '        to_agt = f"agt_{ag_raw.lower()}"\n'
)
R2_REPLACE = (
    '        ag_raw = (args.get("agent") or "WORKER").upper()\n'
    "        # Alias identite : AGY == ANTIGRAVITY (inbox canonique drainee agt_antigravity)\n"
    '        if ag_raw in ("AGY", "ANTIGRAVITY"):\n'
    '            ag_raw = "ANTIGRAVITY"\n'
    '        to_agt = f"agt_{ag_raw.lower()}"\n'
)


def apply_block(src, search, replace, tag, sentinel):
    if sentinel in src:
        print(f"  [{tag}] deja applique (sentinel present) -> skip")
        return src, False
    n = src.count(search)
    if n != 1:
        print(f"  [{tag}] ERREUR: {n} occurrence(s) du SEARCH (attendu 1) -> abort")
        sys.exit(2)
    print(f"  [{tag}] 1 occurrence -> patch")
    return src.replace(search, replace, 1), True


def main():
    src = TARGET.read_text(encoding="utf-8")
    orig = src
    src, c1 = apply_block(src, R1_SEARCH, R1_REPLACE, "R1 _to_map",
                          '"AGY": "agt_antigravity"')
    src, c2 = apply_block(src, R2_SEARCH, R2_REPLACE, "R2 task_assign",
                          'if ag_raw in ("AGY", "ANTIGRAVITY")')
    if not (c1 or c2):
        print("Rien a faire (deja patche).")
        return
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"AST INVALIDE apres patch: {e} -> abort, aucune ecriture")
        sys.exit(3)
    TARGET.write_text(src, encoding="utf-8", newline="\n")
    print(f"OK ecrit {TARGET} (+{len(src) - len(orig)} chars). AST valide.")


if __name__ == "__main__":
    main()
