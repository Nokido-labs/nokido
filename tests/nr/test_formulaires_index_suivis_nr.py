"""NR 9/11 (revue globale, lot 1) : 6 formulaires du web hub étaient listés dans __index__.json mais NON SUIVIS
par git depuis le 11/09 -- perdus au premier clone ou nettoyage. Toute entrée de l'index a son fichier suivi."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "app" / "web_hub" / "forms"


def test_chaque_entree_de_l_index_a_son_formulaire_suivi():
    index = json.loads((FORMS / "__index__.json").read_text(encoding="utf-8"))
    suivis = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "app/web_hub/forms"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.split()
    if not suivis:
        import pytest
        pytest.skip("git ls-files illisible ici : rien de prouvé (ILLISIBLE, pas NON)")
    manquants = [s for s in index if "app/web_hub/forms/%s_form.py" % s not in suivis]
    assert not manquants, "formulaires indexés mais non suivis : %s" % manquants
