"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-06 | VER:v_forge_spec_formalizer_v1
#FORGE:[score:80|agent:claude-mcp|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Convertit spec BAML (texte) en stubs Python typés. Pas de dépendance baml_py.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import re
import textwrap
from typing import List, Dict, Any, Optional

# BAML type → Python type hint
_TYPE_MAP: Dict[str, str] = {
    "string": "str",
    "str": "str",
    "int": "int",
    "integer": "int",
    "float": "float",
    "double": "float",
    "bool": "bool",
    "boolean": "bool",
    "list": "list",
    "array": "list",
    "dict": "dict",
    "map": "dict",
    "any": "Any",
    "null": "None",
}


def _baml_type_to_python(t: str) -> str:
    t = t.strip()
    # Optional[X] -> Optional[X]
    if t.startswith("Optional[") or t.startswith("optional["):
        inner = re.match(r"[Oo]ptional\[(.+)\]$", t)
        if inner:
            return f"Optional[{_baml_type_to_python(inner.group(1))}]"
    # List[X] or list[X]
    m = re.match(r"[Ll]ist\[(.+)\]$", t)
    if m:
        return f"List[{_baml_type_to_python(m.group(1))}]"
    # Dict[K, V]
    m = re.match(r"[Dd]ict\[(.+),\s*(.+)\]$", t)
    if m:
        return f"Dict[{_baml_type_to_python(m.group(1))}, {_baml_type_to_python(m.group(2))}]"
    return _TYPE_MAP.get(t.lower(), t)


def _parse_params(params_str: str) -> List[tuple]:
    """Parse 'arg1: Type1, arg2: Type2' -> [(name, py_type), ...]"""
    if not params_str.strip():
        return []
    result = []
    for part in params_str.split(","):
        part = part.strip()
        if ":" in part:
            name, typ = part.split(":", 1)
            result.append((name.strip(), _baml_type_to_python(typ.strip())))
        elif part:
            result.append((part, "Any"))
    return result


def parse_baml_spec(spec: str) -> List[Dict[str, Any]]:
    """
    Parse BAML spec string. Returns list of function dicts:
      {name, params: [(name, type)], return_type, docstring}
    """
    funcs = []
    # Match: function Name(args) -> ReturnType { ... }
    pattern = re.compile(
        r"(?:///\s*(?P<doc>[^\n]+)\n\s*)?"
        r"function\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
        r"\s*->\s*(?P<ret>[^\s{]+)",
        re.MULTILINE,
    )
    for m in pattern.finditer(spec):
        funcs.append(
            {
                "name": m.group("name"),
                "params": _parse_params(m.group("params") or ""),
                "return_type": _baml_type_to_python(m.group("ret")),
                "docstring": (m.group("doc") or "").strip(),
            }
        )
    return funcs


def generate_stubs(spec: str, module_docstring: str = "") -> str:
    """
    Convert BAML spec string to Python stub file content.
    Functions have correct type hints, NotImplementedError body, and docstrings.
    """
    funcs = parse_baml_spec(spec)
    if not funcs:
        return "# No functions found in spec\n"

    needs_typing = any(
        "List[" in f["return_type"]
        or "Dict[" in f["return_type"]
        or "Optional[" in f["return_type"]
        or "Any" in f["return_type"]
        or any("List[" in t or "Dict[" in t or "Optional[" in t or "Any" in t for _, t in f["params"])
        for f in funcs
    )

    lines = ["from __future__ import annotations"]
    if needs_typing:
        lines.append("from typing import Any, Dict, List, Optional")
    if module_docstring:
        lines += ["", f'"""{module_docstring}"""']
    lines.append("")

    for f in funcs:
        # Build signature
        sig_params = ["self"] + [f"{n}: {t}" for n, t in f["params"]]
        sig = f"def {f['name']}({', '.join(sig_params)}) -> {f['return_type']}:"
        # Wrap long signature
        if len(sig) > 90:
            inner = ",\n        ".join(sig_params)
            sig = f"def {f['name']}(\n        {inner},\n    ) -> {f['return_type']}:"

        lines.append(f"    {sig}")
        if f["docstring"]:
            lines.append(f'        """{f["docstring"]}"""')
        lines.append("        raise NotImplementedError")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    spec_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not spec_text and len(sys.argv) > 1:
        spec_text = open(sys.argv[1]).read()
    print(generate_stubs(spec_text))
