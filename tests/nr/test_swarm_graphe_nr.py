"""NR -- vue /swarm/graphe : qui travaille sur quoi, en graphe (item SSoT p1_swarm_en_direct_graphique_2026-10-14).

Mesure 19/10 03:04 : le miroir sandbox/reflexion.jsonl vit (ecrit il y a 1 s) mais ne porte ni task_* ni job_* -- le bus
ne voit pas le travail des executeurs. Premiere marche, sans attendre le bus : la vue lit tasks.db (lecture seule) et
montre agents -> taches (en vol et recentes), couleur par statut, sur le gabarit vis-network existant (graph_viz.html,
comme l'arbre roadmap). Une borne sur le nombre de taches se DIT.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.web_hub import swarm_graphe as SG  # noqa: E402

LIGNES = [("job_aaa_1", "ANTIGRAVITY", "running", "verifie le lot 4"),
          ("job_bbb_2", "ANTIGRAVITY", "pending", "enquete RED4"),
          ("job_ccc_3", "OPENCODE_GLM", "done", "livraison"),
          ("job_ddd_4", "CODEX", "statut_inattendu", "?")]


def test_agents_taches_et_aretes():
    g = SG.graphe_taches(LIGNES)
    ids = {n["id"] for n in g["nodes"]}
    assert {"agent:ANTIGRAVITY", "agent:OPENCODE_GLM", "agent:CODEX"} <= ids
    assert {"tache:job_aaa_1", "tache:job_ccc_3"} <= ids
    assert {"from": "agent:ANTIGRAVITY", "to": "tache:job_bbb_2"} in g["edges"]
    assert g["libelle"] == "taches"


def test_un_statut_inattendu_reste_visible():
    d = next(n for n in SG.graphe_taches(LIGNES)["nodes"] if n["id"] == "tache:job_ddd_4")
    assert d["statut"] == "statut_inattendu" and d["color"]


def test_la_borne_se_dit():
    g = SG.graphe_taches(LIGNES * 30, borne=10)
    assert len([n for n in g["nodes"] if n.get("groupe") == "item"]) == 10 and g["ecartees"] == 110


def test_lecture_de_tasks_db_et_base_illisible(tmp_path):
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, description TEXT)")
    con.executemany("INSERT INTO tasks VALUES (?,?,?,?)", LIGNES)
    con.commit()
    con.close()
    assert len(SG.lire_taches(db)) == 4
    assert SG.lire_taches(tmp_path / "absent.db") is None


def test_la_page_est_servie(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.web_hub import wired_routes as W
    monkeypatch.setattr(SG, "lire_taches", lambda db=None: LIGNES)
    app = FastAPI()
    app.include_router(W.router)
    r = TestClient(app).get("/swarm/graphe")
    assert r.status_code == 200 and '"tache:job_aaa_1"' in r.text and "new vis.Network" in r.text
