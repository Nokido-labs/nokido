"""NR 18/10 -- regression introduite par bcc388fbf (exclusion des fichiers sales) puis MESUREE : deux ci_local tues au
plafond RSS de 6 Go dans test_la_delegation_ecrit_un_job_harness_vibe_borne. `_chemins_status(wt)` lance
`git status --porcelain=v1 -uall` ; quand `wt` n'est PAS la racine d'un worktree (dossier temporaire de test sous
sandbox/), git remonte jusqu'au depot Nokido et enumere TOUS ses fichiers non suivis -> sortie geante, 6 Go.

Contrat : hors de la racine d'un worktree (pas de `.git` fichier ou dossier dans `wt`), git n'est JAMAIS lance et
`_chemins_status` rend None (illisible : pas d'etat propre) ; a la racine d'un worktree, comportement inchange.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402


def test_hors_racine_de_worktree_git_n_est_jamais_lance(tmp_path, monkeypatch):
    appels = []
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: appels.append(a) or (_ for _ in ()).throw(
        AssertionError("git lance hors worktree")))
    assert te._chemins_status(str(tmp_path)) is None
    assert appels == [], "git status ne doit pas tourner dans un dossier qui n'est pas la racine d'un worktree"


def test_a_la_racine_d_un_worktree_git_est_lance(tmp_path, monkeypatch):
    (tmp_path / ".git").write_text("gitdir: ailleurs\n", encoding="utf-8")     # forme d'un worktree lie

    class _R:
        returncode, stdout = 0, " M a.py\n?? b.py\n"
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    assert te._chemins_status(str(tmp_path)) == frozenset({"a.py", "b.py"})
