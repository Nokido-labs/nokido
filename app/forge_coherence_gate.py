"""forge_coherence_gate.py — Vérifie l'impact cross-fichiers avant d'écrire du code.

Usage:
    from forge_coherence_gate import coherence_gate
    result = await coherence_gate("app/forge_llm_router.py", new_code)
"""

from __future__ import annotations
import ast
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def coherence_gate(
    file_path: str,
    new_code: str,
    hub_dispatch_fn=None,
) -> dict[str, Any]:
    """AST-parse new_code, trouve les fichiers impactés via GraphLinker.

    Returns: {"ok": bool, "impacted_files": [...], "warnings": [...]}
    """
    warnings: list[str] = []
    impacted: set[str] = set()

    # 1. Extraire noms modifiés via AST
    modified_names: list[str] = []
    try:
        tree = ast.parse(new_code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                modified_names.append(node.name)
    except SyntaxError as e:
        return {"ok": False, "impacted_files": [], "warnings": [f"SyntaxError: {e}"]}

    # 2. Chercher fichiers impactés via GraphLinker
    try:
        from nokido_agent.app.forge_graph_linker import GraphLinker

        linker = GraphLinker()

        # Impact du fichier modifié lui-même
        for hit in linker.get_impacted_by_change(file_path):
            src = hit.get("source", "")
            if src:
                impacted.add(src)

        # Vérifier que les fichiers impactés compilent toujours
        for src in impacted:
            full = ROOT / src
            if full.exists():
                try:
                    ast.parse(full.read_text("utf-8", errors="replace"))
                except SyntaxError:
                    warnings.append(f"SyntaxError in impacted file: {src}")
    except Exception as e:
        warnings.append(f"GraphLinker unavailable: {e}")

    return {
        "ok": len(warnings) == 0,
        "modified_names": modified_names,
        "impacted_files": sorted(impacted),
        "warnings": warnings,
    }


if __name__ == "__main__":
    import asyncio

    sample = "def my_func():\n    pass\n"
    print(asyncio.run(coherence_gate("app/forge_llm_router_dt.py", sample)))
