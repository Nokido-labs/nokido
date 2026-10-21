"""NR -- tmp_path se cree en O(1), sans balayer tout le basetemp.

Mesure 19/10 (2 pre-controles --impacte tues, dont job_115ba556ef96 apres ~15 000 tests en 1477 s) : `Timeout` 30 s
dans `make_numbered_dir` -> `os.scandir(basetemp)`. Le tmp_path de pytest cherche le prochain numero en lisant TOUT le
basetemp, qui grossit d'un dossier par test : O(n) par test, O(n2) sur la suite pure jouee sans xdist, et sous
contention disque un seul balayage depassait 30 s -- la methode thread de pytest-timeout abattait alors toute la suite.
Le conftest cree chaque tmp_path par mkdtemp : aucun balayage. (20/10 : le lot de 256 a ete retire -- il allongeait les
chemins au-dela de MAX_PATH dans la CI de reference, cf. test_tmp_path_court_nr ; il n'a jamais ete la parade, mkdtemp
l'est.)
"""
from __future__ import annotations

import re
from pathlib import Path


def test_tmp_path_n_est_pas_numerote_par_pytest(tmp_path, tmp_path_factory):
    base = Path(tmp_path_factory.getbasetemp()).resolve()
    assert tmp_path.is_dir() and not any(tmp_path.iterdir())
    # make_numbered_dir (le balayage O(n)) nomme « <nom><N> » ; mkdtemp nomme « pytest<nom>_<8 aleatoires> »
    assert re.match(r"^pytest\w*_\w{8}$", tmp_path.name), tmp_path.name
    assert tmp_path.resolve().parent == base


def test_deux_tmp_path_sont_distincts(tmp_path, tmp_path_factory):
    autre = tmp_path_factory.getbasetemp() / "temoin_distinct"
    autre.mkdir(exist_ok=True)
    assert tmp_path != autre and tmp_path.exists()
