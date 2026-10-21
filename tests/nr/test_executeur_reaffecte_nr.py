"""NR -- un CLI absent ou a quota epuise ne bloque plus une tache : elle est REAFFECTEE, et c'est dit (owner 17/10).

Owner 17/10 : « il faut que Nokido soit en mesure de debloquer la situation si les cli n'existent plus ou n'ont plus de
quota ». Avant : quota Codex atteint -> « les taches CODEX restent pending pour demain » ; CLI indisponible -> « laissee
pending » ; AGY sans mode agent -> repli RELAIS qui repond sans executer. Desormais la tache passe au premier executeur
suivant dont le POULS est frais (sandbox/task_executor_<agent>.heartbeat), dans l'ordre ANTIGRAVITY, MISTRAL, CODEX,
WORKER_CODE (modeles locaux : ni CLI ni quota). Jamais vers une file dont on ne sait pas qu'elle est videe ; jamais de
ping-pong (un agent deja essaye n'est plus vise) ; la chaine epuisee laisse la tache ou elle est, et le dit.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


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
    # Ce NR eprouve la MECANIQUE de reaffectation, pas la politique de suspension (test_repli_hors_executeur_suspendu_nr) :
    # isole du registre reel, ou MISTRAL est suspendu depuis le 17/10 (le receveur attendu ici).
    monkeypatch.setattr(T, "_lire_registre", lambda: {"agents": {}})
    return chemin


def _ligne(chemin):
    c = sqlite3.connect(chemin)
    c.row_factory = sqlite3.Row
    return dict(c.execute("SELECT * FROM tasks WHERE id='t1'").fetchone())


def test_un_quota_epuise_reaffecte_au_premier_executeur_qui_bat(monkeypatch, base):
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: agent in ("MISTRAL", "WORKER_CODE"))
    assert T._reaffecter({"id": "t1", "agent": "CODEX"}, "quota Codex du jour atteint") == "MISTRAL"
    ligne = _ligne(base)
    assert ligne["agent"] == "MISTRAL" and ligne["status"] == "pending"
    trace = json.loads(ligne["reaffectations"])
    assert trace[-1]["de"] == "CODEX" and trace[-1]["vers"] == "MISTRAL" and "quota" in trace[-1]["motif"]


def test_une_tache_deja_prise_revient_pending_chez_le_receveur(monkeypatch, base):
    sqlite3.connect(base).execute("UPDATE tasks SET status='running', agent='ANTIGRAVITY'").connection.commit()
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: agent == "MISTRAL")
    assert T._reaffecter({"id": "t1", "agent": "ANTIGRAVITY"}, "mode AGENT indisponible") == "MISTRAL"
    assert _ligne(base)["status"] == "pending"


def test_aucun_executeur_vivant_laisse_la_tache_ou_elle_est(monkeypatch, base):
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: False)
    assert T._reaffecter({"id": "t1", "agent": "CODEX"}, "quota") is None
    assert _ligne(base)["agent"] == "CODEX"


def test_jamais_de_ping_pong(monkeypatch, base):
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: True)
    assert T._reaffecter({"id": "t1", "agent": "CODEX"}, "quota") == "ANTIGRAVITY"
    assert T._reaffecter({"id": "t1", "agent": "ANTIGRAVITY"}, "agy indisponible") == "MISTRAL"
    assert T._reaffecter({"id": "t1", "agent": "MISTRAL"}, "vibe indisponible") == "WORKER_CODE"
    assert T._reaffecter({"id": "t1", "agent": "WORKER_CODE"}, "local indisponible") is None, "chaine epuisee"


def test_le_pouls_d_un_executeur_se_lit_frais_perime_ou_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "SANDBOX", tmp_path)
    maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
    vieux = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3600))
    (tmp_path / "task_executor_mistral.heartbeat").write_text(json.dumps({"ts": maintenant}), encoding="utf-8")
    (tmp_path / "task_executor_codex.heartbeat").write_text(json.dumps({"ts": vieux}), encoding="utf-8")
    assert T._executeur_bat("MISTRAL") is True
    assert T._executeur_bat("CODEX") is False
    assert T._executeur_bat("ANTIGRAVITY") is False, "absent = on ne sait pas qu'elle est videe"


# Le depart depuis alpha (delegation a forge_worktree.sync) est verrouille dans test_executeur_part_d_alpha_nr.py.
