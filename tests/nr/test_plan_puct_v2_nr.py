"""NR -- PUCT v2 : le planificateur n'attribue ni un item qui ATTEND L'OWNER, ni un repondeur OCCUPE.

v1 (08dec66f0) proposait des items dont le reste etait un geste owner (« decision owner », « reposer la bascule a
l'owner ») et des repondeurs deja en vol dans tasks.db : un plan qu'on ne peut pas jouer. Enquete AGY 19/10
(job_55a851be, M:lit INTEGREE) : motif du reste et lecture des agents en vol (statuts running/claimed/assigned).
Un filtre DIT ce qu'il ecarte (attente_owner, occupes) ; tasks.db illisible -> raison nommee, jamais « personne occupe »
en silence.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_roadmap_keeper as K  # noqa: E402


@pytest.mark.parametrize("reste", [
    "un 2e essai en lecture ou sur une tache S pour mesurer sa force, decision owner",
    "serie hamilton_observe, puis decision owner d'armer",
    "remesurer 2 jours puis reposer la bascule a l'owner",
    "geste owner groupe",
    "attente owner",
    "dérogation de l'owner pour app.py",
])
def test_un_reste_qui_attend_l_owner_est_reconnu(reste):
    assert K.attend_owner({"reste": reste})


@pytest.mark.parametrize("reste", ["coder le GREEN", "owner a tranche : cabler la route", ""])
def test_un_reste_jouable_n_attend_pas(reste):
    assert not K.attend_owner({"reste": reste})


def test_le_plan_ecarte_l_item_qui_attend_l_owner_et_le_dit():
    items = [{"cle": "a", "etat": "PARTIEL", "priorite": "P0", "reste": "decision owner"},
             {"cle": "b", "etat": "PARTIEL", "priorite": "P1", "reste": "coder le GREEN"}]
    plan = K.plan_puct(items, ["CLAUDE"], [], duel=False)
    assert [x["cle"] for x in plan["attributions"]] == ["b"]
    assert plan["attente_owner"] == ["a"]


def test_les_agents_en_vol_sont_occupes(tmp_path):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, description TEXT)")
    c.executemany("INSERT INTO tasks VALUES (?,?,?,?)", [("1", "opencode_glm", "running", ""),
                                                          ("2", "CLAUDE", "done", ""),
                                                          ("3", "ANTIGRAVITY", "claimed", "")])
    c.commit()
    c.close()
    occupes, raison = K._occupes(db)
    assert occupes == {"OPENCODE_GLM", "ANTIGRAVITY"} and raison == ""


def test_tasks_db_illisible_se_nomme(tmp_path):
    occupes, raison = K._occupes(tmp_path / "absent" / "tasks.db")
    assert occupes == set() and "ILLISIBLE" in raison


def test_le_point_d_entree_retire_les_occupes(tmp_path, monkeypatch):
    arbre = tmp_path / "arbre.json"
    arbre.write_text(json.dumps({"items": [{"cle": "b", "etat": "PARTIEL", "priorite": "P1",
                                           "reste": "coder le GREEN"}]}), encoding="utf-8")
    monkeypatch.setenv("NOKIDO_PLAN_ARBRE", str(arbre))
    monkeypatch.setenv("NOKIDO_MOTIVATION_RESULTATS", str(tmp_path / "res.jsonl"))
    monkeypatch.setenv("NOKIDO_PLAN_JOURNAL", str(tmp_path / "plan.jsonl"))
    monkeypatch.setattr(K, "_occupes", lambda db=None: ({"OPENCODE_GLM"}, ""))
    plan = K._plan_cli(["OPENCODE_GLM", "CLAUDE"])
    assert plan["libres"] == ["CLAUDE"] and plan["occupes"] == ["OPENCODE_GLM"]
    assert {x["repondeur"] for x in plan["attributions"]} == {"CLAUDE"}
