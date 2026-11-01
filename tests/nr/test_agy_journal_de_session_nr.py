# -*- coding: utf-8 -*-
"""NR -- l'executeur passe `--log-file` a agy : le chemin d'une action refusee devient lisible (30/10).

9 taches AGY du 30/10 mortes sur « read_file » refuse ; ni `denied_actions` ni stderr ne nomment le fichier. La meme
commande passe sous le profil owner en console et echoue sous l'executeur : seul le journal d'agy peut trancher.
Contrat : la commande porte `--log-file` vers sandbox/jobs/agy_<tache>.log, et ce chemin part dans le detail.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
CORPS = SRC.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]

pytestmark = pytest.mark.timeout(60)


def test_la_commande_porte_un_journal_de_session():
    assert '"--log-file"' in CORPS
    assert "agy_" in CORPS and ".log" in CORPS
