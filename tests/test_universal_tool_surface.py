"""Surface Tool universelle : meme forme interne quel que soit l'habillage."""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_universal_tool_surface as uts  # noqa: E402


def test_les_trois_protocoles_donnent_la_meme_forme():
    """L'INVARIANT du module : l'habillage ne change pas ce qui atteint le dispatch."""
    mcp = uts.normalize({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "rag", "arguments": {"q": "x"}}}, "mcp", agent="a")
    acp = uts.normalize({"id": 1, "tool": "rag", "input": {"q": "x"}}, "acp", agent="a")
    api = uts.normalize({"id": 1, "path": "/v1/rag", "body": {"q": "x"}}, "openapi", agent="a")
    assert mcp["args"] == acp["args"] == api["args"] == {"q": "x"}
    assert acp["tool"] == mcp["tool"] == "rag"
    assert api["tool"] == "v1_rag"


def test_le_ring_ne_se_lit_JAMAIS_dans_la_requete():
    """Un appelant qui choisit son privilege = escalade offerte."""
    n = uts.normalize({"tool": "rag", "input": {}, "ring": 0, "agent": "root"},
                      "acp", agent="reel", ring=3)
    assert n["ring"] == 3 and n["agent"] == "reel"


def test_ring_par_defaut_est_le_moins_privilegie():
    assert uts.normalize({"tool": "t", "input": {}}, "acp")["ring"] == uts.DEFAULT_RING


@pytest.mark.parametrize("req,proto", [
    ({}, "mcp"),
    ({"params": {}}, "mcp"),
    ({"tool": "   "}, "acp"),
    ({"body": {}}, "openapi"),
])
def test_requete_sans_tool_est_refusee_en_amont(req, proto):
    with pytest.raises(uts.ToolCallError):
        uts.normalize(req, proto)


def test_protocole_inconnu_refuse():
    with pytest.raises(uts.ToolCallError):
        uts.normalize({"tool": "t"}, "carrier-pigeon")


def test_args_non_objet_refuses():
    with pytest.raises(uts.ToolCallError):
        uts.normalize({"tool": "t", "input": ["liste"]}, "acp")


def test_reponse_rehabillee_par_protocole():
    for proto, cle in (("mcp", "result"), ("acp", "output"), ("openapi", "body")):
        n = uts.normalize({"id": 7, "tool": "t", "input": {}, "path": "/t",
                           "params": {"name": "t"}}, proto)
        assert cle in uts.to_protocol_response({"ok": True}, n)


def test_erreur_rehabillee_par_protocole():
    n = uts.normalize({"jsonrpc": "2.0", "id": 9, "params": {"name": "t"}}, "mcp")
    r = uts.to_protocol_response({"error": "boom"}, n)
    assert r["error"]["code"] == -32000 and r["id"] == 9


def test_dispatch_delegue_au_registre_unique():
    """Le module ne doit JAMAIS executer lui-meme : un 2e chemin contournerait les gardes."""
    vus = {}

    class FakeRegistry:
        async def dispatch(self, tool, args, agent, ring):
            vus.update({"tool": tool, "args": args, "agent": agent, "ring": ring})
            return {"ok": True}

    req = {"id": "x", "tool": "rag", "input": {"q": "z"}}
    out = asyncio.run(uts.dispatch_universal(FakeRegistry(), req, "acp", agent="org", ring=2))
    assert vus == {"tool": "rag", "args": {"q": "z"}, "agent": "org", "ring": 2}
    assert out["ok"] is True


def test_requete_invalide_n_atteint_pas_le_dispatch():
    class Explosive:
        async def dispatch(self, *a, **k):
            raise AssertionError("le dispatch ne doit PAS etre atteint")

    out = asyncio.run(uts.dispatch_universal(Explosive(), {"nope": 1}, "acp"))
    assert "bad_request" in str(out)
