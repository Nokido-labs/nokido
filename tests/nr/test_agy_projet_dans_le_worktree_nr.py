# -*- coding: utf-8 -*-
"""NR -- AGY tourne DANS le worktree de tache, qui est SON projet (patron « Worktree mode » de Codex, veille 30/10).

Mesure owner 30/10 (cmd-041b15585ee8) : agy lance dans un worktree de tache avec `--new-project`, sans `--add-dir` ni
regle de permission, lit `app/forge_ssot.py` en 5,8 s / 24 k tokens. Lance avec `--add-dir <worktree de tache>`, son
projet restait le worktree HABITUEL : lectures du worktree de tache refusees en headless (7 taches mortes le 30/10),
ecritures au mauvais endroit (rapatriement). Contrat : `--new-project`, cwd = worktree de tache, plus de `--add-dir`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
CORPS = SRC.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]

pytestmark = pytest.mark.timeout(60)


def test_agy_ouvre_son_projet_dans_le_worktree():
    assert '"--new-project"' in CORPS
    assert "cwd=workdir" in CORPS


def test_plus_d_add_dir_dans_la_commande():
    ligne = next(l for l in CORPS.splitlines() if "_consigne_agy(workdir)" in l and "cmd = [" in l)
    suite = CORPS.split(ligne, 1)[1].split("\n", 3)[:2]
    assert "--add-dir" not in ligne and not any("--add-dir" in s for s in suite), ligne
