# -*- coding: utf-8 -*-
"""NR 7/11 10:29-10:41 : le harness endormi pendant qu'une tache CLAUDE_HEADLESS attend ne doit ni etre endormi par le
regulateur (demande heritee de l'executeur) ni faire echouer la tache (BLOQUE_PAR_DEPENDANCE n'est pas DEAD)."""
import datetime
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as R  # noqa: E402
import forge_task_executor as T  # noqa: E402


def test_demande_harness_heritee_des_executeurs_harness(monkeypatch):
    agents = {"NokidoTaskExecutorClaude": "CLAUDE_HEADLESS", "NokidoTaskExecutorMistral": "MISTRAL",
              "NokidoTaskExecutorAgy": "AGY"}
    monkeypatch.setattr(R, "_agent_du_service", lambda s: agents.get(s))
    monkeypatch.setattr(R, "_taches_de_l_agent", lambda a: 1 if a == "CLAUDE_HEADLESS" else 0)
    assert R._demande_du_service("NokidoHarnessWorker") is True
    monkeypatch.setattr(R, "_taches_de_l_agent", lambda a: 0)
    assert R._demande_du_service("NokidoHarnessWorker") is False  # absence prouvee : on peut dormir
    monkeypatch.setattr(R, "_taches_de_l_agent", lambda a: None)
    assert R._demande_du_service("NokidoHarnessWorker") is None   # illisible : jamais un NO


def _base(tmp_path, monkeypatch):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, result TEXT, "
              "reaffectations TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t1','CLAUDE_HEADLESS','running','RESERVE A CLAUDE_HEADLESS x',NULL,NULL)")
    c.commit()
    c.close()
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(db))
    monkeypatch.delenv("LAFORGE_HARNESS_POULS_IGNORE", raising=False)
    hb = tmp_path / "hb"
    ts = (datetime.datetime.now() - datetime.timedelta(seconds=721)).isoformat(timespec="seconds")
    hb.write_text(json.dumps({"ts": ts, "pid": 1}), encoding="utf-8")
    monkeypatch.setattr(T, "_HARNESS_HEARTBEAT", hb)
    monkeypatch.setattr(T, "_HARNESS_ATTENTE", tmp_path / "attente.json", raising=False)
    appels = []
    monkeypatch.setattr(T, "_hub_call", lambda tool, args, token, timeout=120: appels.append((tool, args)) or {})
    return db, appels


def _statut(db):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT status FROM tasks WHERE id='t1'").fetchone()[0]
    finally:
        c.close()


def test_harness_endormi_tache_reservee_reste_pending(tmp_path, monkeypatch):
    db, appels = _base(tmp_path, monkeypatch)
    T._delegate_to_claude({"id": "t1", "agent": "CLAUDE_HEADLESS",
                           "description": "RESERVE A CLAUDE_HEADLESS x"}, "tok")
    assert _statut(db) == "pending"
    assert any(t == "nokido_ensure_service" and a.get("service") == "NokidoHarnessWorker" for t, a in appels)


def test_harness_endormi_au_dela_de_la_duree_echec_explicite(tmp_path, monkeypatch):
    db, _ = _base(tmp_path, monkeypatch)
    vieux = datetime.datetime.now().timestamp() - T._HARNESS_ATTENTE_MAX_S - 5
    T._HARNESS_ATTENTE.write_text(json.dumps({"t1": vieux}), encoding="utf-8")
    clos = []
    monkeypatch.setattr(T, "_clore_delegation", lambda tid, tok, ok, detail, intent=None: clos.append((ok, detail)))
    T._delegate_to_claude({"id": "t1", "agent": "CLAUDE_HEADLESS",
                           "description": "RESERVE A CLAUDE_HEADLESS x"}, "tok")
    assert clos and clos[0][0] is False
    assert T.classer_cause_echec(clos[0][1]) == "HARNESS_WORKER"
