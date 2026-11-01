"""L'executeur ne laisse plus un fichier transitoire faire refuser le commit d'un agent (24/10).

CE QUI A ETE PAYE. `nokido.lock` (verrou transitoire de worktree), INDEXE par une tache precedente, partait dans
chaque commit de l'executant claude_headless : le gate « transitoires » a refuse 5 livraisons dans la journee, et
l'agent n'a pas le droit de `git restore --staged`. Contrat, sur le chemin reel `_committer_pour_agent` (depot git
temporaire, aucun hook) : le livrable est committe, le transitoire n'y est pas, et il reste sur le disque.
"""
import os
import subprocess
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_task_executor as T  # noqa: E402


def _git(wt, *a):
    return subprocess.run(["git", "-C", str(wt), *a], check=True, capture_output=True, text=True).stdout


def test_transitoire_deja_indexe_ne_part_pas_dans_le_commit(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "a@b.c")
    _git(wt, "config", "user.name", "t")
    (wt / "a.txt").write_text("x", encoding="utf-8")
    _git(wt, "add", "a.txt")
    _git(wt, "commit", "-qm", "init")
    (wt / "nokido.lock").write_text("verrou", encoding="utf-8")
    _git(wt, "add", "nokido.lock")  # indexe par une tache precedente
    (wt / "livrable.py").write_text("X = 1\n", encoding="utf-8")
    note = T._committer_pour_agent(str(wt), "job_t", '{"intent":"OK_DONE","commit_message":"feat: livrable"}',
                                   "CLAUDE_HEADLESS")
    assert note and "REFUSE" not in note and "ECHOUE" not in note, note
    fichiers = _git(wt, "show", "--name-only", "--format=", "HEAD").split()
    assert "livrable.py" in fichiers, fichiers
    assert "nokido.lock" not in fichiers, fichiers
    assert (wt / "nokido.lock").exists(), "le transitoire a ete supprime du disque"
