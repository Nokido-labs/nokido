"""NR 28/10 (job_22f3db0c) : un pointer_ref qui ne designe AUCUN artefact n'exempte plus `_non_livre`.

OPENCODE_DEFAUT2 (quota epuise, repli) a rendu OK_DONE en DECLARANT avoir cree 4 fichiers ; le worktree n'en
contenait aucun (0 commit, seul le marqueur de l'executeur non committe). Son `pointer_ref` valait
« forge_introspect_performance_plan » : un mot nu, que `_artefact_declare_absent` ne juge pas, et dont la
seule presence suffisait a sauter le verdict NON LIVRE. Un `tasks.db:` ne designe pas non plus un livrable.
Un chemin, un sha ou un pointeur d'un AUTRE registre (bb:, rag:, URL) garde l'exemption : il est juge ailleurs.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_task_executor as TE  # noqa: E402

EFFET = "[effet observe] commits produits : 0 (43d1a91a1..43d1a91a1) ; fichiers non commites : 1"


def _rep(ptr):
    return 'travail fait.\n{"intent": "OK_DONE", "pointer_ref": "%s"}' % ptr


def test_mot_nu_n_exempte_pas():
    assert TE._non_livre(EFFET, _rep("forge_introspect_performance_plan"))


def test_tasks_db_n_exempte_pas():
    assert TE._non_livre(EFFET, _rep("tasks.db:job_22f3db0c_1793204410_claude_task_assign"))


def test_autre_registre_garde_l_exemption():
    assert TE._non_livre(EFFET, _rep("bb:architecture_rules/P1_x")) is None
    assert TE._non_livre(EFFET, _rep("https://example.org/rapport")) is None


def test_chemin_ou_sha_garde_l_exemption():
    assert TE._non_livre(EFFET, _rep("docs/enquetes/rapport.md")) is None
    assert TE._non_livre(EFFET, _rep("agent/opencode@5b1072e16")) is None


def test_sans_pointeur_inchange():
    assert TE._non_livre(EFFET, "travail fait, rien a pointer")
