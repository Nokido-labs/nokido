# -*- coding: utf-8 -*-
"""NR : les taches ANTIGRAVITY de sandbox/tasks.db (lecture seule) apparaissent dans /acp, au format du journal."""
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web_hub import acp_harness, acp_views

SCHEMA = ("CREATE TABLE tasks (id TEXT, description TEXT, agent TEXT, status TEXT, result TEXT, "
          "created_at TEXT, updated_at TEXT, job_id TEXT, reaffectations INTEGER)")


@pytest.fixture
def env(tmp_path, monkeypatch):
    logs, perms = tmp_path / "logs", tmp_path / "perms"
    for d in (logs, perms):
        d.mkdir()
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute(SCHEMA)
    con.commit()
    con.close()
    monkeypatch.setattr(acp_views, "LOG_DIR", logs)
    monkeypatch.setattr(acp_views, "PERMISSIONS_DIR", perms)
    monkeypatch.setattr(acp_views, "TASKS_DB", db, raising=False)
    app = FastAPI()
    app.include_router(acp_views.router)
    return TestClient(app), db


def _t(db, id, desc="bonjour", agent="ANTIGRAVITY", status="done", result="salut", job_id=None,
       c="1000", u="1005"):
    con = sqlite3.connect(db)
    con.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,0)", (id, desc, agent, status, result, c, u, job_id))
    con.commit()
    con.close()


def test_session_projetee(env):
    c, db = env
    _t(db, "t1", job_id="job_ab12")
    s = [x for x in c.get("/api/acp/sessions").json()["sessions"] if x["session"] == "agy-job_ab12"]
    assert len(s) == 1 and s[0]["agent"] == "agy" and s[0]["lignes"] == 4
    d = c.get("/api/acp/sessions/agy-job_ab12").json()
    assert [l["kind"] for l in d["lignes"]] == ["ouverte", "prompt", "reponse", "fermee"]
    assert all(set(l) == {"ts", "session", "agent", "kind", "payload"} for l in d["lignes"])
    assert d["lignes"][1]["payload"]["send"] == "bonjour"
    assert d["lignes"][2]["payload"]["output"] == "salut"
    assert d["lignes"][3]["ts"] == 1005.0


def test_id_sans_job_id_et_autres_agents_exclus(env):
    c, db = env
    _t(db, "t9")
    _t(db, "x1", agent="CODEX")
    ids = [x["session"] for x in c.get("/api/acp/sessions").json()["sessions"]]
    assert ids == ["agy-t9"]
    assert c.get("/api/acp/sessions/agy-x1").status_code == 404


def test_en_cours_sans_fermee(env):
    c, db = env
    _t(db, "r", status="running", result=None)
    d = c.get("/api/acp/sessions/agy-r").json()
    assert [l["kind"] for l in d["lignes"]] == ["ouverte", "prompt"]
    assert d["etat"] == "EN_COURS"


@pytest.mark.parametrize("st", ["failed", "completed", "DONE"])
def test_statuts_terminaux(env, st):
    c, db = env
    _t(db, "f", status=st, result=None)
    d = c.get("/api/acp/sessions/agy-f").json()
    assert d["lignes"][-1]["kind"] == "fermee"


def test_payload_caviarde(env, monkeypatch):
    c, db = env
    monkeypatch.setattr(acp_harness, "_caviarder", lambda t: t.replace("SECRET", "***"))
    _t(db, "s", desc="mon SECRET", result="SECRET encore")
    txt = json.dumps(c.get("/api/acp/sessions/agy-s").json())
    assert "SECRET" not in txt and "***" in txt


def test_base_illisible_dite(env, tmp_path, monkeypatch):
    c, _ = env
    monkeypatch.setattr(acp_views, "TASKS_DB", tmp_path / "absente.db")
    s = c.get("/api/acp/sessions").json()["sessions"]
    assert len(s) == 1 and s[0]["etat"] == "ILLISIBLE"
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"pas une base sqlite" * 100)
    monkeypatch.setattr(acp_views, "TASKS_DB", bad)
    s = c.get("/api/acp/sessions").json()["sessions"]
    assert len(s) == 1 and s[0]["etat"] == "ILLISIBLE"
    assert c.get("/api/acp/sessions/agy-zz").json()["etat"] == "ILLISIBLE"


def test_50_plus_recents(env):
    c, db = env
    for i in range(60):
        _t(db, f"n{i:02d}")
    ids = [x["session"] for x in c.get("/api/acp/sessions").json()["sessions"]]
    assert len(ids) == 50 and "agy-n59" in ids and "agy-n09" not in ids


def test_resultat_borne_et_tronque_dit(env):
    c, db = env
    _t(db, "big", result="x" * (3 * 1024 * 1024))
    d = c.get("/api/acp/sessions/agy-big").json()
    rep = d["lignes"][2]["payload"]
    assert rep["tronque"] is True and len(rep["output"]) <= 2 * 1024 * 1024
    assert len(json.dumps(c.get("/api/acp/sessions").json())) < 2 * 1024 * 1024


def test_lecture_seule(env):
    _, db = env
    con = acp_harness._ouvrir(db)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO tasks (id) VALUES ('w')")
    con.close()


def test_plan_sans_scan_de_table(env):
    _, db = env
    con = acp_harness._ouvrir(db)
    plan = " | ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + acp_harness.REQUETE_RECENTES,
                                                (acp_harness.FENETRE, acp_harness.MAX_JOBS, 1000, 1000)))
    con.close()
    assert "SEARCH" in plan and "SCAN" not in plan, plan


def test_pas_de_permission_agy_et_page(env):
    c, db = env
    _t(db, "p")
    assert c.get("/api/acp/permissions").json()["permissions"] == []
    page = c.get("/acp").text
    assert "AGY" in page and "permission" in page.lower()


def test_id_agy_traversant(env):
    c, _ = env
    assert c.get("/api/acp/sessions/agy-a..b").status_code == 400


def test_organe_declare():
    assert acp_harness.__FORGE_COLOR__
