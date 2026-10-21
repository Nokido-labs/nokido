"""NR 18/10 -- le travail d'un agent dont la session echoue n'est plus perdu.

Mesure du 18/10 : deux livraisons OPENCODE_NEMOTRON (job_094dea4e arbre roadmaps, job_24ee0a6f rejeu C06) ont
fini « [NON LIVRE] aucun commit propre, N fichier(s) non committe(s) » alors que le code ET les NR etaient dans
le worktree : forge_task_executor ne committait que si la session OpenCode avait REUSSI (`if ok:`), et la
session avait echoue APRES l'ecriture (quota/delai puis repli de modele). La reaffectation repartait d'alpha :
le travail pouvait etre ecrase. Contrat : session en echec MAIS travail neuf -> commit sur la branche de l'agent,
marque INACHEVE / A RELIRE (jamais vers alpha sans relecture) ; rien de neuf -> rien ; succes -> inchange.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as E  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _sauvegardes_isolees(tmp_path, monkeypatch):
    # 19/10 : un commit refuse produit desormais une COPIE de sauvegarde -- jamais dans le vrai sandbox/.
    monkeypatch.setattr(E, "_SAUVEGARDES", tmp_path / "sauvegardes", raising=False)


_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t"}


def _git(*a, cwd):
    return subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          cwd=str(cwd), capture_output=True, text=True, errors="replace").stdout.strip()


def _wt(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git("init", "-q", cwd=wt)
    _git("add", "-A", cwd=wt)
    _git("commit", "-q", "-m", "base", cwd=wt)
    return wt


def test_session_en_echec_mais_travail_present_est_committe_inacheve(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_env_git", lambda: _ENV)
    wt = _wt(tmp_path)
    (wt / "nouveau.py").write_text("y = 2\n", encoding="utf-8")
    note = E._preserver_livraison(False, str(wt), "job_x", "erreur ACP OpenCode (TimeoutError)", "NEMOTRON", frozenset())
    assert note and "INACHEVE preserve" in note
    log = _git("log", "-1", "--format=%s", cwd=wt)
    assert "INACHEVE" in log and _git("status", "--porcelain", cwd=wt) == ""


def test_commit_refuse_n_est_jamais_dit_preserve(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_env_git", lambda: {**os.environ, "GIT_AUTHOR_NAME": "", "GIT_COMMITTER_NAME": "",
                                                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    wt = _wt(tmp_path)
    (wt / "nouveau.py").write_text("y = 2\n", encoding="utf-8")
    note = E._preserver_livraison(False, str(wt), "job_x", "erreur", "NEMOTRON", frozenset())
    assert note and "INACHEVE NON committe" in note and "preserve" not in note


def test_session_en_echec_sans_travail_ne_committe_rien(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_env_git", lambda: _ENV)
    wt = _wt(tmp_path)
    assert E._preserver_livraison(False, str(wt), "job_x", "erreur", "NEMOTRON", frozenset()) is None
    assert _git("log", "--oneline", cwd=wt).count("\n") == 0


def test_session_reussie_inchangee(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_env_git", lambda: _ENV)
    wt = _wt(tmp_path)
    (wt / "b.py").write_text("z = 3\n", encoding="utf-8")
    note = E._preserver_livraison(True, str(wt), "job_x", '{"commit_message":"feat: b"}', "NEMOTRON", frozenset())
    assert note and "INACHEVE" not in note and _git("log", "-1", "--format=%s", cwd=wt) == "feat: b"
