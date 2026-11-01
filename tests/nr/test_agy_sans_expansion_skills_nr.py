# -*- coding: utf-8 -*-
"""NR -- chasse aux tokens (owner 30/10 : « 50 000 tokens juste pour un whoami, pas acceptable ») : l'executeur coupe
l'expansion des slash commands et skills d'agy en mode print (`--disable-slash-commands`, aide d'agy relue le 30/10).
Une tache deleguee porte sa consigne complete : les skills developpees a chaque lancement ne sont que du contexte paye.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
CORPS = SRC.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]

pytestmark = pytest.mark.timeout(60)


def test_expansion_des_skills_coupee():
    assert '"--disable-slash-commands"' in CORPS
