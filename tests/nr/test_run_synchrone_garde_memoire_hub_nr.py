# -*- coding: utf-8 -*-
"""NR -- voie SYNCHRONE du hub (`run action=python|shell`) sous l'intention differer_taches_lourdes_in_process.

Traverse le vrai handler (ToolRegistry.handle_run) avec un etat memoire simule (tmp_path via
LAFORGE_MEM_ETAT_PATH). run_job / job_status / job_kill / trusted_script ne sont jamais refuses par ce garde.
"""
import json
import time

import pytest

from app import forge_resource_manager as RM
from app.forge_mcp_registry import ToolRegistry

pytestmark = pytest.mark.timeout(60)


def _etat(tmp_path, monkeypatch, ts=None, intentions=("differer_taches_lourdes_in_process",)):
    p = tmp_path / "hub_mem_palier.json"
    p.write_text(json.dumps({"ts": time.time() if ts is None else ts, "palier": "PREFERENCE",
                             "intentions": list(intentions)}), encoding="utf-8")
    monkeypatch.setenv("LAFORGE_MEM_ETAT_PATH", str(p))


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["python", "shell"])
async def test_appel_lourd_refuse_et_dit_sous_etat_ok(tmp_path, monkeypatch, action):
    _etat(tmp_path, monkeypatch)
    res = await ToolRegistry().handle_run(
        {"action": action, "code": "print(1)", "timeout": RM.SEUIL_SYNC_DUREE_S + 1}, "CLAUDE", 1)
    assert res.startswith("ERR:") and "run_job" in res


@pytest.mark.asyncio
async def test_budget_sortie_lourd_refuse(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch)
    res = await ToolRegistry().handle_run(
        {"action": "python", "code": "print(1)", "max_output_chars": RM.SEUIL_SYNC_SORTIE_CHARS + 1}, "CLAUDE", 1)
    assert "run_job" in res and "refuse" in res


@pytest.mark.asyncio
async def test_appel_court_reste_servi(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch)
    res = await ToolRegistry().handle_run({"action": "python", "code": "print('COURT_OK')"}, "CLAUDE", 1)
    assert "COURT_OK" in res


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stale", "absent"])
async def test_stale_illisible_comportement_inchange(tmp_path, monkeypatch, mode):
    if mode == "stale":
        _etat(tmp_path, monkeypatch, ts=time.time() - 9999)
    else:
        monkeypatch.setenv("LAFORGE_MEM_ETAT_PATH", str(tmp_path / "absent.json"))
    args = {"action": "python", "code": "print('PASSE')", "timeout": RM.SEUIL_SYNC_DUREE_S + 1}
    assert RM.refus_synchrone_lourd(args) is None
    res = await ToolRegistry().handle_run(args, "CLAUDE", 1)
    assert "PASSE" in res


def test_sans_intention_pas_de_refus(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch, intentions=())
    assert RM.refus_synchrone_lourd({"action": "shell", "timeout": 999}) is None


@pytest.mark.parametrize("action", ["run_job", "job_status", "job_kill", "trusted_script"])
def test_run_job_et_consorts_jamais_refuses(tmp_path, monkeypatch, action):
    _etat(tmp_path, monkeypatch)
    assert RM.refus_synchrone_lourd({"action": action, "timeout": 99999, "max_output_chars": 10**9}) is None


@pytest.mark.asyncio
async def test_job_status_traverse_le_handler_sans_refus_du_garde(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch)
    res = await ToolRegistry().handle_run({"action": "job_status", "job_id": "", "timeout": 99999}, "CLAUDE", 1)
    assert "synchrone refuse" not in res
