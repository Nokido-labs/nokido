"""NR : outil MCP « acp » du hub (depot asynchrone vers tools/forge_acp_hub.py)."""
import asyncio
import time

import pytest

from app.forge_mcp_registry import ToolRegistry
# Le handler importe par l'espace de noms du hub (convention du registre) : espionner CE module-la.
from nokido_agent.tools import forge_acp_hub


def test_acp_passe_l_allowlist_statique_du_mcp():
    """28/10 recette reelle : outil enregistre ET autorise par le RBAC, mais « tool 'acp' not allowed » au /mcp --
    tools/hub_middleware._ALLOWED_TOOLS l'ignorait (gotcha deja paye pour forge_deep_explore, introspect)."""
    from tools import hub_middleware as M
    ok, raison = M.validate_tool_name("acp")
    assert ok, raison


@pytest.fixture
def espion(monkeypatch):
    appels = {"deposer": [], "resultat": []}

    def fake_deposer(op, /, **params):
        appels["deposer"].append((op, params))
        return "a" * 32

    def fake_resultat(job_id, /, **kw):
        appels["resultat"].append(job_id)
        return {"etat": "ACCEPTED"}

    monkeypatch.setattr(forge_acp_hub, "deposer", fake_deposer)
    monkeypatch.setattr(forge_acp_hub, "resultat", fake_resultat)
    return appels


def _run(args):
    return asyncio.run(ToolRegistry().handle_acp(args, "T", 1))


def _src(mod):
    return open(mod.__file__, encoding="utf-8").read()


def test_ouvrir_rend_job_id_sans_attendre(espion):
    t = time.monotonic()
    r = _run({"op": "ouvrir", "agent": "claude", "prompt": "salut"})
    assert time.monotonic() - t < 2
    assert r == {"ok": True, "job_id": "a" * 32, "etat": "REQUESTED"}
    assert espion["deposer"][0][0] == "ouvrir"


def test_resultat_relaie_etat(espion):
    r = _run({"op": "resultat", "job_id": "b" * 32})
    assert r["etat"] == "ACCEPTED" and espion["resultat"] == ["b" * 32]


def test_agent_inconnu_refuse(espion):
    r = _run({"op": "ouvrir", "agent": "evil"})
    assert r["ok"] is False and not espion["deposer"]


def test_op_inconnue_refusee(espion):
    r = _run({"op": "rm"})
    assert r["ok"] is False and not espion["deposer"]


def test_cle_illisible_ok_false(monkeypatch):
    def boom(op, /, **p):
        raise RuntimeError("cle Ed25519 du hub indisponible")
    monkeypatch.setattr(forge_acp_hub, "deposer", boom)
    r = _run({"op": "lister"})
    assert r["ok"] is False and "raison" in r and "etat" not in r


def test_dans_chaque_table_voisine():
    from app import (forge_corrigibility, forge_mcp_rbac, forge_mcp_registry,
                     forge_tool_annotations, forge_tool_scope)
    assert forge_mcp_rbac._TOOL_REQUIRED_RING["acp"] == 1
    for m in (forge_tool_scope, forge_tool_annotations, forge_corrigibility, forge_mcp_registry):
        assert '"acp"' in _src(m), m.__name__
    assert '"acp": 1' in _src(forge_mcp_registry)
    assert '"forge_acp": "acp"' in _src(forge_mcp_registry)
