"""NR -- « livrable juge sur le commit » NOMME un livrable : la consigne ne peut plus etre jugee en lecture seule.

Vecu 26/10 (job_d0021c97, methode C) : la consigne finissait par « Livrable juge sur le commit » ; `_RE_LIVRABLE_NOMME`
ne reconnaissait que « committe » ou « livrable : X », et une contrainte de conception l'a fait passer pour une tache
en lecture seule -> OK_DONE a 0 commit.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402


def test_livrable_juge_sur_le_commit_est_nomme():
    for d in ("Regles : ... Livrable juge sur le commit.", "livrable jugé sur le commit", "Livrable : le commit"):
        assert te._RE_LIVRABLE_NOMME.search(d), d


def test_une_simple_mention_de_commit_ne_nomme_rien():
    assert not te._RE_LIVRABLE_NOMME.search("lis le dernier commit et resume-le")
