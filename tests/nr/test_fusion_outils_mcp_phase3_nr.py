# -*- coding: utf-8 -*-
"""NR phase 3 de l'audit des schemas MCP (choix owner 31/10).

route_dt -> route_task mode=dt ; react_orchestrate -> orchestrate engine=react. Les anciens noms ne sont plus LISTES
(poids du catalogue) mais restent APPELABLES (gestionnaires et ring gardes). Le mode dt garde le ring de route_dt :
route_task est ouvert au ring 3, route_dt au ring 2 -- sans ce garde, la fusion elevait le privilege d'un appelant.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from forge_mcp_registry import ToolRegistry


@pytest.fixture
def reg(tmp_path):
    with patch("pathlib.Path.home", return_value=tmp_path):
        r = ToolRegistry(root_dir=tmp_path)
    r._event_bus = MagicMock()
    return r


def test_les_outils_absorbes_ne_sont_plus_listes_mais_restent_appelables(reg):
    noms = {t["name"] for t in reg._all_tools()}
    assert {"route_task", "orchestrate"} <= noms
    assert "route_dt" not in noms and "react_orchestrate" not in noms
    assert callable(getattr(reg, "handle_route_dt", None)) and callable(getattr(reg, "handle_react_orchestrate", None))
    assert reg._TOOL_MIN_RING.get("route_dt") == 2


def test_mode_dt_garde_le_ring_de_route_dt(reg):
    appels = []

    async def faux_dt(args, agent, ring):
        appels.append(args)
        return "DT"

    reg.handle_route_dt = faux_dt
    refus = asyncio.run(reg.handle_route_task({"mode": "dt", "task_type": "code", "payload": {"prompt": "x"}}, "T", 3))
    assert "ring" in refus and not appels, "ring 3 a atteint route_dt : elevation de privilege"
    assert asyncio.run(reg.handle_route_task({"mode": "dt", "task_type": "code", "payload": {"prompt": "x"}},
                                             "T", 2)) == "DT"
    assert appels == [{"prompt": "x", "task_type": "code"}]


def test_engine_react_delegue_a_la_boucle_react(reg):
    appels = []

    async def faux_react(args, agent, ring):
        appels.append(args)
        return "REACT"

    reg.handle_react_orchestrate = faux_react
    assert asyncio.run(reg.handle_orchestrate({"task": "t", "engine": "react", "max_iter": 3}, "T", 2)) == "REACT"
    assert appels == [{"task": "t", "max_iter": 3}]
