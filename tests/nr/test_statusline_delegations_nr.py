"""La ligne d'etat montre les delegations en cours (owner 24/10 : « visualiser direct en bas de terminal »).

Segment `DÉL n AGENT<marque><age>` lu dans tasks.db en lecture seule : en cours ▶, en attente ⏸.
Base illisible = `DÉL ?` (jamais 0 : une source muette ne prouve rien). Aucune delegation = segment absent.
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import nokido_statusline as S  # noqa: E402


def _base(tmp_path, lignes):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, from_agent TEXT, updated_at TEXT)")
    c.executemany("INSERT INTO tasks VALUES (?,?,?,?,?)", lignes)
    c.commit()
    c.close()
    return db


def test_delegations_en_cours_et_en_attente(tmp_path):
    maintenant = datetime(2026, 10, 24, 18, 0, 0)
    db = _base(tmp_path, [
        ("j1", "CLAUDE_HEADLESS", "running", "agt_claude", (maintenant - timedelta(minutes=3)).isoformat()),
        ("j2", "OPENCODE_GLM", "pending", "agt_claude", (maintenant - timedelta(minutes=12)).isoformat()),
        ("j3", "MISTRAL", "done", "agt_claude", maintenant.isoformat()),
        ("j4", "CODEX", "running", "agt_autre", maintenant.isoformat()),
    ])
    seg = S._delegations(db, maintenant=maintenant)
    assert seg.startswith("DÉL 2"), seg
    assert "HEADLESS▶3m" in seg and "GLM⏸12m" in seg, seg
    assert "MISTRAL" not in seg and "CODEX" not in seg, seg


def test_aucune_delegation_pas_de_segment(tmp_path):
    db = _base(tmp_path, [("j3", "MISTRAL", "done", "agt_claude", "2026-10-24T18:00:00")])
    assert S._delegations(db) == ""


def test_base_illisible_dit_inconnu(tmp_path):
    assert S._delegations(tmp_path / "absente.db") == "DÉL ?"
