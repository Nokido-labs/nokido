# -*- coding: utf-8 -*-
"""NR -- `hub action=whoami` dit QUAND le hub a demarre (owner 30/10 : « il faudrait que tu puisses le voir »).

Deux restarts owner du 30/10 n'etaient visibles que dans laforge-master.log. Rendu AGY d543f5e17 (premiere tache de code
AGY livree apres la reparation du lancement dans le worktree de tache) : `hub_pid` et `hub_demarre_a` (ISO) dans la
reponse de handle_whoami ; psutil illisible -> "ILLISIBLE", jamais absent ni invente.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[2] / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
CORPS = SRC.split("async def handle_whoami", 1)[1].split("\n    async def ", 1)[0]

pytestmark = pytest.mark.timeout(60)


def test_whoami_porte_pid_et_heure_de_demarrage():
    assert '"hub_pid": os.getpid()' in CORPS
    assert '"hub_demarre_a": _hub_demarre_a' in CORPS


def test_lecture_illisible_dite_jamais_inventee():
    assert '_hub_demarre_a = "ILLISIBLE"' in CORPS
    assert "create_time()" in CORPS
