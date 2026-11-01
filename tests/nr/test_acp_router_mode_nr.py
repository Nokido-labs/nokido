"""NR -- T2b : mode fixe a l'ouverture (set_mode seulement si annonce). Faux agent stdio."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402
import forge_acp_client as C  # noqa: E402

FAUX = r'''
import json, sys
def out(o): print(json.dumps(o), flush=True)
rec, modes = sys.argv[1], json.loads(sys.argv[2])
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1}})
    elif meth == "session/new":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s1",
             "modes": {"currentModeId": "auto", "availableModes": [{"id": i} for i in modes]}}})
    elif meth == "session/set_mode":
        open(rec, "a").write(json.dumps(m["params"]) + "\n")
        out({"jsonrpc": "2.0", "id": m["id"], "result": {}})
'''


def _routeur(tmp_path, modes):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    rec = tmp_path / "rec.txt"
    wt = tmp_path / "wt"
    wt.mkdir(exist_ok=True)
    r = R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt),
                    cmd_factory=lambda a: [sys.executable, str(f), str(rec), json.dumps(modes)])
    return r, rec


def _appels(rec):
    return [json.loads(l) for l in rec.read_text().splitlines()] if rec.exists() else []


def _journal(tmp_path, sid):
    p = tmp_path / "logs" / f"{sid}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


def test_table_modes_surs():
    assert R.MODES_SURS == {"claude": "default", "codex": "read-only"}


def test_mode_sur_applique_si_annonce(tmp_path):
    r, rec = _routeur(tmp_path, ["auto", "default"])
    sid = r.ouvrir("claude")
    try:
        assert _appels(rec) == [{"sessionId": "s1", "modeId": "default"}]
    finally:
        r.fermer(sid)


def test_mode_explicite_prioritaire(tmp_path):
    r, rec = _routeur(tmp_path, ["auto", "default", "plan"])
    sid = r.ouvrir("claude", mode="plan")
    try:
        assert _appels(rec) == [{"sessionId": "s1", "modeId": "plan"}]
    finally:
        r.fermer(sid)


def test_mode_non_annonce_jamais_devine(tmp_path):
    r, rec = _routeur(tmp_path, ["auto", "agent"])
    sid = r.ouvrir("codex")
    try:
        assert _appels(rec) == []
        evt = [l for l in _journal(tmp_path, sid) if l["kind"] == "mode_inchange"]
        assert len(evt) == 1
        assert "agent" in json.dumps(evt[0]["payload"]) and "read-only" in json.dumps(evt[0]["payload"])
    finally:
        r.fermer(sid)


def test_set_mode_client(tmp_path):
    r, rec = _routeur(tmp_path, ["x"])
    f = tmp_path / "faux.py"
    cli = C.ACPClient(cmd=[sys.executable, str(f), str(rec), "[]"], cwd=str(tmp_path), permission_timeout=7)
    assert cli.permission_timeout == 7
    cli.start()
    try:
        cli.initialize()
        sid = cli.session_new()
        cli.set_mode(sid, "m1")
    finally:
        cli.close()
    assert _appels(rec) == [{"sessionId": "s1", "modeId": "m1"}]
    assert C.ACPClient(cmd=["x"]).permission_timeout == C.PERMISSION_POLICY_TIMEOUT == 30.0
