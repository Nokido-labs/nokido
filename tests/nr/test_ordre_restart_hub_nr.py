"""NR 31/10 -- redemarrer le HUB SEUL par la meme fenetre Oui/Non, au lieu de la stack complete.

Owner 31/10 : « pourquoi tu as declenche un reboot full stack alors que tu parles du hub ? ». Le CLI pilote n'avait
qu'un ordre `restart` (stack complete) ; le tray, lui, sait deja `restart-hub` (menu « Restart HUB seul ») et execute
toute action de son panneau, fenetre Oui/Non comprise pour un ordre `a_valider`. Il manquait l'ORDRE.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from nokido_agent.app import forge_ordres_bureau as B

RACINE = Path(__file__).resolve().parents[2]


def _actions_panneau_du_tray():
    src = (RACINE / "tools" / "nokido_tray.py").read_text(encoding="utf-8")
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ACTIONS_PANNEAU" for t in n.targets):
            return set(ast.literal_eval(n.value))
    raise AssertionError("ACTIONS_PANNEAU introuvable dans le tray")


def test_l_ordre_existe_et_le_tray_sait_l_executer():
    assert "restart-hub" in B.ACTIONS
    assert "restart-hub" in _actions_panneau_du_tray()


def test_le_cli_pilote_depose_un_restart_hub_a_valider(monkeypatch):
    deposes = []
    monkeypatch.setattr(B, "_surface_de", lambda agent: "interactive")
    monkeypatch.setattr(B, "deposer", lambda action, dem, raison="", a_valider=False, **k:
                        deposes.append((action, a_valider)) or {"id": "ordre-test"})
    r = asyncio.run(B.demander_ordre("CLAUDE", "restart-hub", "activer un correctif du hub", demandeur_prouve=True))
    assert r["etat"] == B.DEPOSE and r["a_valider"] is True
    assert deposes == [("restart-hub", True)]


def test_restart_complet_inchange(monkeypatch):
    deposes = []
    monkeypatch.setattr(B, "_surface_de", lambda agent: "interactive")
    monkeypatch.setattr(B, "deposer", lambda action, dem, raison="", a_valider=False, **k:
                        deposes.append((action, a_valider)) or {"id": "ordre-test"})
    asyncio.run(B.demander_ordre("CLAUDE", "restart", "", demandeur_prouve=True))
    assert deposes == [("restart", True)]
