"""NR : dedup du swarm pointeur (voie unique meta + primitives partagees). Faux transport, aucun reseau."""
from __future__ import annotations

import email.message
import inspect
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import forge_handoff  # noqa: E402
import forge_cli_swarm  # noqa: E402
import forge_tool_call_probe as probe  # noqa: E402


def _agent():
    return forge_handoff.Agent(name="m", instructions="i", tools=[], model="gpt-x",
                               text_handoff=False, provider="groq_fast")


def test_meta_porte_finish_reason_et_raisonnement(monkeypatch):
    class S:
        appeler_avec_outils = staticmethod(lambda *a, **k: {
            "choices": [{"message": {"content": ""}}], "_finish_reason": "length", "_raisonnement_car": 300})
    monkeypatch.setattr(forge_handoff, "_cloud_slot_info", lambda p: ("http://x/v1", "k", ["gpt-x"]))
    monkeypatch.setattr(forge_handoff, "_sonde", lambda: S)
    r = forge_handoff._call_cloud_with_tools(_agent(), "groq_fast", [{"role": "user", "content": "q"}], [])
    assert r["_router_meta"]["finish_reason"] == "length"
    assert r["_router_meta"]["raisonnement_car"] == 300


def test_meta_429_retry_after(monkeypatch):
    h = email.message.Message()
    h["Retry-After"] = "7"

    def faux(*a, **k):
        raise urllib.error.HTTPError("http://x", 429, "rate", h, None)

    class S:
        appeler_avec_outils = staticmethod(faux)
        _retry_after = staticmethod(probe._retry_after)
    monkeypatch.setattr(forge_handoff, "_cloud_slot_info", lambda p: ("http://x/v1", "k", ["gpt-x"]))
    monkeypatch.setattr(forge_handoff, "_sonde", lambda: S)
    r = forge_handoff._call_cloud_with_tools(_agent(), "groq_fast", [{"role": "user", "content": "q"}], [])
    assert r["_router_meta"]["http"] == 429
    assert r["_router_meta"]["retry_after"] == 7.0


def test_sonde_sans_canal_thread_local():
    assert not hasattr(probe, "derniere_lecture")
    assert not hasattr(probe, "dernier_retry_after")


def test_boucle_membre_sans_duplication():
    src = inspect.getsource(forge_cli_swarm._boucle_membre)
    assert "ERR: tool not found" not in src
    assert "tool_call_id" not in src


def test_executer_appel():
    def ok(a="0"):
        return "R" + a

    def boom():
        raise ValueError("zut")

    nom, res, ids = forge_handoff._executer_appel(
        {"id": "i1", "function": {"name": "ok", "arguments": '{"a":"1"}'}}, [ok])
    assert (nom, res, ids) == ("ok", "R1", {"tool_call_id": "i1"})
    _n, res, ids = forge_handoff._executer_appel({"function": {"name": "nope", "arguments": "{}"}}, [ok])
    assert res == "ERR: tool not found" and ids == {}
    _n, res, _i = forge_handoff._executer_appel({"function": {"name": "ok", "arguments": "{pas json"}}, [ok])
    assert res == "R0"
    _n, res, _i = forge_handoff._executer_appel({"function": {"name": "boom", "arguments": "{}"}}, [boom])
    assert res == "ERR: ValueError: zut"


def test_message_assistant():
    tcs = [{"id": "a", "function": {"name": "f", "arguments": None}}]
    assert forge_handoff._message_assistant("c", tcs) == {
        "role": "assistant", "content": "c",
        "tool_calls": [{"id": "a", "function": {"name": "f", "arguments": "{}"}}]}
    assert forge_handoff._message_assistant("c", [{"function": {"name": "f"}}]) == {
        "role": "assistant", "content": "c"}
