"""NR -- « ne cree pas de systeme parallele » est une CONTRAINTE de conception, pas une consigne en lecture seule.

Vecu 26/10 : la consigne de la methode C (OPENCODE_GPTOSS, job_d0021c97) disait « etends, ne cree pas de systeme
parallele » ; `_RE_LECTURE_SEULE` acceptait `ne cree pas`, le juge a classe la tache en lecture seule, l'a jugee sur
son rapport et a rendu OK_DONE avec 0 commit. Les vraies formes de lecture seule restent exemptees.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402


def test_une_contrainte_de_conception_n_exempte_pas():
    assert not te._lecture_seule("Reutilise l'existant : etends, ne cree pas de systeme parallele. NR d'abord.")
    assert not te._lecture_seule("ne modifie pas le schema public ; ajoute le test")


def test_les_vraies_lectures_seules_restent_exemptees():
    for d in ("Enquete en lecture seule.", "read-only audit", "ne modifie aucun code",
              "ne cree rien", "sans rien modifier"):
        assert te._lecture_seule(d), d
