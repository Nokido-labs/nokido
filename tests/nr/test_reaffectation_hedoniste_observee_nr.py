# -*- coding: utf-8 -*-
"""NR : la reaffectation note ce qu'aurait choisi l'ordre HEDONISTE, sans le suivre (P1 utilitarisme, 19/10).

`forge_motivation.ordre_hedoniste` classe les executeurs par force mesuree (recompense par resultat) mais
n'avait AUCUN appelant. Observer avant d'enforcer : chaque reaffectation trace `hedoniste` a cote de `vers` ;
l'armement (suivre l'ordre hedoniste) reste une decision owner, sur la serie observee.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402
from nokido_agent.app import forge_motivation as M  # noqa: E402


@pytest.fixture
def base(monkeypatch, tmp_path):
    chemin = tmp_path / "tasks.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT,"
              " updated_at TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t1', 'x', 'CODEX', 'pending', NULL, NULL)")
    c.commit()
    c.close()
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(chemin))
    monkeypatch.setattr(T, "_lire_registre", lambda: {"agents": {}})
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: agent in ("MISTRAL", "WORKER_CODE"))
    return chemin


def _trace(chemin):
    c = sqlite3.connect(chemin)
    return json.loads(c.execute("SELECT reaffectations FROM tasks WHERE id='t1'").fetchone()[0])


def test_la_trace_porte_le_choix_hedoniste_sans_le_suivre(monkeypatch, base):
    vus = []
    monkeypatch.setattr(M, "ordre_hedoniste", lambda cands, classe, r=None: vus.append((list(cands), classe))
                        or list(reversed(cands)))
    assert T._reaffecter({"id": "t1", "agent": "CODEX"}, "quota") == "MISTRAL"  # decision INCHANGEE
    t = _trace(base)[-1]
    assert t["vers"] == "MISTRAL" and t["hedoniste"] == "WORKER_CODE"
    assert vus and vus[0][0] == ["MISTRAL", "WORKER_CODE"]  # seulement les vivants non essayes


def test_ordre_hedoniste_illisible_est_inconnu(monkeypatch, base):
    def casse(*a, **k):
        raise RuntimeError("registre illisible")
    monkeypatch.setattr(M, "ordre_hedoniste", casse)
    assert T._reaffecter({"id": "t1", "agent": "CODEX"}, "quota") == "MISTRAL"
    assert _trace(base)[-1]["hedoniste"] == "INCONNU"
