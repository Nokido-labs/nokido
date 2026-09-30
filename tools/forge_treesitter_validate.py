#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_treesitter_validate.py — validation structurelle PRÉ-write (multi-langage).

Le hook AST PostToolUse ne valide QUE le Python, et POST-hoc. Tree-sitter parse
en millisecondes dans ~40 langages et signale les nœuds ERROR/MISSING → on peut
rejeter un patch LLM syntaxiquement cassé AVANT de l'écrire (JS/TS/Go/Rust/YAML…).

FAIL-OPEN : si tree-sitter ou la grammaire du langage manque, validate() renvoie
ok=True avec reason='unavailable' → ne bloque JAMAIS à tort (le hook Python AST
reste le filet pour .py). Roadmap observabilité chantier #5.

Usage :
    forge_treesitter_validate.py <fichier> [<fichier> ...]
    # ou importer : from forge_treesitter_validate import validate
"""
from __future__ import annotations

import os
import sys

# Extension → langage tree-sitter (noms tree_sitter_languages).
EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".java": "java",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".cs": "c_sharp", ".php": "php", ".lua": "lua", ".sh": "bash",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml",
    ".html": "html", ".css": "css", ".sql": "sql", ".md": "markdown",
}

_PARSERS: dict = {}
_UNAVAILABLE: str | None = None


def _get_parser(lang: str):
    """Parser tree-sitter pour le langage, ou None (fail-open). Caché."""
    global _UNAVAILABLE
    if _UNAVAILABLE is not None:
        return None
    if lang in _PARSERS:
        return _PARSERS[lang]
    try:
        from tree_sitter_languages import get_parser  # grammaires prébuildées
        p = get_parser(lang)
        _PARSERS[lang] = p
        return p
    except Exception as exc:  # noqa: BLE001 - sdk/grammaire absent → fail-open
        # On ne désactive que si tree_sitter_languages lui-même manque ;
        # une grammaire isolée absente ne coupe pas les autres langages.
        if "tree_sitter_languages" in str(exc) or isinstance(exc, ImportError):
            _UNAVAILABLE = f"tree_sitter_languages indisponible: {exc}"
        _PARSERS[lang] = None
        return None


def _collect_errors(node, src: bytes, out: list, limit: int = 20) -> None:
    if len(out) >= limit:
        return
    if node.type == "ERROR" or getattr(node, "is_missing", False):
        sl, sc = node.start_point
        snippet = src[node.start_byte:node.end_byte][:60].decode("utf-8", "replace")
        out.append({"line": sl + 1, "col": sc + 1,
                    "kind": "MISSING" if getattr(node, "is_missing", False) else "ERROR",
                    "snippet": snippet.replace("\n", " ")})
    for child in node.children:
        _collect_errors(child, src, out, limit)


def validate(code: str, lang: str | None = None, path: str | None = None) -> dict:
    """Valide la structure. Retourne {ok, lang, reason, errors:[...]}.

    ok=False UNIQUEMENT si le parser existe ET trouve des ERROR/MISSING.
    """
    if lang is None and path:
        lang = EXT_LANG.get(os.path.splitext(path)[1].lower())
    if not lang:
        return {"ok": True, "lang": None, "reason": "unmapped_extension", "errors": []}
    parser = _get_parser(lang)
    if parser is None:
        return {"ok": True, "lang": lang, "reason": "unavailable", "errors": []}
    try:
        src = code.encode("utf-8", "replace")
        tree = parser.parse(src)
        errors: list = []
        _collect_errors(tree.root_node, src, errors)
        return {"ok": not errors, "lang": lang,
                "reason": "clean" if not errors else "syntax_errors",
                "errors": errors}
    except Exception as exc:  # noqa: BLE001 - jamais bloquer sur un crash parser
        return {"ok": True, "lang": lang, "reason": f"parse_skip: {exc}", "errors": []}


def validate_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            code = fh.read()
    except OSError as exc:
        return {"ok": True, "lang": None, "reason": f"read_skip: {exc}", "errors": []}
    r = validate(code, path=path)
    r["path"] = path
    return r


def main() -> int:
    paths = sys.argv[1:]
    if not paths:
        print("usage: forge_treesitter_validate.py <fichier> [...]")
        return 1
    bad = 0
    for p in paths:
        r = validate_file(p)
        tag = "OK " if r["ok"] else "BAD"
        print(f"[{tag}] {p} lang={r['lang']} reason={r['reason']}")
        for e in r["errors"]:
            print(f"    {e['kind']} L{e['line']}:{e['col']}  {e['snippet']}")
        if not r["ok"]:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
