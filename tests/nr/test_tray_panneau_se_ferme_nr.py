# -*- coding: utf-8 -*-
"""NR -- la console du panneau lancee par le tray se FERME quand l'action reussit (owner 30/10).

`lancer_panneau` ouvrait `cmd.exe /k` : la fenetre restait ouverte apres chaque restart du hub et
l'owner devait la fermer a la main. Contrat : `cmd.exe /c` (fermeture a la fin) et `|| pause` (un
ECHEC garde la fenetre ouverte, l'owner lit l'erreur).
"""
from __future__ import annotations

from pathlib import Path

import pytest

# nokido_tray sort (sys.exit) a l'import hors bureau interactif : on lit son SOURCE, comme
# test_tray_se_recharge_sur_code_perime_nr.
SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_tray.py").read_text(encoding="utf-8")
PANNEAU = SRC.split("def lancer_panneau", 1)[1].split("\ndef ", 1)[0]

pytestmark = pytest.mark.timeout(60)


def test_console_se_ferme_si_succes():
    assert "cmd.exe /c " in PANNEAU
    assert "cmd.exe /k" not in PANNEAU


def test_echec_garde_la_fenetre_ouverte():
    assert "|| pause" in PANNEAU
