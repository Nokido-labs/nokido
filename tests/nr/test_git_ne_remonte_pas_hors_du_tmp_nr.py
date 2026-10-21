"""NR -- un test qui lance git dans son tmp ne remonte JAMAIS jusqu'au depot Nokido.

Mesure 19/10 22:56 (CI de reference job_c0e9551e5d67) : des tests executeur lancent `git status --porcelain -uall`
dans `<basetemp>/.../wt`, dossier NON initialise ; le basetemp de la reference vit DANS l'arbre
(sandbox/workspace/tmp/nokido_proof/...) -> git remontait jusqu'a Nokido/.git : status -uall du depot entier et
`.git/index.lock` tenu en continu (commits refuses « index.lock: File exists »). Interrupteur global : conftest pose
GIT_CEILING_DIRECTORIES sur le basetemp, aucun git lance sous un tmp ne peut en sortir.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _git(cwd, *a, env=None):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(cwd), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def test_le_plafond_git_couvre_le_basetemp(tmp_path_factory):
    plafonds = [p for p in os.environ.get("GIT_CEILING_DIRECTORIES", "").split(os.pathsep) if p]
    base = Path(tmp_path_factory.getbasetemp()).resolve()
    assert any(base == Path(p).resolve() or base.is_relative_to(Path(p).resolve()) for p in plafonds), plafonds


def test_git_dans_un_tmp_non_depot_ne_trouve_aucun_depot(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    r = _git(wt, "rev-parse", "--show-toplevel")
    assert r.returncode != 0, r.stdout


def test_le_plafond_arrete_bien_la_remontee_sous_windows(tmp_path):
    exterieur = tmp_path / "exterieur"
    wt = exterieur / "plafond" / "wt"
    wt.mkdir(parents=True)
    assert _git(exterieur, "init", "-q").returncode == 0
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(exterieur / "plafond"))
    assert _git(wt, "rev-parse", "--show-toplevel", env=env).returncode != 0
