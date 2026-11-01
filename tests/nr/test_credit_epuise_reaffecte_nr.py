"""NR 31/10 -- un CLI sans credit est une PANNE DE SURFACE (reaffectation + surface indisponible), pas un echec de travail.

Mesure 31/10 09:30 (job_81843bc6, CLAUDE_HEADLESS) : `claude -p` rend `"is_error":true, "api_error_status":400,
"result":"Credit balance is too low"` apres 254 ms, 0 jeton. L'executeur a CLOS la tache (done/FAILURE) sans la
reaffecter : _RE_ECHEC_TRAVAIL (\\bFAILED\\b, re.I) reconnaissait la CLE JSON `"failed":0` des statistiques de sous-agents
-> « echec de travail » -> aucune reaffectation. Deux reparations : une cle JSON n'est pas un echec de test ; un credit
epuise se NOMME et se reaffecte, et la surface est marquee indisponible (la tache suivante n'y retourne pas).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402

EFFET = "[effet observe] commits produits : 0 (94816d930..94816d930) ; fichiers non commites : 0 ; [RIEN PRODUIT]"
DETAIL = ('⚠ Permission mode forced to default — CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set.\n'
          '{"duration_api_ms":0,"subagent_stats":{"completed":0,"failed":0,"killed":{"parent":0}},'
          '"is_error":true,"api_error_status":400,"result":"Credit balance is too low","type":"result"}')


def test_une_cle_json_failed_n_est_pas_un_echec_de_travail():
    assert T._est_echec_travail('{"subagent_stats":{"completed":0,"failed":0}}') is False


def test_un_vrai_echec_de_test_reste_un_echec_de_travail():
    assert T._est_echec_travail("=== 2 failed, 31 passed in 3.1s ===") is True
    assert T._est_echec_travail("FAILED tests/nr/test_x.py::test_y") is True


def test_credit_epuise_se_nomme_et_se_reaffecte():
    motif = T._motif_reaffectation_apres(False, EFFET, DETAIL)
    assert motif and motif.startswith("CREDIT EPUISE") and "Credit balance is too low" in motif


def test_credit_epuise_marque_la_surface_indisponible(monkeypatch, tmp_path):
    import sqlite3
    chemin = tmp_path / "tasks.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT,"
              " updated_at TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t1', 'x', 'CLAUDE_HEADLESS', 'running', NULL, NULL)")
    c.commit()
    c.close()
    marquees = []
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(chemin))
    monkeypatch.setattr(T, "_lire_registre", lambda: {"agents": {}})
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: agent == "MISTRAL")
    monkeypatch.setattr(T, "marquer_surface_indisponible", lambda agent, motif: marquees.append(agent))
    motif = T._motif_reaffectation_apres(False, EFFET, DETAIL)
    assert T._reaffecter({"id": "t1", "agent": "CLAUDE_HEADLESS"}, motif, ordre=["MISTRAL"]) == "MISTRAL"
    assert marquees == ["CLAUDE_HEADLESS"]
