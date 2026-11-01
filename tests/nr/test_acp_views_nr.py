# -*- coding: utf-8 -*-
"""NR T3 : front ACP du web hub (sessions, flux, permissions)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web_hub import acp_views

PID = "0123456789abcdef0123456789abcdef"  # forme reelle d'un identifiant de la file (uuid4().hex)


@pytest.fixture
def env(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    perms = tmp_path / "perms"
    logs.mkdir()
    perms.mkdir()
    monkeypatch.setattr(acp_views, "LOG_DIR", logs)
    monkeypatch.setattr(acp_views, "PERMISSIONS_DIR", perms)
    import sys
    from pathlib import Path
    tools = str(Path(acp_views.__file__).resolve().parents[2] / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import forge_acp_router as R
    monkeypatch.setattr(R._importer_hub(), "cle_signature", lambda: None)  # cle illisible : signature par le hub
    monkeypatch.setattr(R, "signer_par_hub", lambda jeton, **k: (lambda payload: "a.b.c"))
    app = FastAPI()
    app.include_router(acp_views.router)
    return app, logs, perms


def _journal(logs, sid, n, agent="claude"):
    with open(logs / f"{sid}.jsonl", "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"ts": 100.0 + i, "session": sid, "agent": agent,
                                "kind": "msg", "payload": {"i": i}}) + "\n")


def _perm(perms, pid, etat="EN_ATTENTE"):
    (perms / f"{pid}.json").write_text(json.dumps({
        "id": pid, "session": "s1", "agent": "claude", "ts": 1.0, "request": {},
        "options": [{"optionId": "allow"}, {"optionId": "deny"}],
        "etat": etat, "decision": None}), encoding="utf-8")


def test_sessions_liste(env):
    app, logs, _ = env
    _journal(logs, "s1", 5)
    r = TestClient(app).get("/api/acp/sessions")
    assert r.status_code == 200
    s = r.json()["sessions"][0]
    assert (s["session"], s["agent"], s["lignes"], s["dernier_ts"]) == ("s1", "claude", 5, 104.0)


def test_session_n_dernieres(env):
    app, logs, _ = env
    _journal(logs, "s1", 50)
    d = TestClient(app).get("/api/acp/sessions/s1?n=3").json()
    assert [l["payload"]["i"] for l in d["lignes"]] == [47, 48, 49]


def test_gros_journal_lecture_bornee(env):
    app, logs, _ = env
    _journal(logs, "big", 60000)
    assert (logs / "big.jsonl").stat().st_size > 2 * 1024 * 1024
    d = TestClient(app).get("/api/acp/sessions/big?n=2").json()
    assert [l["payload"]["i"] for l in d["lignes"]] == [59998, 59999]


def test_lecture_queue_octets_lus_bornes(tmp_path, monkeypatch):
    _journal(tmp_path, "x", 60000)
    lus = []
    ouvrir = open

    class F:
        def __init__(self, f):
            self.f = f

        def __getattr__(self, k):
            return getattr(self.f, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self.f.__exit__(*a)

        def read(self, *a):
            b = self.f.read(*a)
            lus.append(len(b))
            return b
    monkeypatch.setattr(acp_views, "open", lambda *a, **k: F(ouvrir(*a, **k)), raising=False)
    out = acp_views._lire_queue(tmp_path / "x.jsonl", 5)
    assert len(out) == 5
    assert lus and sum(lus) <= 2 * 1024 * 1024


def test_id_traversee(env):
    app, _, _ = env
    c = TestClient(app)
    assert c.get("/api/acp/sessions/a..b").status_code == 400
    assert c.get("/api/acp/sessions/a%5Cb").status_code == 400
    assert c.get("/api/acp/sessions/a%2Fb").status_code in (400, 404)


def test_permissions_en_attente(env):
    app, _, perms = env
    _perm(perms, "p1")
    _perm(perms, "p2", etat="DECIDE")
    d = TestClient(app).get("/api/acp/permissions").json()
    assert [p["id"] for p in d["permissions"]] == ["p1"]


def test_post_sans_jeton_401_meme_loopback(env):
    app, _, perms = env
    _perm(perms, "p1")
    c = TestClient(app, client=("127.0.0.1", 5555))
    assert c.post("/api/acp/permissions/p1", json={"option": "allow"}).status_code == 401
    assert json.loads((perms / "p1.json").read_text())["etat"] == "EN_ATTENTE"


def test_post_admin(env, monkeypatch):
    app, _, perms = env
    monkeypatch.setattr(acp_views, "_est_admin", lambda request: True)
    _perm(perms, PID)  # la file ne produit que des uuid4 hex (decider les exige depuis 7fc7b367b)
    r = TestClient(app).post(f"/api/acp/permissions/{PID}", json={"option": "allow"})
    assert r.status_code == 200
    j = json.loads((perms / f"{PID}.json").read_text())
    assert j["etat"] == "DECIDE" and j["decision"]["optionId"] == "allow"


def test_post_refuser(env, monkeypatch):
    app, _, perms = env
    monkeypatch.setattr(acp_views, "_est_admin", lambda request: True)
    _perm(perms, PID)
    assert TestClient(app).post(f"/api/acp/permissions/{PID}", json={"refuser": True}).status_code == 200
    assert json.loads((perms / f"{PID}.json").read_text())["decision"] == {"outcome": "cancelled"}


def test_post_option_inconnue_400(env, monkeypatch):
    app, _, perms = env
    monkeypatch.setattr(acp_views, "_est_admin", lambda request: True)
    _perm(perms, "p1")
    assert TestClient(app).post("/api/acp/permissions/p1", json={"option": "evil"}).status_code == 400
    assert json.loads((perms / "p1.json").read_text())["etat"] == "EN_ATTENTE"


def test_post_id_traversant_400(env, monkeypatch):
    app, _, _ = env
    monkeypatch.setattr(acp_views, "_est_admin", lambda request: True)
    c = TestClient(app)
    assert c.post("/api/acp/permissions/a..b", json={"refuser": True}).status_code == 400
    assert c.post("/api/acp/permissions/a%5Cb", json={"refuser": True}).status_code == 400


def test_page_sans_innerhtml(env):
    app, _, _ = env
    r = TestClient(app).get("/acp")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "innerHTML" not in r.text
    assert "textContent" in r.text and "setInterval" in r.text and "3000" in r.text
    assert 'src="http' not in r.text


def test_est_admin_defaut_refuse_sans_jeton():
    from starlette.requests import Request
    req = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1), "method": "POST",
                   "path": "/", "query_string": b""})
    assert acp_views._est_admin(req) is False
