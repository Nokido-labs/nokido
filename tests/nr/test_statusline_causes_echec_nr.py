# -*- coding: utf-8 -*-
"""NR (owner 3/11 « vois-tu et diagnostiques-tu au moins les raisons des echecs de delegations ? ») : la barre du bas
montre la CAUSE classee des delegations de Claude echouees dans les 2 dernieres heures (tasks.cause_echec, ecrite par
forge_task_executor._clore_delegation). Une base sans la colonne garde l'affichage d'avant, jamais « DÉL ? »."""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest
import nokido_statusline as S  # noqa: E402

MAINTENANT = datetime(2026, 11, 3, 23, 0, 0)


def _base(tmp_path, avec_cause=True):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, updated_at TEXT, from_agent TEXT%s)"
              % (", cause_echec TEXT" if avec_cause else ""))
    lignes = [("t1", "CODEX", "running", MAINTENANT - timedelta(minutes=5), "CLAUDE", None),
              ("t2", "MISTRAL", "failed", MAINTENANT - timedelta(minutes=20), "CLAUDE", "OUTIL_REFUSE"),
              ("t3", "ANTIGRAVITY", "failed", MAINTENANT - timedelta(minutes=40), "CLAUDE", "OUTIL_REFUSE"),
              ("t4", "OPENCODE_GLM", "done", MAINTENANT - timedelta(minutes=50), "CLAUDE", "FAUX_VERT"),
              ("t5", "CODEX", "failed", MAINTENANT - timedelta(hours=5), "CLAUDE", "QUOTA"),
              ("t6", "CODEX", "failed", MAINTENANT - timedelta(minutes=10), "GEMINI", "RING")]
    for tid, ag, st, maj, de, cause in lignes:
        if avec_cause:
            c.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?)", (tid, ag, st, maj.isoformat(sep=" "), de, cause))
        else:
            c.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (tid, ag, st, maj.isoformat(sep=" "), de))
    c.commit()
    c.close()
    return db


@pytest.fixture(autouse=True)
def _sans_marque_reelle(tmp_path, monkeypatch):
    """La vraie marque d'acquittement (sandbox/delegations_acquittees.txt) ne doit pas masquer ces causes."""
    monkeypatch.setattr(S, "_ACQUIT", tmp_path / "pas_de_marque.txt")


def test_les_causes_recentes_de_claude_sont_affichees(tmp_path):
    seg = S._delegations(_base(tmp_path), MAINTENANT, registre=tmp_path / "absent.json")
    assert seg.startswith("DÉL 1 ")
    assert "✗" in seg and "OUTIL_REFUSE×2" in seg and "FAUX_VERT" in seg
    assert "QUOTA" not in seg   # plus de 2 h
    assert "RING" not in seg    # delegation d'un autre agent


def test_sans_colonne_cause_l_affichage_reste_celui_d_avant(tmp_path):
    seg = S._delegations(_base(tmp_path, avec_cause=False), MAINTENANT, registre=tmp_path / "absent.json")
    assert seg.startswith("DÉL 1 ") and "✗" not in seg
