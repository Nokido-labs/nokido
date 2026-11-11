# -*- coding: utf-8 -*-
"""NR -- 9/11 : `forge_merge_gate reconcilier --commit <sha>` ne prenait que les fichiers du DERNIER commit. Or
l'executeur livre en DEUX commits (RED : le test ; puis le code) : le NR de la livraison e8b4a8ef6 (mint sans
empreinte) etait « manquant » et l'integration a du se faire a la main. Le plan couvre toute la livraison
(alpha...sha), toujours filtree par les fichiers NOMMES."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_merge_gate as G  # noqa: E402


def _g(d, *a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(d), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout.strip()


def test_le_test_du_commit_red_fait_partie_du_plan(tmp_path):
    d = tmp_path / "depot"
    d.mkdir()
    _g(d, "init", "-q", "-b", "alpha")
    _g(d, "config", "user.email", "nr@local")
    _g(d, "config", "user.name", "nr")
    (d / "a.py").write_text("X = 1\n", encoding="utf-8")
    _g(d, "add", "a.py")
    _g(d, "commit", "-q", "-m", "base")
    _g(d, "checkout", "-q", "-b", "tache/x")
    (d / "tests").mkdir()
    (d / "tests" / "t_nr.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    _g(d, "add", "tests/t_nr.py")
    _g(d, "commit", "-q", "-m", "test(X): RED")
    (d / "a.py").write_text("X = 2\n", encoding="utf-8")
    _g(d, "commit", "-q", "-am", "fix(X): code")
    sha = _g(d, "rev-parse", "HEAD")
    _g(d, "checkout", "-q", "alpha")
    r = G.reconcilier(sha, ["tests/t_nr.py", "a.py"], apply=False, root=d)
    assert sorted(r["plan"]["a_integrer"]) == ["a.py", "tests/t_nr.py"], r
    assert not r["plan"]["manquants"], r


def test_une_livraison_sur_base_perimee_n_ecrase_jamais_alpha(tmp_path):
    """9/11 : l'extraction est par FICHIER ENTIER ; une livraison partie d'un alpha plus ancien effacerait les commits
    faits depuis dans ce fichier (cas reel : livraison AGY 236c816c3 sur forge_task_executor.py). Refus + voie dite."""
    d = tmp_path / "depot"
    d.mkdir()
    _g(d, "init", "-q", "-b", "alpha")
    _g(d, "config", "user.email", "nr@local")
    _g(d, "config", "user.name", "nr")
    (d / "a.py").write_text("L1 = 1\nL2 = 2\nL3 = 3\n", encoding="utf-8")
    _g(d, "add", "a.py")
    _g(d, "commit", "-q", "-m", "base")
    _g(d, "checkout", "-q", "-b", "tache/x")
    (d / "a.py").write_text("L1 = 10\nL2 = 2\nL3 = 3\n", encoding="utf-8")
    _g(d, "commit", "-q", "-am", "fix(X): L1")
    sha = _g(d, "rev-parse", "HEAD")
    _g(d, "checkout", "-q", "alpha")
    (d / "a.py").write_text("L1 = 1\nL2 = 2\nL3 = 30\n", encoding="utf-8")
    _g(d, "commit", "-q", "-am", "alpha avance : L3")
    r = G.reconcilier(sha, ["a.py"], apply=True, root=d, tests=[])
    assert r["applique"] is False and "3 voies" in r["decision"], r
    assert "L3 = 30" in (d / "a.py").read_text(encoding="utf-8")
