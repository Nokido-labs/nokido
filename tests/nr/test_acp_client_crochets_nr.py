"""NR -- crochets on_event / permission_policy d'ACPClient. Faux agent stdio, aucun reseau ni modele."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_client as C  # noqa: E402

FAUX = r'''
import json, sys
def out(o): print(json.dumps(o), flush=True)
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1}})
    elif meth == "session/new":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s1"}})
    elif meth == "session/prompt":
        for u in ({"sessionUpdate": "tool_call", "toolCallId": "t1"},
                  {"sessionUpdate": "plan", "entries": []},
                  {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "hm"}},
                  {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "salut"}}):
            out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1", "update": u}})
        out({"jsonrpc": "2.0", "id": 900, "method": "session/request_permission",
             "params": {"sessionId": "s1", "toolCall": {"toolCallId": "t1"}, "options": [{"optionId": "allow"}]}})
        rep = json.loads(sys.stdin.readline())
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1",
             "update": {"sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "|" + json.dumps(rep["result"]["outcome"])}}}})
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}})
'''


def _run(tmp_path, **kw):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    cli = C.ACPClient(cmd=[sys.executable, str(f)], **kw)
    cli.start()
    try:
        cli.initialize()
        sid = cli.session_new()
        return cli.prompt(sid, "x", timeout=20)
    finally:
        cli.close()


def test_defaut_inchange_permission_cancelled(tmp_path):
    r = _run(tmp_path)
    assert '"cancelled"' in r["text"]
    assert r["text"].startswith("salut")


def test_on_event_recoit_tous_les_types(tmp_path):
    ev = []
    _run(tmp_path, on_event=ev.append)
    kinds = [(e.get("update") or {}).get("sessionUpdate") for e in ev]
    assert kinds[:4] == ["tool_call", "plan", "agent_thought_chunk", "agent_message_chunk"]


def test_on_event_qui_leve_n_interrompt_rien(tmp_path):
    def boom(e):
        raise ValueError("x")
    logs = []
    r = _run(tmp_path, on_event=boom, on_log=logs.append)
    assert r["stopReason"] == "end_turn"
    assert any("on_event" in l for l in logs)


def test_politique_injectee_decide(tmp_path):
    seen = []

    def pol(params):
        seen.append(params)
        return {"outcome": "selected", "optionId": "allow"}
    r = _run(tmp_path, permission_policy=pol)
    assert '"selected"' in r["text"] and '"allow"' in r["text"]
    assert seen and seen[0]["toolCall"]["toolCallId"] == "t1"


def test_politique_qui_leve_est_cancelled(tmp_path):
    def boom(p):
        raise RuntimeError("x")
    logs = []
    r = _run(tmp_path, permission_policy=boom, on_log=logs.append)
    assert '"cancelled"' in r["text"]
    assert any("permission_policy" in l for l in logs)


def test_politique_qui_expire_est_cancelled(tmp_path):
    import time
    C.PERMISSION_POLICY_TIMEOUT = 0.3
    try:
        r = _run(tmp_path, permission_policy=lambda p: time.sleep(3) or {"outcome": "selected"})
    finally:
        C.PERMISSION_POLICY_TIMEOUT = 30.0
    assert '"cancelled"' in r["text"]


def test_politique_au_resultat_illisible_est_cancelled(tmp_path):
    r = _run(tmp_path, permission_policy=lambda p: "oui")
    assert '"cancelled"' in r["text"]
