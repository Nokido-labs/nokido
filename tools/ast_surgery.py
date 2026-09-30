"""
tools/ast_surgery.py — Injection chirurgicale de type hints via AST
====================================================================
Au lieu de demander au LLM de réécrire tout le fichier (troncation),
on extrait les signatures sans corps, on envoie au LLM, et on fusionne
les annotations dans le fichier original.

Garde-fous :
- Compte les classes avant/après — si delta > 0, rejet
- Valide AST après chaque injection
- Backup automatique avant toute modification

Usage :
  python tools/ast_surgery.py app/forge_core_models.py
  python tools/ast_surgery.py app/forge_core_models.py --dry-run
"""

from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : injection chirurgicale de type hints via AST"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def extract_signatures(src: str) -> str:
    """Extrait uniquement les signatures def/class sans corps."""
    tree = ast.parse(src)
    lines = src.splitlines()
    sigs = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Ligne de déclaration + décorateurs
            start = node.lineno - 1
            while start > 0 and lines[start - 1].strip().startswith("@"):
                start -= 1
            sigs.append(lines[start])  # class Foo(Base):

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Signature complète (peut être multi-ligne)
            sig_lines = []
            for i in range(node.lineno - 1, min(node.lineno + 5, len(lines))):
                sig_lines.append(lines[i])
                if lines[i].rstrip().endswith(":"):
                    break
            sigs.append(" ".join(l.strip() for l in sig_lines))

    return "\n".join(sigs)


def count_nodes(src: str) -> dict:
    """Compte les nœuds structuraux — garde-fou anti-troncation."""
    try:
        tree = ast.parse(src)
        return {
            "classes": len([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]),
            "functions": len(
                [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
            ),
            "lines": src.count("\n"),
        }
    except SyntaxError:
        return {"classes": -1, "functions": -1, "lines": -1}


def merge_annotations(original: str, annotated_sigs: str) -> str:
    """
    Fusionne les annotations du LLM dans le fichier original.
    Stratégie : parse les signatures annotées, injecte dans l'AST original.
    """
    orig_lines = original.splitlines(keepends=True)
    orig_tree = ast.parse(original)

    # Parse les signatures annotées
    try:
        ann_tree = ast.parse(annotated_sigs)
    except SyntaxError:
        return original  # LLM a produit quelque chose d'invalide

    # Mappe nom → annotations LLM
    ann_map: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(ann_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ann_map[node.name] = node

    changes = []  # (line_idx, old_line, new_line)

    for node in ast.walk(orig_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        ann = ann_map.get(node.name)
        if not ann:
            continue

        # Trouve la ligne de def dans l'original
        def_idx = node.lineno - 1
        old_line = orig_lines[def_idx]

        # Reconstruit la signature avec les nouvelles annotations
        try:
            new_sig = ast.unparse(ann)
            # Garde l'indentation d'origine
            indent = len(old_line) - len(old_line.lstrip())
            indent_str = " " * indent

            # Remplace seulement si -> manquant ou args non annotés
            needs_return = ann.returns and not node.returns
            needs_args = any(a.annotation for a in ann.args.args) and not any(
                a.annotation for a in node.args.args
            )

            if needs_return or needs_args:
                # Reconstruit la ligne def avec annotations
                new_line = indent_str + new_sig.split("\n")[0] + ":\n"
                changes.append((def_idx, old_line, new_line))
        except Exception:
            continue

    if not changes:
        return original

    # Applique du bas vers le haut
    result = list(orig_lines)
    for idx, old, new in sorted(changes, key=lambda x: -x[0]):
        if result[idx] == old:
            result[idx] = new

    new_src = "".join(result)

    # Valide AST
    try:
        ast.parse(new_src)
        return new_src
    except SyntaxError:
        return original  # rollback silencieux


def ast_surgery(filepath: str, dry_run: bool = False) -> dict:
    """
    Injecte les type hints chirurgicalement dans un fichier.
    Retourne un rapport de ce qui a changé.
    """
    f = Path(filepath)
    original = f.read_text(encoding="utf-8", errors="replace")
    orig_stats = count_nodes(original)

    # Extrait les signatures
    sigs = extract_signatures(original)
    print(f"\n[AST-SURGERY] {f.name}")
    print(
        f"  Classes: {orig_stats['classes']} | Fonctions: {orig_stats['functions']} | Lignes: {orig_stats['lines']}"
    )
    print(f"  Signatures extraites: {len(sigs.splitlines())}L")

    if dry_run:
        print("  [DRY-RUN] Signatures à envoyer au LLM:")
        for l in sigs.splitlines()[:10]:
            print(f"    {l}")
        return {"dry_run": True, "sigs": sigs}

    # Envoie au LLM
    try:
        from nokido_agent.app.forge_openrouter import generate_code

        prompt = (
            "Add Python 3.9+ type hints to these function signatures. "
            "Return ONLY the annotated signatures, one per line. "
            "Do NOT include function bodies. Do NOT add imports.\n\n" + sigs
        )
        annotated = generate_code(
            prompt,
            system="Return ONLY annotated function signatures. No bodies. No imports. No markdown.",
            max_tokens=2048,
        )
        print(f"  LLM réponse: {len(annotated)}c")
    except Exception as e:
        print(f"  LLM KO: {e}")
        return {"ok": False, "error": str(e)}

    # Fusionne
    merged = merge_annotations(original, annotated)
    merged_stats = count_nodes(merged)

    # Garde-fou : vérifie l'intégrité
    if merged_stats["classes"] < orig_stats["classes"]:
        print(
            f"  REJET — classes: {orig_stats['classes']} → {merged_stats['classes']} (perte détectée)"
        )
        return {"ok": False, "reason": "class_loss"}

    if merged_stats["lines"] < orig_stats["lines"] * 0.85:
        print(f"  REJET — troncation: {orig_stats['lines']}L → {merged_stats['lines']}L")
        return {"ok": False, "reason": "truncation"}

    if merged == original:
        print("  Aucun changement — fichier déjà typé ou LLM n'a rien ajouté")
        return {"ok": True, "changed": False}

    # Backup + écriture
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = f.parent / f"{f.stem}_surgery_bak_{ts}.py"
    shutil.copy(f, backup)

    if not dry_run:
        f.write_text(merged, encoding="utf-8")
        print(
            f"  ✅ Injecté — {orig_stats['lines']}L → {merged_stats['lines']}L | backup: {backup.name}"
        )

    return {
        "ok": True,
        "changed": True,
        "lines_before": orig_stats["lines"],
        "lines_after": merged_stats["lines"],
        "backup": str(backup),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="AST Surgery — injection type hints")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    results = {}
    for fpath in args.files:
        results[fpath] = ast_surgery(fpath, dry_run=args.dry_run)

    print(f"\nRésumé: {sum(1 for r in results.values() if r.get('ok'))} OK / {len(results)}")
