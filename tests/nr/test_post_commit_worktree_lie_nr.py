"""NR étape 3 (owner 9/11 : « chaque surface ne dérive pas » + entonnoir vers alpha).

Mesure du 9/11 : core.hooksPath=.githooks est RELATIF -> dans un worktree de tâche, git exécute la copie du hook du
worktree, qui lance depuis le worktree l'indexation RAG (forge_post_commit), le SSoT (forge_ssot_maintainer, journal
verrouillé dans opencode_glm_e98ab2cf9e04/logs) et l'oplog des corrections : un travail NON relu, hors alpha, entrait
dans la mémoire comme s'il faisait foi. Contrat : dans un worktree LIÉ, le post-commit ne lance ni indexation, ni
SSoT, ni oplog (il le DIT) ; l'arbre principal, lui, continue.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".githooks" / "post-commit"
FAUX_INDEXEUR = (
    "import os\n"
    "open(os.path.join(os.getcwd(), 'TEMOIN_INDEXATION'), 'w').write('x')\n"
)


def _git(c, *a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(c), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def _commit(c, nom):
    (c / nom).write_text(nom, encoding="utf-8")
    _git(c, "add", nom)
    return _git(c, "-c", "user.name=nr", "-c", "user.email=nr@x", "commit", "-m", nom)


def test_worktree_lie_ne_lance_pas_l_indexation(tmp_path):
    _scenario(tmp_path / "depot")


def test_chemins_avec_espaces(tmp_path):  # pylint: disable=unused-argument
    """9/11 : le vrai depot vit sous « Script python IA » ; un split() sur les espaces rendait la nature du
    worktree ILLISIBLE. L'arbre principal doit indexer, le worktree lie non, et sans « ILLISIBLE ».

    10/11 (pre-vol job_485594937c49) : sous la CI, `tmp_path` est profond (artefacts/ci_<compte>/...) et le
    gitdir du worktree depassait la limite de git -- `fatal: '$GIT_DIR' too big` -> ILLISIBLE, alors que le test
    passait seul. Base COURTE du temp systeme : on teste les espaces, pas la longueur du bac de CI."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="nk_"))
    try:
        depot = base / "Script python IA" / "depot"
        assert len(str(depot / ".git" / "worktrees" / "wt_tache")) < 160, "base encore trop longue : %s" % base
        _scenario(depot, espaces=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _scenario(depot, espaces=False):
    tmp_path = depot.parent
    depot.mkdir(parents=True)
    _git(depot, "init", "-b", "alpha")
    (depot / ".githooks").mkdir()
    shutil.copy(HOOK, depot / ".githooks" / "post-commit")
    (depot / "tools").mkdir()
    (depot / "tools" / "forge_post_commit.py").write_text(FAUX_INDEXEUR, encoding="utf-8")
    _git(depot, "config", "core.hooksPath", ".githooks")
    _git(depot, "add", "-A")
    _git(depot, "-c", "user.name=nr", "-c", "user.email=nr@x", "commit", "-m", "init")
    import time
    for _ in range(40):
        if (depot / "TEMOIN_INDEXATION").exists():
            break
        time.sleep(0.25)
    if not (depot / "TEMOIN_INDEXATION").exists():
        pytest.skip("hook non execute ici (python absent du PATH de git ?) : rien de prouve -- ILLISIBLE, pas NON")
    wt = tmp_path / "wt_tache"
    _git(depot, "worktree", "add", "-b", "tache/x", str(wt))
    r = _commit(wt, "livraison.txt")
    time.sleep(3)
    assert not (wt / "TEMOIN_INDEXATION").exists(), "indexation lancee depuis un worktree de tache"
    assert "worktree" in (r.stderr or "").lower(), "le hook doit DIRE qu'il saute l'indexation (stderr)"
    if espaces:
        assert "ILLISIBLE" not in (r.stderr or ""), r.stderr
