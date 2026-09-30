"""Tests du client supervisor — résolution token (guichet) + header auth.

Couvre le fix 2026-05-29 : le client était antérieur au gate auth Phase 23A
(POST /supervisor/* → 401). Il lit LAFORGE_SUPERVISOR_TOKEN sinon FORGE_MCP_TOKEN,
et envoie le header brut.

HERMETIQUE depuis le 2026-09-28 (2b-5). L'ancienne version patchait un faux coffre
sous un AUTRE nom que celui qu'importe le module : elle lisait le VRAI jeton au coffre,
echouait, et pytest AFFICHAIT un fragment de sa valeur dans le rapport. Le guichet est
desormais simule, et chaque comparaison est reduite a un booleen AVANT l'assert.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import forge_supervisor_ctl as sc  # type: ignore[import-not-found]


def _guichet(monkeypatch, store):
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))


def test_token_supervisor_priority(monkeypatch):
    _guichet(monkeypatch, {"LAFORGE_SUPERVISOR_TOKEN": "TOK_SUP", "FORGE_MCP_TOKEN": "TOK_MCP"})
    ok = sc._token() == "TOK_SUP"
    assert ok


def test_token_mcp_fallback(monkeypatch):
    _guichet(monkeypatch, {"FORGE_MCP_TOKEN": "TOK_MCP"})
    ok = sc._token() == "TOK_MCP"
    assert ok


def test_token_absent_returns_empty(monkeypatch):
    _guichet(monkeypatch, {})
    ok = sc._token() == ""
    assert ok


def test_token_guichet_illisible_returns_empty(monkeypatch):
    fs = importlib.import_module("nokido_agent.app.forge_secrets")

    def _panne(k, required=False):
        raise OSError("guichet illisible (simule)")

    monkeypatch.setattr(fs, "get_secret", _panne)
    ok = sc._token() == ""
    assert ok


class _FakeResp:
    status = 200

    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_call_adds_raw_auth_header(monkeypatch):
    monkeypatch.setattr(sc, "_token", lambda: "ABC123")
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["auth"] = req.get_header("Authorization")
        captured["method"] = req.get_method()
        return _FakeResp()

    monkeypatch.setattr(sc.urllib.request, "urlopen", fake_urlopen)
    st, body = sc._call("/supervisor/restart/NokidoSearxng", method="POST")
    assert st == 200
    assert captured["auth"] == "ABC123"  # token brut, pas "Bearer ..."
    assert captured["method"] == "POST"


def test_call_no_token_no_header(monkeypatch):
    monkeypatch.setattr(sc, "_token", lambda: "")
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResp()

    monkeypatch.setattr(sc.urllib.request, "urlopen", fake_urlopen)
    sc._call("/supervisor/status")
    assert captured["auth"] is None
