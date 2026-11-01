"""NR 29/10 -- une consigne deleguee « tasks.db, id job_X, champ description » est INATTEIGNABLE pour l'agent (sandbox/
ignore donc absent du worktree de tache, bash refuse, SQLite illisible par read) : DEFAUT3/5 ont passe leurs tours a
chercher tasks.db (journal OpenCode, runs 519ef053, 6707ce61) -> RIEN_PRODUIT. L'executeur RESOUT le pointeur avant
l'envoi ; un pointeur introuvable est DIT a l'agent (« ne pas chercher tasks.db »), jamais laisse a sa recherche.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)]

import forge_task_executor as E  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture()
def bus(tmp_path, monkeypatch):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT)")
    c.execute("INSERT INTO tasks VALUES ('job_169ca7e4_1793285194_claude_task_assign', "
              "'audit lot 3 : R7 et R9, artefact sandbox/audit/run-8-lot3/findings.json')")
    c.execute("INSERT INTO tasks VALUES ('job_aaaa0001_1_claude_task_assign', "
              "'REPRISE : tasks.db, id job_169ca7e4_1793285194_claude_task_assign, champ description')")
    c.commit()
    c.close()
    monkeypatch.setattr(E, "_db", lambda: sqlite3.connect(db))
    return db


def test_pointeur_resolu_en_ligne(bus):
    d = E._resoudre_pointeurs_consigne(
        "REPRISE. Consigne INTEGRALE : tasks.db, id job_169ca7e4_1793285194_claude_task_assign, champ description.")
    assert "audit lot 3 : R7 et R9" in d and "tasks.db:job_169ca7e4" in d


def test_pointeur_en_chaine_resolu(bus):
    d = E._resoudre_pointeurs_consigne("voir tasks.db, id job_aaaa0001_1_claude_task_assign, champ description")
    assert "audit lot 3 : R7 et R9" in d


def test_pointeur_introuvable_dit_a_l_agent(bus):
    d = E._resoudre_pointeurs_consigne("tasks.db, id job_inexistant_0, champ description")
    assert "INRESOLU" in d and "ne pas chercher tasks.db" in d


def test_consigne_sans_pointeur_inchangee(bus):
    assert E._resoudre_pointeurs_consigne("corriger X dans tools/y.py") == "corriger X dans tools/y.py"
