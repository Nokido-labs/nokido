"""NR -- colonnes DEDIEES de `tasks` pour la trace de fin de tache (decision owner 23/10).

taille, modele, effort, cout_usd, cout_etat (MESURE|FORFAIT|INCONNU), verdict_effet. Migration additive et
idempotente ; absent = NULL (jamais 0) ; le cout est lu sur la ligne `type=result` AVANT la troncature du result.
Toujours une base sqlite TEMPORAIRE : jamais la base vivante.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as ex  # noqa: E402

COLS = ("taille", "modele", "effort", "cout_usd", "cout_etat", "verdict_effet")


def _base(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, "
                 "result TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO tasks (id, description, agent, status) VALUES ('t1','d','CLAUDE_HEADLESS','running')")
    conn.commit()
    return conn


def _sortie(cout, pad=0):
    d = {"type": "result", "result": "x" * pad}
    if cout is not None:
        d["total_cost_usd"] = cout
    return json.dumps(d)


def test_migration_additive_idempotente(tmp_path):
    conn = _base(tmp_path)
    ex.ensure_trace_schema(conn)
    ex.ensure_trace_schema(conn)  # rejouable
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    assert set(COLS) <= cols
    assert {"id", "description", "agent", "status", "result", "updated_at"} <= cols  # rien supprime
    row = conn.execute("SELECT * FROM tasks WHERE id='t1'").fetchone()
    assert row["description"] == "d"
    assert all(row[c] is None for c in COLS)  # absent = NULL, jamais 0


def test_cout_mesure(tmp_path):
    conn = _base(tmp_path)
    ex.ensure_trace_schema(conn)
    usd, etat = ex._cout_et_etat(ex._cout_claude(_sortie(0.4321)))
    ex.ecrire_trace_tache(conn, "t1", taille="M", modele="m", effort="high", cout_usd=usd, cout_etat=etat,
                          verdict_effet="OK 1 commit")
    r = conn.execute("SELECT * FROM tasks WHERE id='t1'").fetchone()
    assert (r["cout_usd"], r["cout_etat"]) == (0.4321, "MESURE")
    assert (r["taille"], r["modele"], r["effort"], r["verdict_effet"]) == ("M", "m", "high", "OK 1 commit")


def test_cout_forfait_distinct_de_mesure(tmp_path):
    conn = _base(tmp_path)
    ex.ensure_trace_schema(conn)
    usd, etat = ex._cout_et_etat(ex._cout_claude("sortie illisible"))
    assert etat == "FORFAIT" and usd == float(ex._CLAUDE_COUT_INCONNU_USD)
    ex.ecrire_trace_tache(conn, "t1", cout_usd=usd, cout_etat=etat)
    assert conn.execute("SELECT cout_etat FROM tasks").fetchone()[0] == "FORFAIT"


def test_cout_inconnu_reste_null(tmp_path):
    conn = _base(tmp_path)
    ex.ensure_trace_schema(conn)
    ex.ecrire_trace_tache(conn, "t1", taille="S")  # aucun cout fourni
    r = conn.execute("SELECT * FROM tasks WHERE id='t1'").fetchone()
    assert r["cout_usd"] is None and r["cout_etat"] == "INCONNU"
    assert r["modele"] is None and r["effort"] is None  # jamais 0 ni ''


def test_zero_mesure_reste_zero_mesure(tmp_path):
    conn = _base(tmp_path)
    ex.ensure_trace_schema(conn)
    usd, etat = ex._cout_et_etat(0.0)
    ex.ecrire_trace_tache(conn, "t1", cout_usd=usd, cout_etat=etat)
    r = conn.execute("SELECT cout_usd, cout_etat FROM tasks").fetchone()
    assert (r[0], r[1]) == (0.0, "MESURE")


def test_troncature_du_result_sans_perte_du_cout(tmp_path):
    conn = _base(tmp_path)
    ex.ensure_trace_schema(conn)
    sortie = _sortie(1.25, pad=30000)  # result > CAP_RESULTAT
    usd, etat = ex._cout_et_etat(ex._cout_claude(sortie))  # extrait AVANT la troncature
    ex._mark_done(conn, "t1", sortie, True)
    ex.ecrire_trace_tache(conn, "t1", cout_usd=usd, cout_etat=etat)
    r = conn.execute("SELECT result, cout_usd, cout_etat FROM tasks WHERE id='t1'").fetchone()
    assert "TRONQUE" in r["result"]
    assert (r["cout_usd"], r["cout_etat"]) == (1.25, "MESURE")


def test_budget_distingue_mesure_et_forfait(tmp_path):
    f = tmp_path / "claude_headless_budget.json"
    ex._consommer_budget_claude(0.5, jour="2026-10-23", chemin=f)
    j = ex._consommer_budget_claude(None, jour="2026-10-23", chemin=f)["2026-10-23"]
    assert j["mesure_usd"] == 0.5
    assert j["forfait_usd"] == float(ex._CLAUDE_COUT_INCONNU_USD)
    assert j["usd"] == j["mesure_usd"] + j["forfait_usd"] and j["inconnus"] == 1
