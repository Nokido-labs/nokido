# -*- coding: utf-8 -*-
"""NR — app/forge_goap.py & tools/forge_orchestrate_loop.py : contrats de verdict (Constat 2).

Contexte (Audit ChatGPT 15/10) :
1. `forge_goap._execute_subgoal` ne testait que `result.get("error")`. Une réponse
   avec `ok == False` (sans clé 'error') ou une réponse non-dict / illisible était
   marquée comme `completed` (succès) !
2. `forge_orchestrate_loop._hub_dispatch` convertissait les erreurs non-JSON en
   `{"ok": True, "stdout": raw}` et renvoyait aveuglément `ok: True` sur read/rag/web
   sans vérifier si le hub a retourné une erreur (ex: 'ERR handle_read: ...') ou du vide.

Contrats requis :
- `ok: false` = échec (status="failed", pas "completed").
- Réponse illisible (non-dict, None, vide) = UNKNOWN, jamais OK.
- Aucun succès sans réponse du hub lue.
- Trajectory.ok reflète la complétion réelle sans échec.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from nokido_agent.app.forge_goap import PlanTree, SubGoal, execute_plan
from nokido_agent.app.forge_trajectory import Trajectory


def _build_test_plan(method: str = "run_shell", params: dict | None = None) -> PlanTree:
    intent = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {"command": "echo test"},
        "id": "act_test_1",
    }
    return PlanTree(
        goal="Tester contrat de verdict",
        ring_max=2,
        parallel=False,
        subgoals=[SubGoal(name="sg_test", actions=[intent])],
    )


@pytest.mark.asyncio
async def test_goap_rejects_ok_false():
    """Un résultat avec ok == False (sans clé 'error') DOIT faire échouer l'étape."""
    plan = _build_test_plan()

    async def mock_dispatch_ok_false(action):
        return {"ok": False, "stderr": "Permission denied: disk error", "stdout": ""}

    traj = await execute_plan(plan, dispatch_fn=mock_dispatch_ok_false, rollback=False)

    assert len(traj.steps) == 1
    step = traj.steps[0]
    assert step.status == "failed", f"L'étape avec ok=False aurait dû être 'failed', mais est '{step.status}'"
    assert hasattr(traj, "ok")
    assert not traj.ok, "La trajectoire ne doit pas être validée si une étape a échoué"


@pytest.mark.asyncio
async def test_goap_rejects_unreadable_and_empty_responses():
    """Une réponse non-dict, None ou vide DOIT être rejetée comme UNKNOWN, jamais OK."""
    plan = _build_test_plan()

    # Cas 1 : dispatch renvoie None
    async def mock_dispatch_none(action):
        return None

    traj_none = await execute_plan(plan, dispatch_fn=mock_dispatch_none, rollback=False)
    assert traj_none.steps[0].status == "failed"
    assert "UNKNOWN" in str(traj_none.steps[0].result)

    # Cas 2 : dispatch renvoie une chaîne brute (non-dict)
    async def mock_dispatch_str(action):
        return "FATAL: process terminated abruptly"

    traj_str = await execute_plan(plan, dispatch_fn=mock_dispatch_str, rollback=False)
    assert traj_str.steps[0].status == "failed"
    assert "UNKNOWN" in str(traj_str.steps[0].result)

    # Cas 3 : dispatch renvoie un dict vide
    async def mock_dispatch_empty(action):
        return {}

    traj_empty = await execute_plan(plan, dispatch_fn=mock_dispatch_empty, rollback=False)
    assert traj_empty.steps[0].status == "failed"
    assert "UNKNOWN" in str(traj_empty.steps[0].result)


@pytest.mark.asyncio
async def test_orchestrate_loop_hub_dispatch_verdicts():
    """_hub_dispatch ne doit jamais masquer les erreurs non-JSON ou les erreurs du hub."""
    from nokido_agent.tools.forge_orchestrate_loop import _hub_dispatch

    # 1. run_python avec réponse non-JSON du hub (ex: crash 500, HTML ou message d'erreur texte)
    intent_py = {"method": "run_python", "params": {"code": "1+1"}}
    with patch("nokido_agent.tools.forge_orchestrate_loop._hub_async", return_value="502 Bad Gateway: backend unreachable"):
        res = await _hub_dispatch(intent_py)
        assert res.get("ok") is False, "Une réponse non-JSON à run_python ne doit PAS renvoyer ok: True !"
        assert "UNKNOWN" in str(res.get("error", "")) or res.get("status") == "UNKNOWN"

    # 2. read_file avec erreur du hub (ex: 'ERR handle_read: File not found')
    intent_read = {"method": "read_file", "params": {"path": "inexistant.txt"}}
    with patch("nokido_agent.tools.forge_orchestrate_loop._hub_async", return_value="ERR handle_read: File not found"):
        res_read = await _hub_dispatch(intent_read)
        assert res_read.get("ok") is False, "Une réponse 'ERR handle_read' ne doit PAS être renvoyée avec ok: True !"

    # 3. read_file avec réponse vide
    with patch("nokido_agent.tools.forge_orchestrate_loop._hub_async", return_value=""):
        res_empty = await _hub_dispatch(intent_read)
        assert res_empty.get("ok") is False, "Une réponse vide du hub ne doit PAS être renvoyée avec ok: True !"
        assert "UNKNOWN" in str(res_empty.get("error", "")) or res_empty.get("status") == "UNKNOWN"


def test_trajectory_ok_property():
    """Trajectory.ok doit être True ssi steps non vide et aucun failed."""
    t = Trajectory()
    assert hasattr(t, "ok"), "Trajectory doit posséder la propriété 'ok'"
    assert not t.ok  # vide -> False

    step = t.append({"method": "test"})
    assert not t.ok  # pending -> False

    t.complete(0, {"result": "ok"})
    assert t.ok  # completed -> True

    t.append({"method": "test2"})
    t.fail(1, "ko")
    assert not t.ok  # 1 step failed -> False
