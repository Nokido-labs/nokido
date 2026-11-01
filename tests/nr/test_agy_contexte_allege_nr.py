# -*- coding: utf-8 -*-
"""NR -- owner 30/10 « 180 000 tokens c'est encore enorme » : sonde mesuree, un tour AGY SANS outil = 22 336 tokens,
dont ~19 000 de fichiers de contexte (GEMINI.md, AGENTS.md, CLAUDE.md + RULES_SHARED importe deux fois) recharges a
CHAQUE tour. Le worktree de tache recoit des versions MINIMALES, marquees skip-worktree : git ne les voit pas
(ni status, ni commit, ni retrait du worktree bloque) ; un fichier non suivi n'est pas cree."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as fte  # noqa: E402


def _git(d, *a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(d), *a], capture_output=True, text=True,
                          errors="replace")


def _depot(tmp_path):
    d = tmp_path / "wt"
    d.mkdir()
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    (d / "GEMINI.md").write_text("@RULES_SHARED.md\n" + "regle longue\n" * 500, encoding="utf-8")
    (d / "AGENTS.md").write_text("agents " * 800, encoding="utf-8")
    _git(d, "add", "GEMINI.md", "AGENTS.md")
    _git(d, "commit", "-q", "-m", "init")
    return d


def test_contexte_allege_et_invisible_pour_git(tmp_path):
    d = _depot(tmp_path)
    avant = (d / "GEMINI.md").stat().st_size
    fte._alleger_contexte_tache(d)
    assert (d / "GEMINI.md").stat().st_size < avant // 10
    assert "@" not in (d / "GEMINI.md").read_text(encoding="utf-8").split("\n")[0]  # plus d'import
    assert (d / "AGENTS.md").stat().st_size < 2000
    assert _git(d, "status", "--porcelain").stdout.strip() == ""  # rien a committer, retrait possible


def test_fichier_non_suivi_jamais_cree(tmp_path):
    d = _depot(tmp_path)
    fte._alleger_contexte_tache(d)
    assert not (d / "CLAUDE.md").exists()


def test_regles_essentielles_presentes(tmp_path):
    d = _depot(tmp_path)
    fte._alleger_contexte_tache(d)
    t = (d / "GEMINI.md").read_text(encoding="utf-8")
    for mot in ("shell", "balayage", "coffre", "pointeur"):
        assert mot in t
