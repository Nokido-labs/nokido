"""NR 7/11 : (A) armement limite au SEUL soin d'integrite ; (B) `query` rend les lignes d'EXPLAIN/PRAGMA/WITH/RETURNING.

A : `coagulate(armed_integrite=True)` arme le soin d'integrite (acquittement, depot de reverification plafonne) et RIEN
d'autre : la remediation (orphelins, ports) reste desarmee. Frein `is_human_locked` conserve.
B : handler reel `_handle_query_sync` sur base jetable.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_coagulation as C  # noqa: E402
from nokido_agent.app import forge_remediation as R  # noqa: E402
from tests.nr.test_coagulation_soin_integrite_nr import _acquittes, _brancher, _ev, corps  # noqa: E402,F401

EVS = [dict(_ev("attestation_commit_anterieur", "job_suspect:50221f9ca"), id=1),
       dict(_ev("attestation_commit_anterieur", "job_contredit:50221f9ca"), id=2)]


def test_sans_aucun_armement_rien_n_agit(corps, monkeypatch):
    _brancher(monkeypatch, corps["tmp"], EVS)
    C.coagulate()
    assert not _acquittes(corps["constats"])
    assert corps["depots"] == []


def test_armer_integrite_arme_le_soin_seul(corps, monkeypatch):
    heal = dict(id=3, kind="orphan_process", severity="medium", payload={})
    assert C._triage(heal)[0] == "heal"
    _brancher(monkeypatch, corps["tmp"], EVS + [heal])
    appels = []
    vrai = R.run_remediation_cycle

    def espion(armed=False, lesions=None):
        appels.append((armed, tuple(lesions or ())))
        return vrai(armed=armed, lesions=lesions)

    monkeypatch.setattr(R, "run_remediation_cycle", espion)
    C.coagulate(armed_integrite=True)
    assert ("attestation_commit_anterieur", "job_contredit:50221f9ca") in _acquittes(corps["constats"])
    assert len(corps["depots"]) == 1
    soin = [a for a in appels if a[1] == ("delivery_integrity",)]
    assert soin and all(a[0] is True for a in soin), appels
    autres = [a for a in appels if a[1] != ("delivery_integrity",)]
    assert autres and all(a[0] is False for a in autres), "un autre soin a ete arme : %s" % appels


def test_armer_integrite_garde_le_frein_humain(corps, monkeypatch):
    _brancher(monkeypatch, corps["tmp"], EVS)
    import nokido_agent.app.forge_opsec as OP
    monkeypatch.setattr(OP, "is_human_locked", lambda: True)
    C.coagulate(armed_integrite=True)
    assert not _acquittes(corps["constats"]) and corps["depots"] == []


def test_armer_integrite_garde_le_plafond_de_taches(corps, monkeypatch):
    _brancher(monkeypatch, corps["tmp"], EVS)
    monkeypatch.setattr(R, "REVERIF_MAX_JOUR", 0)
    C.coagulate(armed_integrite=True)
    assert corps["depots"] == [], "le plafond journalier n'a pas retenu la creation de tache"


# ---- B -----------------------------------------------------------------
def _reg(tmp_path):
    from nokido_agent.app.forge_mcp_registry import ToolRegistry
    db = tmp_path / "j.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    c.executemany("INSERT INTO t (v) VALUES (?)", [("a",), ("b",), ("c",)])
    c.commit()
    c.close()
    r = ToolRegistry(tmp_path)
    r.db_path = db
    return r, db


def _q(r, sql):
    return r._handle_query_sync({"sql": sql}, "claude", 2)


def test_query_explain_pragma_with_rendent_leurs_lignes(tmp_path):
    r, _ = _reg(tmp_path)
    for sql in ("EXPLAIN QUERY PLAN SELECT * FROM t WHERE id=1", "PRAGMA table_info(t)",
                "WITH x AS (SELECT * FROM t) SELECT v FROM x"):
        out = _q(r, sql)
        assert out != "Mutation OK" and json.loads(out), (sql, out)


def test_query_returning_rend_et_commit(tmp_path):
    r, db = _reg(tmp_path)
    out = _q(r, "INSERT INTO t (v) VALUES ('d') RETURNING id")
    assert json.loads(out) == [[4]], out
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 4


def test_query_mutation_sans_lignes_inchangee_et_cap(tmp_path, monkeypatch):
    r, db = _reg(tmp_path)
    assert _q(r, "UPDATE t SET v='z' WHERE id=1") == "Mutation OK"
    assert sqlite3.connect(db).execute("SELECT v FROM t WHERE id=1").fetchone()[0] == "z"
    monkeypatch.setenv("FORGE_QUERY_MAX_ROWS", "2")
    out = _q(r, "WITH x AS (SELECT * FROM t) SELECT v FROM x")
    assert len(json.loads(out.split("\n\n[")[0])) == 2 and "tronqu" in out
