# -*- coding: utf-8 -*-
"""NR -- le gate cognitif de governed_edit ne bloque plus la boucle d'evenements du hub.

Alerte owner 2026-11-08 « ANTI-EMBOLIE event_loop » : logs/loop_lag.log, lags du hub de
5592 ms (22:20:39) et 1750 ms (22:34:32), pile coupable = handle_governed_edit ->
forge_introspect.verdict_cognitif, appele en SYNCHRONE dans la coroutine (forge_mcp_registry.py
l.4130). Chaque ecriture gouvernee gelait tout le hub. Contrat : le verdict s'execute dans un
fil (asyncio.to_thread), jamais dans le fil de la boucle.
"""
import asyncio
import importlib
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_verdict_cognitif_hors_du_fil_de_la_boucle(monkeypatch, tmp_path):
    reg = importlib.import_module("nokido_agent.app.forge_mcp_registry")
    intro = importlib.import_module("nokido_agent.app.forge_introspect")
    fils = []

    def faux_verdict(agent, rel, contenu):
        fils.append(threading.get_ident())
        raise RuntimeError("arret volontaire apres mesure du fil")

    monkeypatch.setattr(intro, "verdict_cognitif", faux_verdict)

    async def scenario():
        boucle = threading.get_ident()
        soi = SimpleNamespace(root=tmp_path)
        try:
            await reg.ToolRegistry.handle_governed_edit(
                soi, {"path": "tests/nr/x_inexistant.py", "content": "x = 1\n"}, "CLAUDE", 0)
        except Exception:
            pass
        return boucle

    boucle = asyncio.run(scenario())
    assert fils, "verdict_cognitif jamais atteint : le NR ne mesure rien"
    assert fils[0] != boucle, "verdict_cognitif tourne dans le fil de la boucle : il gele le hub"
