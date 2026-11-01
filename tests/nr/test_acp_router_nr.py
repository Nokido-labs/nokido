"""NR -- routeur ACP multi-sessions. Faux agent stdio, aucun vrai CLI, aucun reseau."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402
from forge_acp_client import SessionBusyError  # noqa: E402

TEMOIN = "ghp_" + "Zq7" * 12  # fabrique a l'execution, comme test_jeton_jamais_journalise_nr

FAUX = r'''
import json, sys, time
def out(o): print(json.dumps(o), flush=True)
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1}})
    elif meth == "session/new":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s1"}})
    elif meth == "session/prompt":
        txt = m["params"]["prompt"][0]["text"]
        if txt == "lent":
            time.sleep(1.5)
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1",
             "update": {"sessionUpdate": "tool_call", "toolCallId": "t1", "note": "Authorization: Bearer " + sys.argv[1]}}})
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1",
             "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "re:" + txt}}}})
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}})
'''


@pytest.fixture
def routeur(tmp_path):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    r = R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt),
                    cmd_factory=lambda agent: [sys.executable, str(f), TEMOIN])
    yield r
    for i in list(r.lister()):
        r.fermer(i["id"])


def _lignes(tmp_path, sid):
    p = tmp_path / "logs" / f"{sid}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


def test_color():
    assert R.__FORGE_COLOR__ == "systeme_nerveux/routeur ACP multi-sessions"


def test_ouvrir_envoyer_journal(routeur, tmp_path):
    sid = routeur.ouvrir("gemini")
    r = routeur.envoyer(sid, "bonjour", timeout=20)
    assert r["text"] == "re:bonjour"
    lg = _lignes(tmp_path, sid)
    assert all({"ts", "session", "agent", "kind", "payload"} <= set(l) for l in lg)
    assert all(l["session"] == sid and l["agent"] == "gemini" for l in lg)
    assert "tool_call" in [l["kind"] for l in lg]
    assert TEMOIN not in (tmp_path / "logs" / f"{sid}.jsonl").read_text(encoding="utf-8")


def test_lister_et_fermer(routeur):
    a = routeur.ouvrir("gemini")
    b = routeur.ouvrir("gemini")
    assert a != b
    assert {x["id"] for x in routeur.lister()} == {a, b}
    routeur.fermer(a)
    assert {x["id"] for x in routeur.lister()} == {b}
    with pytest.raises(KeyError):
        routeur.envoyer(a, "x", timeout=5)


def test_session_occupee(routeur):
    sid = routeur.ouvrir("gemini")
    t = threading.Thread(target=lambda: routeur.envoyer(sid, "lent", timeout=20))
    t.start()
    import time
    for _ in range(50):
        if routeur.lister()[0].get("occupee"):
            break
        time.sleep(0.05)
    with pytest.raises(SessionBusyError):
        routeur.envoyer(sid, "autre", timeout=5)
    t.join()


def test_agy_hors_acp(routeur):
    with pytest.raises(R.HorsACPError) as e:
        routeur.ouvrir("agy")
    assert "HORS_ACP" in str(e.value)
    assert routeur.lister() == []


def test_sans_worktree_refus_explicite(tmp_path):
    def non(a):
        raise RuntimeError("pas de worktree")
    r = R.ACPRouter(log_dir=tmp_path / "l", route=non, cmd_factory=lambda a: [sys.executable, "-c", ""])
    with pytest.raises(R.CwdIndisponibleError):
        r.ouvrir("gemini")


def test_permission_par_defaut_cancelled_et_politique_injectable(tmp_path):
    r = R.ACPRouter(log_dir=tmp_path, route=lambda a: str(tmp_path), cmd_factory=lambda a: ["x"])
    assert r.permission_policy({"x": 1}) == {"outcome": "cancelled"}
    r2 = R.ACPRouter(log_dir=tmp_path, route=lambda a: str(tmp_path), cmd_factory=lambda a: ["x"],
                     permission_policy=lambda p: {"outcome": "selected", "optionId": "a"})
    assert r2.permission_policy({})["outcome"] == "selected"
