"""
forge_ast_index.py — Index AST code Nokido (ex forge_code_atlas).

Phase 8 (2026-05-24) + Phase 27 (2026-05-25, renomme pour casser
ambiguite avec forge_proprioception qui est l'atlas vitalite multi-axes
au niveau organe). Donne aux agents la navigation AST de leur propre
CODE. Avant d'editer un module, l'agent query
GET /api/graph/proprioception?file=X&depth=2 et recoit :
  - imports_from : modules que ce fichier importe
  - imported_by  : modules qui importent ce fichier (callers)
  - calls_top    : noms de fonctions les plus appelees depuis le fichier

Module leger, AST seul, mono-process, in-RAM. ~100-500ms pour scan complet
LaForge/{app,tools}/. TTL 10min.

API :
    >>> from forge_code_atlas import get_index, ego, summary
    >>> idx = get_index()                  # build lazy + cache
    >>> ego("app/forge_handoff.py", 2)     # {center, imports_from, imported_by, calls_top}
"""

from __future__ import annotations

import ast
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("forge_ast_index")

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
SCAN_DIRS = [ROOT / "app", ROOT / "tools"]

_INDEX: dict[str, Any] = {
    "built_ts": 0.0,
    "scan_duration_s": 0.0,
    "n_files": 0,
    "n_edges": 0,
    "imports_from": {},
    "imported_by": {},
    "calls": {},
}
_BUILD_LOCK = threading.Lock()
_BUILD_TTL_S = 600.0


def _parse_one(path: Path) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError, ValueError) as exc:
        logger.debug("parse skip %s: %s", path.name, exc)
        return [], []
    imports: list[str] = []
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                target = f"{mod}.{alias.name}" if mod else alias.name
                imports.append(target)
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                calls.append(f.attr)
            elif isinstance(f, ast.Name):
                calls.append(f.id)
    return imports, calls


def _build_index() -> dict[str, Any]:
    t0 = time.monotonic()
    imports_from: dict[str, list[str]] = {}
    imported_by: dict[str, list[str]] = defaultdict(list)
    calls: dict[str, list[str]] = {}
    n_edges = 0
    for d in SCAN_DIRS:
        if not d.is_dir():
            continue
        for py in d.rglob("*.py"):
            rel_str = str(py.relative_to(ROOT)).replace("\\", "/")
            if "_attic" in rel_str or "/archive/" in rel_str or "/sandbox/" in rel_str:
                continue
            imps, cls = _parse_one(py)
            imports_from[rel_str] = imps
            calls[rel_str] = sorted(set(cls))
            for imp in imps:
                top = imp.split(".", 1)[0]
                imported_by[top].append(rel_str)
                n_edges += 1
    new_index = {
        "built_ts": time.time(),
        "scan_duration_s": round(time.monotonic() - t0, 3),
        "n_files": len(imports_from),
        "n_edges": n_edges,
        "imports_from": imports_from,
        "imported_by": dict(imported_by),
        "calls": calls,
    }
    logger.info(
        "ast_index built: %d files, %d edges, %.2fs",
        new_index["n_files"],
        n_edges,
        new_index["scan_duration_s"],
    )
    return new_index


def get_index(force_rebuild: bool = False) -> dict[str, Any]:
    global _INDEX
    if not force_rebuild and _INDEX["built_ts"] > 0 and (time.time() - _INDEX["built_ts"]) < _BUILD_TTL_S:
        return _INDEX
    with _BUILD_LOCK:
        if not force_rebuild and _INDEX["built_ts"] > 0 and (time.time() - _INDEX["built_ts"]) < _BUILD_TTL_S:
            return _INDEX
        _INDEX = _build_index()
        return _INDEX


def ego(file: str, depth: int = 1) -> dict[str, Any]:
    depth = max(1, min(3, int(depth)))
    idx = get_index()
    target = file.replace("\\", "/").strip()
    if target not in idx["imports_from"]:
        return {
            "ok": False,
            "error": f"file not in index: {target}",
            "hint": "expected path relative to Nokido root, e.g. 'app/forge_handoff.py'",
            "indexed_files": len(idx["imports_from"]),
        }
    seen_files: set[str] = {target}
    layer_files = [target]
    imports_layers: list[list[str]] = []
    callers_layers: list[list[str]] = []
    for _ in range(depth):
        next_layer_imports: list[str] = []
        next_layer_callers: list[str] = []
        for f in layer_files:
            next_layer_imports.extend(idx["imports_from"].get(f, []))
        for f in layer_files:
            mod_guess = Path(f).stem
            for caller in idx["imported_by"].get(mod_guess, []):
                if caller not in seen_files:
                    next_layer_callers.append(caller)
                    seen_files.add(caller)
        imports_layers.append(sorted(set(next_layer_imports))[:50])
        callers_layers.append(sorted(set(next_layer_callers))[:50])
        layer_files = list(set(next_layer_callers))[:20]
        if not layer_files:
            break
    return {
        "ok": True,
        "center": target,
        "depth": depth,
        "calls_top": idx["calls"].get(target, [])[:30],
        "imports_from": imports_layers,
        "imported_by": callers_layers,
        "stats": {
            "index_age_s": round(time.time() - idx["built_ts"], 1),
            "total_files_indexed": idx["n_files"],
        },
    }


def summary() -> dict[str, Any]:
    idx = get_index()
    return {
        "built_ts": idx["built_ts"],
        "age_s": round(time.time() - idx["built_ts"], 1),
        "n_files": idx["n_files"],
        "n_edges": idx["n_edges"],
        "scan_duration_s": idx["scan_duration_s"],
        "scan_dirs": [str(d.relative_to(ROOT)) for d in SCAN_DIRS if d.is_dir()],
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        print(json.dumps(ego(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2), indent=2))
    else:
        print(json.dumps(summary(), indent=2))
