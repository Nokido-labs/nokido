import sys
from pathlib import Path

# Setup paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_commit_intel import CRITICAL_SYMBOLS
import ast


def analyze_file_structure(file_path):
    path = Path(file_path)
    if not path.exists():
        print(f"Error: {file_path} not found")
        return

    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    print(f"=== ANALYSE DE STRUCTURE : {path.name} ===")

    # 1. Extraction des symboles
    functions = []
    classes = []
    constants = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id.isupper():
                        constants.append(target.id)

    print(f"Classes   : {classes}")
    print(f"Functions : {functions}")
    print(f"Constants : {constants}")

    # 2. Vérification des symboles critiques
    criticals = [f for f in (functions + classes) if f in CRITICAL_SYMBOLS]
    print(f"Critical Symbols Found : {criticals}")

    # 3. Recherche de potentielles constantes orphelines
    # (Simple check : definies mais non utilisees dans le corps du fichier)
    content = path.read_text(encoding="utf-8")
    orphans = []
    for c in constants:
        if content.count(c) <= 1:  # Seulement la definition
            orphans.append(c)

    if orphans:
        print(f"Potential Orphan Constants : {orphans}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_file_structure(sys.argv[1])
    else:
        print("Usage: python forge_impact_agent.py <file_path>")
