#!/usr/bin/env python
"""
forge_patch_agent_list_task_executor.py — Ajoute TASK_EXECUTOR à _AGENT_LIST
du hub (tools/nokido_hub.py), fichier CRITIQUE. Patcher SPÉCIFIQUE et IDEMPOTENT
(pas un éditeur générique) : cible et remplacement figés, vérifie avant/après.

Lancé en trusted_script (compte LaForgeTrusted) — seul chemin d'écriture d'un
CRITICAL_FILE hors governed_edit (owner a autorisé la maintenance 2026-07-23).

Usage : run action=trusted_script path=tools/forge_patch_agent_list_task_executor.py
"""
from __future__ import annotations

import json
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "nokido_hub.py"
ANCHOR = '    "DSPY_ROUTER",\n)'
INSERT = (
    '    "DSPY_ROUTER",\n'
    '    "TASK_EXECUTOR",  # exec autonome (ring2) : charge FORGE_TOKEN_TASK_EXECUTOR du vault au boot\n'
    ')'
)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    out: dict = {"target": str(TARGET)}
    if '"TASK_EXECUTOR",' in src and "_AGENT_LIST" in src:
        # déjà présent ?
        idx = src.find("_AGENT_LIST")
        seg = src[idx: idx + 600]
        if '"TASK_EXECUTOR"' in seg:
            out["status"] = "already_present"
            print(json.dumps(out))
            return 0
    if ANCHOR not in src:
        out["status"] = "anchor_not_found"
        print(json.dumps(out))
        return 1
    if src.count(ANCHOR) != 1:
        out["status"] = f"anchor_ambiguous ({src.count(ANCHOR)})"
        print(json.dumps(out))
        return 1
    new = src.replace(ANCHOR, INSERT, 1)
    # validation AST avant écriture
    try:
        compile(new, str(TARGET), "exec")
    except SyntaxError as e:
        out["status"] = f"ast_fail: {e}"
        print(json.dumps(out))
        return 1
    TARGET.write_text(new, encoding="utf-8")
    reread = TARGET.read_text(encoding="utf-8")
    idx = reread.find("_AGENT_LIST")
    out["status"] = "patched"
    out["verified"] = '"TASK_EXECUTOR"' in reread[idx: idx + 600]
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
