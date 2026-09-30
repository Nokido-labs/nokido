"""forge_anchor_swebench.py — Ancre le fix localisation SWE-bench dans Nokido.

Run : run action=trusted_script path=tools/forge_anchor_swebench.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nokido_agent.app.forge_self_correction import anchor_solution  # noqa: E402


def main() -> None:
    anchor_solution(
        problem="SWE-bench : la localisation des fichiers a editer etait cassee "
        "a la racine. _find_relevant_files faisait RAGEngine() = corpus "
        "Nokido (embeddings.db) -> cherchait un bug astropy/pylint dans "
        "le code de Nokido, renvoyait des forge_*.py hors-sujet. Le "
        "Coder recevait les mauvais fichiers. Cause majeure du 10/50.",
        solution="forge_swebench_runner._find_relevant_files reecrit : recherche "
        "lexicale BM25-lite du problem_statement contre les .py du REPO "
        "DE L'INSTANCE (repo_path.rglob). Score = termes presents + "
        "bonus frequence + bonus fort si match dans le chemin. Skip "
        "tests/build/docs. Commit df9394c1.",
        example="for p in repo_path.rglob('*.py'): score termes vs problem_statement",
        domain="swebench",
    )
    print("[anchor] fix localisation SWE-bench ancre")


if __name__ == "__main__":
    main()
