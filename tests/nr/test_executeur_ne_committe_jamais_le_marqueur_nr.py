"""NR -- l'executeur ne committe JAMAIS le marqueur de worktree `.nokido.agent`.

Mesure 2026-10-17 : _committer_pour_agent indexe tout ce que `git status` liste ; le marqueur d'identite (non suivi dans
chaque worktree) partait dans les commits de livraison -- 3c9e89e0c, 422690f59, 38f0fa758, 336ba94a4 (GPTOSS), et chez
GLM (« LIVRAISON VIDE : 1 fichier committe, configuration de l'agent »). Le garde du pre-commit (demande owner R7
b623ecc7915c) va le BLOQUER : sans ce correctif, toute livraison serait refusee. Chemin REEL : vrai depot git temporaire.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402


def _git(wt, *args):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(wt), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def test_la_livraison_est_committee_sans_le_marqueur(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    assert _git(wt, "init", "-q").returncode == 0
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    (wt / "base.txt").write_text("base\n", encoding="utf-8")
    _git(wt, "add", "base.txt")
    assert _git(wt, "commit", "-q", "-m", "base").returncode == 0
    (wt / "tools").mkdir()
    (wt / "tools" / "x.py").write_text("X = 1\n", encoding="utf-8")
    (wt / ".nokido.agent").write_text("agent=OPENCODE_TEST\n", encoding="utf-8")

    note = T._committer_pour_agent(str(wt), "t1", 'fait {"intent":"OK_DONE","pointer_ref":"x"}', "OPENCODE_TEST")

    assert note and "commit executeur de 1 fichier" in note, note
    suivis = set(_git(wt, "ls-files").stdout.split())
    assert "tools/x.py" in suivis
    assert ".nokido.agent" not in suivis, "le marqueur d'identite du worktree est parti dans le commit"


def test_un_worktree_qui_ne_porte_que_le_marqueur_n_a_rien_a_committer(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    (wt / "base.txt").write_text("base\n", encoding="utf-8")
    _git(wt, "add", "base.txt")
    _git(wt, "commit", "-q", "-m", "base")
    (wt / ".nokido.agent").write_text("agent=OPENCODE_TEST\n", encoding="utf-8")
    assert T._committer_pour_agent(str(wt), "t2", "fait", "OPENCODE_TEST") is None
