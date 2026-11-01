# -*- coding: utf-8 -*-
"""NR -- owner 30/10 « la fenetre ne s'est toujours pas fermee ; au demarrage tu sais le faire ! » : le tray de 09:11
tournait encore `cmd /k` (66a76c36e jamais charge) parce qu'il ne se rechargeait qu'apres start/restart, et l'owner
n'utilise que « Restart HUB seul ». Toute action de panneau recharge un tray dont le code a derive.

nokido_tray sort (sys.exit) a l'import hors bureau interactif : on lit son SOURCE, comme
test_tray_panneau_se_ferme_nr."""
from __future__ import annotations

from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_tray.py").read_text(encoding="utf-8")
RELANCE = SRC.split("def _relancer_si_perime", 1)[1].split("\ndef ", 1)[0]


def test_toute_action_de_panneau_recharge_un_tray_perime():
    assert "if action not in ACTIONS_PANNEAU:" in RELANCE
    assert 'not in ("start", "restart")' not in RELANCE


def test_restart_hub_est_une_action_de_panneau():
    actions = SRC.split("ACTIONS_PANNEAU = (", 1)[1].split(")", 1)[0]
    assert '"restart-hub"' in actions
