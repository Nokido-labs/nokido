#!/usr/bin/env python
"""One-shot patcher (CRITICAL_FILE path) : ajoute action=schema a l'outil query.

Applique 2 blocs SEARCH/REPLACE (bytes exacts en C:/tmp/patch_qs) sur
app/forge_mcp_registry.py, valide l'AST via py_compile AVANT d'ecrire.
Idempotent : no-op si deja patche. Lance via run action=trusted_script.
"""
from __future__ import annotations
import sys
import pathlib
import py_compile

BASE = pathlib.Path(r"C:/tmp/patch_qs")
ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "forge_mcp_registry.py"


def _load(name: str) -> str:
    # text mode => \r\n normalises en \n (match robuste quel que soit l'EOL disque)
    return BASE.joinpath(name).read_text(encoding="utf-8").rstrip("\n")


def main() -> int:
    if not TARGET.exists():
        print(f"ABORT: cible absente {TARGET}")
        return 4
    src = TARGET.read_text(encoding="utf-8")
    pairs = [(_load("qs_s1.txt"), _load("qs_r1.txt")),
             (_load("qs_s2.txt"), _load("qs_r2.txt"))]
    changed = False
    for s, r in pairs:
        if r in src:
            print("SKIP: bloc deja present")
            continue
        n = src.count(s)
        if n != 1:
            print(f"ABORT: bloc SEARCH trouve {n}x (attendu 1) -> aucune ecriture")
            return 2
        src = src.replace(s, r, 1)
        changed = True
    if not changed:
        print("NO-OP: deja patche integralement")
        return 0
    tmp = TARGET.with_suffix(".py.tmp_patch")
    tmp.write_text(src, encoding="utf-8")
    try:
        py_compile.compile(str(tmp), doraise=True)
    except py_compile.PyCompileError as e:
        tmp.unlink(missing_ok=True)
        print(f"ABORT: AST invalide -> aucune ecriture\n{e}")
        return 3
    tmp.replace(TARGET)
    print(f"PATCH OK -> {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
