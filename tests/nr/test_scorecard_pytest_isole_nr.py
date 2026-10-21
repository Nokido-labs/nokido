"""NR (RED en attente) -- le pytest imbrique du scorecard est enracine dans le worktree livre.

Meme defaut que forge_mutation_judge.mesurer (test_pytest_imbrique_isole_nr, CI de reference 46c8adfa5) : sans
--rootdir/--confcutdir, la collecte de pytest >= 8 liste les dossiers ancetres ou naissent et meurent les temporaires
d'autres tests (UNRATED observe a la reference 63a63a812). forge_scorecard est un module de JUGE : la separation des
pouvoirs interdit a CLAUDE de le modifier -- GREEN par derogation owner ou par un autre agent.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_scorecard as S  # noqa: E402


class _R:
    returncode, stdout, stderr = 0, "1 passed in 0.1s", ""


def _valeur(cmd, option):
    for i, x in enumerate(cmd):
        if x == option and i + 1 < len(cmd):
            return cmd[i + 1]
    return None


def test_le_scorecard_enracine_son_pytest_dans_le_worktree(tmp_path, monkeypatch):
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_a_nr.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    vus = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: vus.append(cmd) or _R())
    S.scorecard_de_livraison(tmp_path, ["tests/nr/test_a_nr.py"])
    cmds = [c for c in vus if "pytest" in c]
    assert cmds and _valeur(cmds[0], "--rootdir") == str(tmp_path), vus
    assert _valeur(cmds[0], "--confcutdir") == str(tmp_path), vus
