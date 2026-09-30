#!/usr/bin/env python3
"""
tools/check_lazy_cycles.py - Linter: verifie que tous les cycles d imports
restent LAZY (dans fonctions), jamais au niveau MODULE.

Usage:
    python tools/check_lazy_cycles.py

Exit code:
    0 : aucun cycle bloquant (tous cycles sont lazy) -- OK
    1 : au moins un cycle BLOQUANT (imports module-level) -- FAIL
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")


def collect_module_level_imports(file_path):
    """Retourne les modules importes au niveau top-level (pas lazy)."""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src)
    except (SyntaxError, OSError):
        return set()
    imports = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
    return imports


def check_cycles():
    """Detecte les cycles BLOQUANTS (A<->B au niveau module)."""
    if not os.path.isdir(APP_DIR):
        return []
    py_files = {
        f[:-3]: os.path.join(APP_DIR, f)
        for f in os.listdir(APP_DIR)
        if f.endswith(".py") and os.path.isfile(os.path.join(APP_DIR, f))
    }
    graph = {}
    for mod_name, path in py_files.items():
        mod_imports = collect_module_level_imports(path)
        graph[mod_name] = mod_imports & set(py_files.keys())
    bad_cycles = []
    seen = set()
    for a, deps in graph.items():
        for b in deps:
            if a in graph.get(b, set()):
                key = tuple(sorted([a, b]))
                if key not in seen:
                    seen.add(key)
                    bad_cycles.append((a, b))
    return bad_cycles


def main():
    """Entry point."""
    bad = check_cycles()
    if bad:
        print(f"[FAIL] {len(bad)} cycle(s) BLOQUANT(S) detecte(s):")
        for a, b in bad:
            print(f"  - {a} <-> {b}")
        msg = "Correction: deplacer au moins un import dans une fonction (lazy)."
        print(msg)
        return 1
    print("[OK] Aucun cycle d import bloquant (tous les cycles sont lazy)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
