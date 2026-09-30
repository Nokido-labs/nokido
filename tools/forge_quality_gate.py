#!/usr/bin/env python
"""tools/forge_quality_gate.py — Quality check statique d'un fichier Python."""

import ast
import re
from pathlib import Path


def quality_check(file_path: str) -> dict:
    """Retourne {ok: bool, score: float 0-1, issues: list[str]}."""
    issues: list[str] = []
    score = 0.0
    content = Path(file_path).read_text("utf-8", errors="replace")
    lines = content.splitlines()

    # +0.3 syntaxe AST OK
    try:
        tree = ast.parse(content, filename=file_path)
        score += 0.3
    except SyntaxError as e:
        issues.append(f"SyntaxError: {e}")
        return {"ok": False, "score": round(score, 2), "issues": issues}

    # +0.2 docstrings dans >50% fonctions publiques
    pub_funcs = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    ]
    if pub_funcs:
        with_doc = sum(
            1
            for f in pub_funcs
            if f.body
            and isinstance(f.body[0], ast.Expr)
            and isinstance(f.body[0].value, ast.Constant)
            and isinstance(f.body[0].value.value, str)
        )
        if with_doc / len(pub_funcs) >= 0.5:
            score += 0.2
        else:
            issues.append(
                f"docstrings manquantes ({with_doc}/{len(pub_funcs)} fonctions publiques)"
            )
    else:
        score += 0.2  # pas de fonctions publiques = pas de pénalité

    # -0.1 par TODO/FIXME (max 3)
    todo_count = sum(1 for l in lines if re.search(r"\b(TODO|FIXME)\b", l, re.IGNORECASE))
    penalty = min(todo_count, 3) * 0.1
    if penalty:
        score -= penalty
        issues.append(f"{todo_count} TODO/FIXME (-{penalty:.1f})")

    # +0.2 fichier < 300 lignes
    if len(lines) < 300:
        score += 0.2
    else:
        issues.append(f"fichier long ({len(lines)} lignes, seuil 300)")

    # +0.2 pas de bare except
    bare = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.type is None]
    if not bare:
        score += 0.2
    else:
        issues.append(f"{len(bare)} bare except (sans type)")

    score = max(0.0, min(round(score, 2), 1.0))
    return {"ok": score >= 0.6, "score": score, "issues": issues}


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    import json

    print(json.dumps(quality_check(target), indent=2, ensure_ascii=False))
