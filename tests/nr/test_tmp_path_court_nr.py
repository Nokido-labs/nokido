"""NR -- le dossier d'un tmp_path ne depasse pas la longueur du tmp_path par defaut de pytest (31 caracteres).

Mesure 20/10 (CI de reference job_8cc3cf7572d2 sur 477e02f93, 13 echecs + 5 erreurs) : `fatal: '$GIT_DIR' too big`.
Le worktree de reference est profond (sandbox/workspace/tmp/nokido_proof/ci-reference-<id>/artefacts/<compte>/bt/
popen-gwN, ~150 car.) et la fixture tmp_path O(1) (0b3c5da24, 537a769e5) ajoutait un lot `pytest_tXX/` et un suffixe
aleatoire : ~51 caracteres par test contre ~31 pour le defaut. Les tests git (worktrees, preuve, rebase) passaient
MAX_PATH. La reference e6642dcf1, sur le defaut, ne les avait pas.
"""
from __future__ import annotations


def test_le_dossier_du_test_reste_court(tmp_path, tmp_path_factory):
    rel = tmp_path.relative_to(tmp_path_factory.getbasetemp())
    assert len(str(rel)) <= 31, (len(str(rel)), str(rel))
