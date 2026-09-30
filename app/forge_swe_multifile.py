"""forge_swe_multifile.py — SWE-bench Phase 2 : multi-fichiers via repomap + AST.

Source roadmap_swebench_improvements Phase 2 : "multi-fichiers via repomap-PAS-RAG-dense".

Pattern :
1. RepoMap : index symboles via tree-sitter (ou ast Python) -> graph
2. Pour un patch impactant func F : trouve callers + callees via graph
3. Inclut leur contexte dans prompt LLM
4. LLM gen patch spanning multi-files
5. Applique AST-level a chaque fichier via forge_swe_ast_whole_func.apply_ast_replacement

API :
- build_repomap(repo_path) -> {file: [{symbol, kind, callers, callees}]}
- find_impact(repo_map, target_func) -> {direct_files, related_files}
- generate_multifile_patch(repo_path, problem, target_func) -> {patches: [...]}
"""

from __future__ import annotations
import ast, json, logging, sys
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("swe_multifile")

ROOT = Path(__file__).resolve().parent.parent


def _extract_symbols_from_file(file_path: Path) -> dict:
    """Extract Python AST symbols (func/class def + calls) from file."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return {"functions": [], "classes": [], "calls": [], "imports": []}

    functions = []
    classes = []
    calls = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "decorators": [ast.unparse(d) for d in node.decorator_list][:3],
                }
            )
        elif isinstance(node, ast.ClassDef):
            classes.append({"name": node.name, "line": node.lineno})
        elif isinstance(node, ast.Call):
            try:
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
            except Exception:
                pass
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(f"{mod}.{alias.name}")

    return {
        "functions": functions,
        "classes": classes,
        "calls": list(set(calls))[:50],
        "imports": list(set(imports))[:30],
    }


def build_repomap(repo_path: Path, include_glob: str = "**/*.py", max_files: int = 500) -> dict:
    """Build symbol index of repository."""
    if not repo_path.exists():
        return {"error": "repo not found"}

    repomap = {}
    for fp in repo_path.glob(include_glob):
        if not fp.is_file():
            continue
        rel = str(fp.relative_to(repo_path))
        if any(p in rel for p in (".git", "__pycache__", ".pytest_cache", "node_modules", "venv", ".venv")):
            continue
        repomap[rel] = _extract_symbols_from_file(fp)
        if len(repomap) >= max_files:
            break
    return repomap


def find_impact(repomap: dict, target_func: str, max_related: int = 10) -> dict:
    """Find files containing target_func definition + files calling it."""
    direct_files = []
    caller_files = []

    for fpath, info in repomap.items():
        if isinstance(info, dict) and "error" in info:
            continue
        # Direct : file contains the target function definition
        for func in info.get("functions", []):
            if func.get("name") == target_func:
                direct_files.append({"file": fpath, "line": func.get("line")})
        # Callers : file calls target_func
        if target_func in info.get("calls", []):
            caller_files.append(fpath)

    return {
        "direct_files": direct_files[:max_related],
        "caller_files": caller_files[:max_related],
        "total_callers": len(caller_files),
    }


def generate_multifile_patch(repo_path: Path, problem: str, target_func: str, max_files_to_patch: int = 3) -> dict:
    """End-to-end multi-file patch generation.

    1. Build repomap
    2. Find impact (direct + callers)
    3. For each impacted file, request LLM patch via cascade
    4. Validate AST + propose application
    """
    repomap = build_repomap(repo_path)
    if "error" in repomap:
        return repomap

    impact = find_impact(repomap, target_func)
    if not impact["direct_files"]:
        return {"error": f"function '{target_func}' not found in repo"}

    # Gather context from related files
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_swe_ast_whole_func import generate_function_replacement, apply_ast_replacement
    except Exception as e:
        return {"error": f"forge_swe_ast_whole_func unavailable: {e}"}

    patches = []
    files_to_patch = (
        [d["file"] for d in impact["direct_files"]]
        + impact["caller_files"][: max_files_to_patch - len(impact["direct_files"])]
    )[:max_files_to_patch]

    # Build context summary
    ctx_summary = f"Caller files: {impact['caller_files'][:5]}\n"
    ctx_summary += f"Direct files: {[d['file'] for d in impact['direct_files']]}"

    for rel_path in files_to_patch:
        fpath = repo_path / rel_path
        # For each file : ask LLM to patch the relevant function
        # Heuristic: use target_func name (assumed shared accross files for simplicity)
        result = generate_function_replacement(fpath, target_func, problem, ctx_summary)
        result["file"] = rel_path
        patches.append(result)

    return {
        "target_func": target_func,
        "impact": impact,
        "patches": patches,
        "n_patches_generated": len([p for p in patches if p.get("ast_valid")]),
    }


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("repo_path", type=str)
    ap.add_argument("--func", type=str, required=True, help="Target function name")
    ap.add_argument("--problem", type=str, required=True)
    ap.add_argument("--build-map-only", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo_path)
    if args.build_map_only:
        repomap = build_repomap(repo)
        print(
            json.dumps(
                {
                    "n_files": len(repomap),
                    "sample": dict(list(repomap.items())[:3]),
                },
                indent=2,
                default=str,
            )
        )
        return

    result = generate_multifile_patch(repo, args.problem, args.func)
    print(json.dumps({k: v for k, v in result.items() if k != "patches"}, indent=2, default=str))
    print(f"\n{len(result.get('patches', []))} patches generated")


if __name__ == "__main__":
    main()
