"""
generate_stub.py — Génère les signatures (squelette) d'un fichier Python.
Usage : python generate_stub.py <fichier.py>
        ou depuis Python : from tools.generate_stub import generate_stub
"""

__FORGE_COLOR__ = "qualite/quality : genere les signatures squelette d'un fichier Python"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import sys


def generate_stub(filepath: str) -> str:
    """Génère une version squelette d'un fichier Python (signatures uniquement)."""
    with open(filepath, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    stub_lines = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            stub_lines.append(f"class {node.name}:")
            for sub_node in node.body:
                if isinstance(sub_node, ast.FunctionDef):
                    args = ast.unparse(sub_node.args)
                    stub_lines.append(f"    def {sub_node.name}({args}): ...")

        elif isinstance(node, ast.FunctionDef):
            args = ast.unparse(node.args)
            stub_lines.append(f"def {node.name}({args}): ...")

    return "\n".join(stub_lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python generate_stub.py <fichier.py>")
        sys.exit(1)
    print(generate_stub(sys.argv[1]))
