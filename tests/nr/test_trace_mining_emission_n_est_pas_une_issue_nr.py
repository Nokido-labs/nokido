"""NR -- une EMISSION d'appel n'est pas une issue : le capteur d'usage ne la compte jamais comme un echec.

MESURE 2026-09-25 (execution_traces, 7 jours) : groq 227 lignes, mistral 56, cohere, deepseek,
gemini_cli, openrouter_free, ollama, router... TOUTES `status=CALL`, `success=0`, et AUCUNE ligne
OK/ERR pour ces outils. `pat_trace_mining` en tirait « groq 0 % de succes » -> une experience
`usage_findings` PENDING toutes les heures, et le re-examen du tri concluait TOUJOURS_EN_ECHEC.

Cause (lue dans le code, pas deduite) : `tools/forge_trace_sidecar._parse_line` ne trace que les
lignes `Direction.OUT` et pose `success=(status == "OK")`. Or pour le canal CLOUD le sens est
inverse : `log_cloud_out` = la REQUETE partie vers le fournisseur (status CALL), `log_cloud_in` = la
REPONSE (OK/ERR), ecartee comme ligne IN. L'issue d'un appel fournisseur n'atteint donc JAMAIS la
table : 0 % ne mesurait rien. UNKNOWN n'est pas NO -- et l'inverse vaut aussi : rien ne prouve non
plus que ces appels reussissent. Le capteur dit « issue non tracee », il n'invente ni panne ni sante.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SCHEMA = """CREATE TABLE traces (id TEXT NOT NULL, ts REAL NOT NULL, state_t_emb BLOB,
    action_json TEXT NOT NULL, state_t1_emb BLOB, cost_before REAL, cost_after REAL,
    task_type TEXT, success INTEGER NOT NULL, trace_id TEXT)"""


def _lignes(outil, status, success, n):
    return [(outil, status, success)] * n


@pytest.fixture
def AL(tmp_path, monkeypatch):
    m = importlib.import_module("forge_autonomous_loops")
    (tmp_path / "RAG").mkdir()
    con = sqlite3.connect(tmp_path / "RAG" / "execution_traces.db")
    con.execute(_SCHEMA)
    lignes = (
        _lignes("groq", "CALL", 0, 40)                                      # emissions seules
        + _lignes("mixte", "CALL", 0, 40) + _lignes("mixte", "OK", 1, 35) + _lignes("mixte", "ERR", 0, 5)
        + _lignes("mauvais", "ERR", 0, 30) + _lignes("mauvais", "OK", 1, 10)
        + _lignes("bon", "OK", 1, 40)
        + _lignes("illisible", "INCONNU", 0, 40)                          # statut non lu par le sidecar
    )
    t = time.time()
    for i, (outil, status, success) in enumerate(lignes):
        action = {"type": "tool_call", "tool": outil, "agent": "HUB", "status": status}
        con.execute("INSERT INTO traces (id, ts, action_json, cost_before, cost_after, task_type, success,"
                    " trace_id) VALUES (?,?,?,?,?,?,?,?)",
                    (str(i), t - 60, json.dumps(action), 0.0, 0.0, "tool_call", success, "system"))
    con.commit()
    con.close()
    monkeypatch.setattr(m, "ROOT", tmp_path)                              # JAMAIS la vraie table
    monkeypatch.setattr(m, "_EVOLUTION_LEDGER", tmp_path / "evolution_experiences.jsonl")
    monkeypatch.setattr(m, "_ensure_ledger_migrated", lambda: None)
    evenements = []
    faux = types.ModuleType("forge_critical_events")
    faux.persist = lambda *a, **k: evenements.append(a)
    for nom in ("nokido_agent.app.forge_critical_events", "forge_critical_events"):
        monkeypatch.setitem(sys.modules, nom, faux)
    m._evenements_test = evenements
    return m


def _experiences(AL):
    led = Path(AL._EVOLUTION_LEDGER)
    return [json.loads(l) for l in led.read_text(encoding="utf-8").splitlines() if l] if led.exists() else []


def test_une_emission_seule_n_est_pas_un_echec_et_le_dit(AL):
    r = AL.pat_trace_mining()
    faibles = {f["tool"] for f in r["low_success"]}
    assert "groq" not in faibles, "40 emissions sans issue lues comme 0 % de succes"
    assert {"tool": "groq", "appels_emis": 40} in r["issue_non_tracee"]


def test_un_statut_illisible_n_est_ni_echec_ni_succes(AL):
    r = AL.pat_trace_mining()
    assert "illisible" not in {f["tool"] for f in r["low_success"]}
    assert {"tool": "illisible", "appels_emis": 40} in r["issue_non_tracee"]


def test_le_taux_ne_se_calcule_que_sur_les_issues(AL):
    r = AL.pat_trace_mining()
    faibles = {f["tool"]: f for f in r["low_success"]}
    # mixte : 35 OK / 40 issues = 88 % ; en comptant les 40 CALL on lisait 35/80 = 44 % -> faux signal
    assert "mixte" not in faibles
    assert faibles["mauvais"]["success_pct"] == 25 and faibles["mauvais"]["n"] == 40
    assert "bon" not in faibles


def test_seul_un_vrai_echec_ouvre_une_experience(AL):
    AL.pat_trace_mining()
    exps = [e for e in _experiences(AL) if e.get("kind") == "usage_findings"]
    assert len(exps) == 1
    assert [f["tool"] for f in exps[0]["findings"]["low_success"]] == ["mauvais"]


def test_le_reexamen_ne_juge_pas_sur_des_emissions(AL):
    mesures = AL._succes_recent_des_outils(["groq", "mixte", "mauvais", "bon"])
    assert "groq" not in mesures          # absent -> INDETERMINE au re-examen, jamais TOUJOURS_EN_ECHEC
    assert mesures["mixte"] == (40, 88)
    assert mesures["mauvais"] == (40, 25)
    assert mesures["bon"] == (40, 100)
