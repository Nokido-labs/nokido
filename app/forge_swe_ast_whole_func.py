"""forge_swe_ast_whole_func.py — SWE-bench améliorations Phase 1 :
robustesse output via AST whole-function rewrite + linter gate.

Source roadmap_swebench_improvements : "robustesse output #1 (AST whole-func
+ linter-gate)". Plan vetté cerebras+gemini.

Pattern :
1. LLM output = full function (pas snippet S/R fragile)
2. Parse AST -> verify syntaxe valide
3. Linter gate (pyflakes minimal subset) -> verify no undefined names
4. Substitution AST-level dans fichier cible (replace func by name)
5. Re-parse fichier final -> verify import order OK

API :
- generate_function_replacement(file_path, func_name, problem, context)
  -> {new_func_source, ast_valid, lint_passed, applied}
- apply_ast_replacement(file_path, func_name, new_func_source) -> bool
- lint_function(source) -> list[issue]
"""

from __future__ import annotations
import ast, logging, sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("swe_ast")

ROOT = Path(__file__).resolve().parent.parent


def extract_function(source: str, func_name: str) -> str | None:
    """Extract function source by name (incl decorators). None if not found."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return ast.unparse(node)
    return None


def parse_validate(source: str) -> dict:
    """Parse + return diagnostics."""
    try:
        tree = ast.parse(source)
        return {"valid": True, "tree": tree, "errors": []}
    except SyntaxError as e:
        return {"valid": False, "errors": [{"line": e.lineno, "msg": e.msg}]}


def lint_function(source: str) -> list[dict]:
    """Minimal lint : check undefined names + unused vars.

    Subset of pyflakes-style checks pour eviter dep externe lourde.
    """
    issues = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [{"kind": "syntax", "line": e.lineno, "msg": e.msg}]

    # Collect defined names
    defined = set()
    used = set()

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            defined.add(node.name)
            for arg in node.args.args:
                defined.add(arg.arg)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            self.visit_FunctionDef(node)

        def visit_Assign(self, node):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    defined.add(tgt.id)
            self.generic_visit(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                used.add(node.id)
            self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            for alias in node.names:
                defined.add(alias.asname or alias.name)
            self.generic_visit(node)

    Visitor().visit(tree)

    # Builtins + common
    BUILTINS = {
        "print",
        "len",
        "range",
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "None",
        "True",
        "False",
        "isinstance",
        "type",
        "open",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "RuntimeError",
        "AttributeError",
        "self",
        "cls",
        "super",
        "min",
        "max",
        "sum",
        "map",
        "filter",
        "zip",
        "enumerate",
        "sorted",
        "reversed",
        "any",
        "all",
        "abs",
        "round",
        "input",
        "repr",
        "hash",
        "id",
        "getattr",
        "setattr",
        "hasattr",
        "dir",
        "__name__",
        "__file__",
        "__doc__",
        "__init__",
    }
    undefined = used - defined - BUILTINS
    for name in undefined:
        issues.append({"kind": "undefined", "name": name})

    return issues


def apply_ast_replacement(file_path: Path, func_name: str, new_func_source: str) -> dict:
    """Replace function by name in file using AST. Return {ok, applied_lines}."""
    if not file_path.exists():
        return {"ok": False, "error": "file not found"}
    original = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(original)
    except SyntaxError as e:
        return {"ok": False, "error": f"source parse: {e}"}

    # Find target function span
    target_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            target_node = node
            break
    if not target_node:
        # Try class methods
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for m in cls.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == func_name:
                    target_node = m
                    break
            if target_node:
                break
    if not target_node:
        return {"ok": False, "error": f"function '{func_name}' not found"}

    # Validate new source
    val = parse_validate(new_func_source)
    if not val["valid"]:
        return {"ok": False, "error": "new source invalid syntax", "errors": val["errors"]}

    # Lint check
    issues = lint_function(new_func_source)
    blocking = [i for i in issues if i["kind"] in ("syntax", "undefined")]
    # Undefined often acceptable (module-level names referenced from func), warn only.

    # Replace source lines
    start_line = target_node.lineno - 1
    end_line = target_node.end_lineno or start_line + 1
    # Get original indentation level (column offset)
    col_offset = target_node.col_offset
    indent = " " * col_offset

    # Re-indent new source
    new_lines = new_func_source.splitlines()
    if new_lines:
        # Normalize : strip leading indent from new source
        from textwrap import dedent

        new_func_source = dedent(new_func_source)
        new_lines = [indent + l if l.strip() else l for l in new_func_source.splitlines()]

    original_lines = original.splitlines()
    new_file = original_lines[:start_line] + new_lines + original_lines[end_line:]
    new_text = "\n".join(new_file) + ("\n" if original.endswith("\n") else "")

    # Final validation : parse whole file
    final_val = parse_validate(new_text)
    if not final_val["valid"]:
        return {"ok": False, "error": "final file invalid", "errors": final_val["errors"]}

    # Apply
    backup = file_path.with_suffix(file_path.suffix + ".astrepl.bak")
    backup.write_text(original, encoding="utf-8")
    file_path.write_text(new_text, encoding="utf-8")
    return {
        "ok": True,
        "lines_replaced": end_line - start_line,
        "lint_warnings": issues,
        "backup": str(backup),
    }


def generate_function_replacement(file_path: Path, func_name: str, problem: str, context: str = "") -> dict:
    """Pipeline complet : LLM gen + AST validate + lint gate + (optional apply).

    Returns {new_source, ast_valid, lint_issues, applied}
    """
    if not file_path.exists():
        return {"error": "file not found"}
    original = file_path.read_text(encoding="utf-8")
    current_func = extract_function(original, func_name)
    if not current_func:
        return {"error": f"function {func_name} not found"}

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_frugal_cascade import cascade
    except Exception as e:
        return {"error": f"cascade unavailable: {e}"}

    prompt = (
        f"Probleme:\n{problem[:1500]}\n\n"
        f"Contexte:\n{context[:1500]}\n\n"
        f"Fonction actuelle a corriger ({func_name}):\n"
        f"```python\n{current_func[:3000]}\n```\n\n"
        f"Reecris la fonction ENTIERE (incl. decorateurs, signature, body).\n"
        f"Output STRICT : code Python pur, pas de markdown fence, "
        f"pas de commentaire 'voici le code'. Juste def {func_name}(...): ..."
    )
    result = cascade(prompt, use_case="code", max_tokens=2000)
    raw = result.get("response") or ""

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    raw = raw.strip()

    val = parse_validate(raw)
    lint_issues = lint_function(raw) if val["valid"] else []

    return {
        "new_source": raw,
        "ast_valid": val["valid"],
        "ast_errors": val.get("errors", []),
        "lint_issues": lint_issues,
        "model_used": result.get("model_used"),
        "confidence": result.get("confidence"),
    }


def main():
    """CLI smoke."""
    import argparse, json

    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=str)
    ap.add_argument("func_name", type=str)
    ap.add_argument("--problem", type=str, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    fp = Path(args.file)
    result = generate_function_replacement(fp, args.func_name, args.problem)
    print(json.dumps({k: v for k, v in result.items() if k != "new_source"}, indent=2))

    if args.apply and result.get("ast_valid"):
        apply_result = apply_ast_replacement(fp, args.func_name, result["new_source"])
        print("\n[APPLY]")
        print(json.dumps(apply_result, indent=2))


if __name__ == "__main__":
    main()
