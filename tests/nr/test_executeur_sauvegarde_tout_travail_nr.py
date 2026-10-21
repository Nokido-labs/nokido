# -*- coding: utf-8 -*-
"""NR 19/10 -- aucun travail produit par un executeur ne se perd, meme quand aucun commit ne le garde.

Mesure du 19/10 (enquete AGY docs/audit/executeurs_non_livre_20261019.md, recoupee) : 5 livraisons sans commit.
Trois chemins ou les fichiers ecrits n'etaient gardes NULLE PART puis ecrases au recalage sur alpha :
  1. session en echec : le commit INACHEVE passe par le scorecard -- un travail inacheve qui ne compile pas est
     REFUSE (job_c0eab523, OPENCODE_GLM : « det-diff : ne compile pas ») ;
  2. session reussie, scorecard REJETE : le refus est voulu (decision owner 19/10 : un diff casse n'est jamais
     committe), mais les fichiers disparaissaient avec lui ;
  3. intention d'erreur dans la sortie (`_intent_rendu`) : retour None immediat, rien de garde.
Contrat : dans ces trois cas, COPIE des fichiers produits dans `_SAUVEGARDES/<agent>/<tache>/` + manifeste
(motif, fichiers, worktree) -- sans git, donc sans hook a contourner (`--no-verify` ecarte). Une copie n'est PAS un
commit : la note ne dit jamais « preserve » a tort. Rien de neuf -> rien. Jamais un fichier hors du worktree.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import forge_task_executor as E  # noqa: E402

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


@pytest.fixture()
def rejete(monkeypatch):
    """Scorecard qui REJETTE tout diff, verdict de motivation neutralise."""
    class _G:
        REJECTED = "REJECTED"

    class _Sc:
        grade = "REJECTED"
        critique = "det-diff : ne compile pas"

    sc = types.ModuleType("nokido_agent.app.forge_scorecard")
    sc.QualityGrade = _G
    sc.scorecard_de_livraison = lambda wt, chemins: _Sc()
    mo = types.ModuleType("nokido_agent.app.forge_motivation")
    mo.recompenser_resultat = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_scorecard", sc)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_motivation", mo)


@pytest.fixture()
def sauvegardes(tmp_path, monkeypatch):
    d = tmp_path / "sauvegardes"
    monkeypatch.setattr(E, "_SAUVEGARDES", d)
    monkeypatch.setattr(E, "_env_git", lambda: _ENV)
    return d


def test_inacheve_refuse_par_le_scorecard_est_copie(tmp_path, rejete, sauvegardes):
    wt = _wt(tmp_path)
    (wt / "nouveau.py").write_text("def f(:\n", encoding="utf-8")
    note = E._preserver_livraison(False, str(wt), "job_x", "erreur ACP", "OPENCODE_GLM", frozenset())
    copie = sauvegardes / "OPENCODE_GLM" / "job_x" / "nouveau.py"
    assert copie.read_text(encoding="utf-8") == "def f(:\n"
    man = json.loads((sauvegardes / "OPENCODE_GLM" / "job_x" / "manifeste.json").read_text(encoding="utf-8"))
    assert man["fichiers"] == ["nouveau.py"] and "scorecard" in man["motif"]
    assert "COPIE de sauvegarde" in note and "preserve" not in note


def test_livraison_rejetee_est_copiee(tmp_path, rejete, sauvegardes):
    wt = _wt(tmp_path)
    (wt / "b.py").write_text("z = (\n", encoding="utf-8")
    note = E._preserver_livraison(True, str(wt), "job_y", '{"commit_message":"feat: b"}', "OPENCODE_GPTOSS",
                                  frozenset())
    assert (sauvegardes / "OPENCODE_GPTOSS" / "job_y" / "b.py").exists()
    assert "REFUSE par le scorecard" in note and "COPIE de sauvegarde" in note


def test_intention_d_erreur_ne_perd_plus_le_travail(tmp_path, sauvegardes):
    wt = _wt(tmp_path)
    (wt / "c.py").write_text("w = 4\n", encoding="utf-8")
    note = E._preserver_livraison(True, str(wt), "job_z", '{"intent": "ERR_INTERNAL", "status_code": "FAILURE"}',
                                  "OPENCODE_NEMOTRON", frozenset())
    assert note and "COPIE de sauvegarde" in note
    assert (sauvegardes / "OPENCODE_NEMOTRON" / "job_z" / "c.py").read_text(encoding="utf-8") == "w = 4\n"


def test_rien_de_neuf_rien_de_copie(tmp_path, rejete, sauvegardes):
    wt = _wt(tmp_path)
    assert E._preserver_livraison(False, str(wt), "job_w", "erreur", "OPENCODE_GLM", frozenset()) is None
    assert not sauvegardes.exists()


def test_les_sales_d_avant_ne_sont_pas_copies(tmp_path, rejete, sauvegardes):
    wt = _wt(tmp_path)
    (wt / "deja_sale.py").write_text("v = 0\n", encoding="utf-8")
    (wt / "neuf.py").write_text("u = (\n", encoding="utf-8")
    E._preserver_livraison(False, str(wt), "job_v", "erreur", "OPENCODE_GLM", frozenset({"deja_sale.py"}))
    d = sauvegardes / "OPENCODE_GLM" / "job_v"
    assert (d / "neuf.py").exists() and not (d / "deja_sale.py").exists()
