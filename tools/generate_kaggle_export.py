"""
generate_kaggle_export.py — Générateur kaggle_export.json v2
=============================================================
Scan AST de tout app/ et génère un export enrichi pour GraphCodeBERT.

Champs par fonction :
  name, args, returns, annots, lineno, body_len,
  class_name, docstring,          ← NOUVEAU v2 (détection ML)
  evolution_metrics (complexity_score, purity_rank, is_typed)

Champs par fichier :
  path, size, functions, classes, complexity,
  purity_rank, recommended_model

Usage :
  python tools/generate_kaggle_export.py
  → écrit kaggle_dataset/kaggle_export.json
  → copie dans docs/kaggle_export.json pour push GitHub

Puis push GitHub :
  git add docs/kaggle_export.json kaggle_dataset/kaggle_export.json
  git commit -m "feat: kaggle_export v2 — class_name + docstring"
  git push origin alpha
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : generateur kaggle_export.json v2 (scan AST)"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
OUT_DS = ROOT / "kaggle_dataset" / "kaggle_export.json"
OUT_DOC = ROOT / "docs" / "kaggle_export.json"

# Fichiers à ignorer
IGNORE_FILES = {"_tmp_lf.py", "Nokido_tmp.py"}
IGNORE_DIRS = {"__pycache__", ".venv", "venv", "backups", "legacy"}


# ── Calcul complexité cyclomatique simplifiée ─────────────────────────────────


def _cyclomatic(node: ast.AST) -> int:
    score = 1
    for n in ast.walk(node):
        if isinstance(
            n,
            (
                ast.If,
                ast.While,
                ast.For,
                ast.ExceptHandler,
                ast.With,
                ast.Assert,
                ast.comprehension,
            ),
        ):
            score += 1
        elif isinstance(n, ast.BoolOp):
            score += len(n.values) - 1
    return score


def _purity_rank(complexity: int, n_args: int, is_typed: bool) -> str:
    if complexity <= 2 and n_args <= 3 and is_typed:
        return "A"
    if complexity <= 4 and n_args <= 5:
        return "B"
    if complexity <= 7:
        return "C"
    return "D"


def _recommended_model(rank: str, file_complexity: float) -> str:
    if rank == "A":
        return "phi3-mini"
    if rank == "B":
        return "codebert-base"
    if rank == "C":
        return "graphcodebert-base"
    return "deepseek-coder-6.7b"


def _get_docstring(node: ast.AST) -> str:
    """Extrait la docstring d'une fonction ou classe."""
    try:
        doc = ast.get_docstring(node)
        return (doc or "")[:200]
    except Exception:
        return ""


# ── Scan d'un fichier Python ──────────────────────────────────────────────────


def scan_file(path: Path) -> dict | None:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return None
    except Exception:
        return None

    lines = src.splitlines()
    functions = []

    # Parcours top-level + méthodes de classes
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Classe parente (si méthode)
        class_name = None
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef):
                for child in ast.walk(parent):
                    if child is node:
                        class_name = parent.name
                        break
                if class_name:
                    break

        args = [a.arg for a in node.args.args]
        annots = {}
        for a in node.args.args:
            if a.annotation:
                try:
                    annots[a.arg] = ast.unparse(a.annotation)
                except Exception:
                    pass

        returns = ""
        if node.returns:
            try:
                returns = ast.unparse(node.returns)
            except Exception:
                pass

        is_typed = bool(returns or annots)
        body_len = (node.end_lineno or node.lineno) - node.lineno
        complexity = _cyclomatic(node)
        rank = _purity_rank(complexity, len(args), is_typed)
        docstring = _get_docstring(node)

        functions.append(
            {
                "name": node.name,
                "args": args,
                "returns": returns,
                "annots": annots,
                "lineno": node.lineno,
                "body_len": body_len,
                "class_name": class_name,  # None si top-level
                "docstring": docstring,  # "" si absente
                "evolution_metrics": {
                    "complexity_score": complexity,
                    "purity_rank": rank,
                    "is_typed": is_typed,
                },
            }
        )

    # Classes (noms uniquement pour référence)
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "docstring": _get_docstring(node)[:120],
                    "n_methods": sum(
                        1
                        for n in ast.walk(node)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ),
                }
            )

    # Complexité fichier = moyenne des fonctions
    complexities = [f["evolution_metrics"]["complexity_score"] for f in functions]
    file_complexity = round(sum(complexities) / len(complexities), 2) if complexities else 1.0

    # Rank fichier = pire rank parmi ses fonctions
    rank_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    ranks = [f["evolution_metrics"]["purity_rank"] for f in functions]
    file_rank = max(ranks, key=lambda r: rank_order.get(r, 0)) if ranks else "A"

    rel_path = str(path.relative_to(ROOT)).replace("\\", "/")

    return {
        "path": rel_path,
        "size": len(src),
        "functions": functions,
        "classes": classes,
        "complexity": file_complexity,
        "purity_rank": file_rank,
        "recommended_model": _recommended_model(file_rank, file_complexity),
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def generate(app_dir: Path = APP_DIR) -> dict:
    files_data = {}
    n_files = n_fns = n_skipped = 0

    py_files = sorted(
        f
        for f in app_dir.rglob("*.py")
        if f.name not in IGNORE_FILES and not any(d in f.parts for d in IGNORE_DIRS)
    )

    for py in py_files:
        result = scan_file(py)
        if result is None:
            n_skipped += 1
            continue
        key = result["path"].replace("app/", "")
        files_data[key] = result
        n_fns += len(result["functions"])
        n_files += 1

    export = {
        "_meta": {
            "version": "2.0",
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "n_files": n_files,
            "n_functions": n_fns,
            "n_skipped": n_skipped,
            "fields_v2": ["class_name", "docstring"],
        },
        "files": files_data,
    }
    return export


def main():
    print(f"Scan {APP_DIR} ...")
    t0 = time.time()
    export = generate()
    elapsed = round(time.time() - t0, 2)

    meta = export["_meta"]
    print(
        f"  {meta['n_files']} fichiers | {meta['n_functions']} fonctions | {meta['n_skipped']} ignorés | {elapsed}s"
    )

    # Écriture
    for out_path in [OUT_DS, OUT_DOC]:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8")
        size_mb = round(out_path.stat().st_size / 1024 / 1024, 2)
        print(f"  Écrit: {out_path.relative_to(ROOT)} ({size_mb} Mo)")

    print("Done — push avec:")
    print("  git add docs/kaggle_export.json kaggle_dataset/kaggle_export.json")
    print('  git commit -m "feat: kaggle_export v2 — class_name + docstring"')
    print("  git push origin alpha")


if __name__ == "__main__":
    main()
