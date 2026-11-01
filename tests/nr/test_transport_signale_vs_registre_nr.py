# -*- coding: utf-8 -*-
"""NR phase 2a : transport_declare_registre (registre) et transport_signale (declare par le client) distincts.

__FORGE_COLOR__ = "immunitaire/guard : le transport signale ne remplace jamais le registre"
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _req(headers):
    return SimpleNamespace(headers=headers)


def test_pont_signale_stdio_bridge():
    import nokido_hub as h
    assert h._transport_signale(_req({"X-Transport": "stdio-bridge/3.1"})) == "STDIO_BRIDGE"


def test_une_seule_fonction_pas_de_observe():
    import nokido_hub as h
    assert not hasattr(h, "_transport_observe")


def test_tous_les_appels_log_network_de_mcp_post_transmettent_request():
    """Cause de INCONNU : _log_network appele sans request= (IN/OUT) -> signale INCONNU."""
    tree = ast.parse((ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8"))
    mcp_post = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "mcp_post")
    calls = [c for c in ast.walk(mcp_post) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "_log_network"]
    assert calls
    for c in calls:
        assert "request" in {k.arg for k in c.keywords}, f"ligne {c.lineno}"


def test_set_actor_champs_distincts():
    from forge_trace_context import set_actor, get_actor, reset_actor
    tok = set_actor("CLAUDE-DESKTOP", principal="P", ring=1, channel="HTTP_DIRECT",
                    transport="HTTP_DIRECT", transport_signale="STDIO_BRIDGE",
                    client_process="claude.exe")
    try:
        a = get_actor()
        assert a["transport_declare_registre"] == "HTTP_DIRECT"
        assert a["transport_signale"] == "STDIO_BRIDGE"
        assert "transport_observe" not in a and "transport_declare" not in a
        assert a["principal"] == "P" and a["ring"] == 1
        assert a["client_process"] == "claude.exe"
    finally:
        reset_actor(tok)


def test_set_actor_defaut_inconnu():
    from forge_trace_context import set_actor, get_actor, reset_actor
    tok = set_actor("X")
    try:
        assert get_actor()["transport_signale"] == "INCONNU"
    finally:
        reset_actor(tok)


def test_pont_aucun_sous_processus(monkeypatch):
    import mcp_stdio_bridge as b

    def _boom(*a, **k):
        raise AssertionError("sous-processus interdit")
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(b, "_CLIENT_PROC", None)
    name = b._parent_process_name()
    assert isinstance(name, str) and name and name != "INCONNU"
    assert "X-Client-Process" in b._headers()


def test_pont_echec_lecture_inconnu(monkeypatch):
    import mcp_stdio_bridge as b

    def _ko():
        raise OSError("x")
    monkeypatch.setattr(b.os, "getppid", _ko)
    assert b._parent_process_name() == "INCONNU"
