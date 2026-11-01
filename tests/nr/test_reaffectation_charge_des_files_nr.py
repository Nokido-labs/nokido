"""NR -- _reaffecter tient compte de la charge des files (22/10 : 3 reaffectations toutes vers GPTOSS, 5 en file,
pendant que GLM etait LIBRE) en gardant « meme fichier = meme file »."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
ORDRE = ("OPENCODE_GPTOSS", "OPENCODE_GLM")


def _base(monkeypatch, tmp_path, desc_file_gptoss="tache sur tools/autre_chose.py"):
    spec = importlib.util.spec_from_file_location("charge_files_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, classe TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t_new','OPENCODE_NEMOTRON','running','modifier tools/foo.py','S:ecrit')")
    for i in range(5):
        d = desc_file_gptoss if i == 0 else "tache sur tools/bar%d.py" % i
        c.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", ("g%d" % i, "OPENCODE_GPTOSS",
                                                          "running" if i == 0 else "pending", d, "S:ecrit"))
    c.commit()
    c.close()
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(tmp_path / "coupe_circuit.json"))
    monkeypatch.setattr(m, "executeur_en_repos", lambda *a, **k: None)
    monkeypatch.setattr(m, "TASKS_DB", db)
    monkeypatch.setattr(m, "_executeur_bat", lambda a, max_age_s=None: True)
    monkeypatch.setattr(m, "_executeur_suspendu", lambda a: None)
    return m, db


def _agent(db):
    return sqlite3.connect(str(db)).execute("SELECT agent FROM tasks WHERE id='t_new'").fetchone()[0]


def test_va_a_la_file_la_plus_courte(monkeypatch, tmp_path):
    m, db = _base(monkeypatch, tmp_path)
    task = {"id": "t_new", "agent": "OPENCODE_NEMOTRON", "description": "modifier tools/foo.py"}
    assert m._reaffecter(task, "panne", ordre=ORDRE) == "OPENCODE_GLM"
    assert _agent(db) == "OPENCODE_GLM"


def test_meme_fichier_reste_dans_la_meme_file(monkeypatch, tmp_path):
    m, db = _base(monkeypatch, tmp_path, desc_file_gptoss="editer tools/foo.py")
    task = {"id": "t_new", "agent": "OPENCODE_NEMOTRON", "description": "modifier tools/foo.py"}
    assert m._reaffecter(task, "panne", ordre=ORDRE) == "OPENCODE_GPTOSS"
    assert _agent(db) == "OPENCODE_GPTOSS"
