"""NR -- une fusion n'est pas du travail produit, et une delegation sans commit propre n'est pas un SUCCESS.

2026-10-13 : AGY a fusionne alpha dans sa branche (1 commit de fusion apportant 1337 commits d'ailleurs), modifie
forge_session_context.py, puis s'est arrete sur 5 fichiers NON committes. Le drain a ecrit « commits produits :
1338 » et relaye SUCCESS. Du travail non committe dans un worktree n'est ni relisible par le hub ni fusionnable.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

SOURCE = Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py"


def _mod():
    spec = importlib.util.spec_from_file_location("task_exec_nr_fusion", SOURCE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _git(d, *args):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=nr", "-c", "user.email=nr@x",
                    "-C", str(d), *args], check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", env=env)


def _commit(d, nom):
    (d / nom).write_text(nom, encoding="utf-8")
    _git(d, "add", nom)
    _git(d, "commit", "-q", "-m", nom)


def test_une_fusion_n_est_pas_du_travail_produit(tmp_path):
    m = _mod()
    _git(tmp_path, "init", "-q", "-b", "travail")
    _commit(tmp_path, "base.txt")
    _git(tmp_path, "checkout", "-q", "-b", "alpha")
    for i in range(3):
        _commit(tmp_path, "alpha%d.txt" % i)
    _git(tmp_path, "checkout", "-q", "travail")
    avant = m._etat_git(str(tmp_path))
    _git(tmp_path, "merge", "-q", "--no-ff", "-m", "sync alpha", "alpha")
    (tmp_path / "session.py").write_text("travail en cours", encoding="utf-8")
    effet = m._effet_observe(str(tmp_path), avant)
    assert "commits produits : 0" in effet and "1 fusion" in effet, effet
    assert "fichiers non commites : 1" in effet, effet


def test_un_commit_propre_apres_fusion_compte_un(tmp_path):
    m = _mod()
    _git(tmp_path, "init", "-q", "-b", "travail")
    _commit(tmp_path, "base.txt")
    _git(tmp_path, "checkout", "-q", "-b", "alpha")
    _commit(tmp_path, "alpha0.txt")
    _git(tmp_path, "checkout", "-q", "travail")
    avant = m._etat_git(str(tmp_path))
    _git(tmp_path, "merge", "-q", "--no-ff", "-m", "sync alpha", "alpha")
    _commit(tmp_path, "osmoregulation.py")
    assert "commits produits : 1" in m._effet_observe(str(tmp_path), avant)


def test_non_livre_si_aucun_commit_et_travail_laisse():
    m = _mod()
    effet = "[effet observe] commits produits : 0 (4b06baa74..1296eece5) ; fichiers non commites : 5"
    assert m._non_livre(effet, "Je teste ... Je valide ...") == (
        "[NON LIVRE] aucun commit propre, 5 fichier(s) non committe(s)")


def test_pas_non_livre_pour_un_rapport_qui_pointe_son_artefact_ni_pour_un_commit():
    m = _mod()
    effet0 = "[effet observe] commits produits : 0 (a..b) ; fichiers non commites : 1"
    assert m._non_livre(effet0, '{"pointer_ref": "file:rapport.md"}') is None
    assert m._non_livre("[effet observe] commits produits : 2 (a..b) ; fichiers non commites : 3", "") is None
    assert m._non_livre("[effet observe] commits produits : 0 (a..b) ; fichiers non commites : 0", "") is None
    assert m._non_livre("[effet observe] git ILLISIBLE dans x : rien n'est prouve", "") is None
