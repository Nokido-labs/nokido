#!/usr/bin/env python
"""One-shot patcher : câble gate_tool_call (gate d'intention Agent Policier) dans
forge_mcp_registry.dispatch(), juste après le check RBAC. WARN-mode, fail-open.

Applique 1 bloc SEARCH/REPLACE (bytes exacts en C:/tmp/patch_ig), valide l'AST via
py_compile AVANT d'écrire. Idempotent (no-op si déjà câblé). Lancé via trusted_script.
"""
from __future__ import annotations
import sys
import pathlib
import py_compile

BASE = pathlib.Path(r"C:/tmp/patch_ig")
ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "forge_mcp_registry.py"


def _load(name: str) -> str:
    return BASE.joinpath(name).read_text(encoding="utf-8").rstrip("\n")


def main() -> int:
    if not TARGET.exists():
        print(f"ABORT: cible absente {TARGET}")
        return 4
    src = TARGET.read_text(encoding="utf-8")
    s1, r1 = _load("ig_s1.txt"), _load("ig_r1.txt")
    if "from forge_intention_gate import gate_tool_call" in src:
        print("NO-OP: déjà câblé")
        return 0
    n = src.count(s1)
    if n != 1:
        print(f"ABORT: bloc SEARCH trouvé {n}x (attendu 1) -> aucune écriture")
        return 2
    src = src.replace(s1, r1, 1)
    tmp = TARGET.with_suffix(".py.tmp_igpatch")
    tmp.write_text(src, encoding="utf-8")
    try:
        py_compile.compile(str(tmp), doraise=True)
    except py_compile.PyCompileError as e:
        tmp.unlink(missing_ok=True)
        print(f"ABORT: AST invalide -> aucune écriture\n{e}")
        return 3
    tmp.replace(TARGET)
    print(f"WIRING OK -> {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
