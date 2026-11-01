"""NR -- bug_juge_ok_done_sans_effet_mistral_20261024 : la voie Vibe calculait l'effet observe sans l'ECRIRE
(verdict_effet NULL) ; un RIEN_PRODUIT doit donner un echec explicite ET un verdict_effet ecrit, par UNE fonction
partagee. Chemin reel de `_delegate_to_vibe`, faux client harness, depot git temporaire, aucun reseau."""
import inspect
import os
import sqlite3
import subprocess
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_task_executor as T  # noqa: E402


def _git(wt, *a):
    subprocess.run(["git", "-C", str(wt), *a], check=True, capture_output=True)


def test_vibe_ok_done_sans_commit_est_echec_et_verdict_ecrit(monkeypatch, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "a@b.c")
    _git(wt, "config", "user.name", "t")
    (wt / "a.txt").write_text("x", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "init")
    dbp = tmp_path / "tasks.db"
    c = sqlite3.connect(str(dbp))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, description TEXT, status TEXT, "
              "result TEXT, updated_at TEXT)")
    c.execute("INSERT INTO tasks (id, agent, description, status) "
              "VALUES ('job_x','MISTRAL','faire quelque chose','running')")
    c.commit()
    T.ensure_trace_schema(c)
    c.close()
    monkeypatch.setattr(T, "TASKS_DB", dbp)
    monkeypatch.setattr(T, "_HARNESS_JOBS", tmp_path / "jobs")
    monkeypatch.setattr(T, "_workdir_vibe", lambda: wt)
    monkeypatch.setattr(T, "_modele_hors_quota", lambda *a, **k: None)
    monkeypatch.setattr(T, "_cle_mistral_au_coffre", lambda: True)
    monkeypatch.setattr(T, "_config_mcp_vibe", lambda w: None)
    monkeypatch.setattr(T, "_args_vibe", lambda *a, **k: ["x"])
    monkeypatch.setattr(T, "_attendre_harness",
                        lambda *a, **k: {"ok": True, "output": '{"intent":"OK_DONE","pointer_ref":""}'})
    monkeypatch.setattr(T, "_hub_call", lambda *a, **k: {})
    monkeypatch.setattr(T, "_reaffecter", lambda *a, **k: None)
    monkeypatch.setattr(T, "_consigner_verdict_auto", lambda *a, **k: None)
    monkeypatch.setenv("NOKIDO_BUS_TACHES", "0")
    task = {"id": "job_x", "agent": "MISTRAL", "description": "faire quelque chose"}
    T._delegate_to_vibe(task, "tok")
    r = sqlite3.connect(str(dbp)).execute("SELECT status, verdict_effet FROM tasks WHERE id='job_x'").fetchone()
    assert r[0] == "failed", r
    assert r[1], r


def test_toutes_les_voies_passent_par_la_fonction_partagee():
    for f in (T._delegate_to_agy, T._delegate_to_codex, T._delegate_to_vibe,
              T._delegate_to_claude, T._delegate_to_opencode):
        assert "_finaliser_effet(" in inspect.getsource(f), f.__name__


def test_finaliser_effet_force_l_echec_sur_rien_produit(monkeypatch, tmp_path):
    dbp = tmp_path / "t.db"
    c = sqlite3.connect(str(dbp))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT)")
    c.execute("INSERT INTO tasks VALUES ('j','running')")
    T.ensure_trace_schema(c)
    c.close()
    monkeypatch.setattr(T, "TASKS_DB", dbp)
    assert T._finaliser_effet("j", True, "x ; [RIEN PRODUIT] (RIEN_PRODUIT) y") is False
    assert T._finaliser_effet("j", True, "2 commits") is True
    assert sqlite3.connect(str(dbp)).execute("SELECT verdict_effet FROM tasks").fetchone()[0] == "2 commits"
