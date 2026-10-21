"""NR -- page arbre d'evolution de la roadmap dans l'UI web (item SSoT roadmap_p1_arbre_evolution_ui_web_20261017).

Owner : « un visu total de la roadmap dans l'ui web, sous forme d'arbre d'evolution, multi-partite ». `arbre()` du keeper
rend deja {genere_le, total, par_etat, items:[{cle, etat, priorite, reste}]} ; la page en tire un graphe vis-network
(vendorise, pas de CDN). Contrat : aucun item perdu, une troncature se DIT, et le drapeau --html traverse le vrai
point d'entree (_main), pas seulement la fonction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from app.web_hub import roadmap_arbre as RA  # noqa: E402

DOUBLURE = {"genere_le": "2026-10-19T00:00:00+00:00", "total": 5,
            "par_etat": {"CLOS": 2, "PARTIEL": 1, "DECISION_OWNER": 0, "OWNER_PLANIFIE": 1, "GELE": 0,
                         "SANS_MARQUEUR": 1},
            "items": [{"cle": "a", "etat": "CLOS", "priorite": "P0", "reste": "fait"},
                      {"cle": "b", "etat": "CLOS", "priorite": "P1", "reste": ""},
                      {"cle": "c", "etat": "PARTIEL", "priorite": "P1", "reste": "x" * 500},
                      {"cle": "d", "etat": "OWNER_PLANIFIE", "priorite": "P2", "reste": "attente owner"},
                      {"cle": "e", "etat": "SANS_MARQUEUR", "priorite": None, "reste": "?"}]}


def test_aucun_item_n_est_perdu_et_les_etats_sont_comptes():
    g = RA.graphe(DOUBLURE)
    items = [n for n in g["nodes"] if n.get("groupe") == "item"]
    assert len(items) == DOUBLURE["total"]
    par_etat = {}
    for n in items:
        par_etat[n["etat"]] = par_etat.get(n["etat"], 0) + 1
    assert par_etat == {k: v for k, v in DOUBLURE["par_etat"].items() if v}


def test_racine_priorites_et_aretes():
    g = RA.graphe(DOUBLURE)
    ids = {n["id"] for n in g["nodes"]}
    assert "roadmap" in ids and {"prio:P0", "prio:P1", "prio:P2", "prio:sans"} <= ids
    assert all(e["from"] in ids and e["to"] in ids for e in g["edges"])
    assert {"from": "prio:sans", "to": "item:e"} in g["edges"]


def test_une_troncature_se_dit():
    c = next(n for n in RA.graphe(DOUBLURE)["nodes"] if n["id"] == "item:c")
    assert len(c["title"]) < 500 and "tronque" in c["title"]


def test_un_etat_inattendu_n_est_pas_perdu():
    doc = {"items": [{"cle": "z", "etat": "NOUVEAU", "priorite": "P1", "reste": ""}]}
    z = next(n for n in RA.graphe(doc)["nodes"] if n["id"] == "item:z")
    assert z["etat"] == "NOUVEAU" and z["color"]


def test_la_page_porte_le_graphe_et_vis_network():
    g = RA.graphe(DOUBLURE)
    html = RA.page_html(g)
    assert json.dumps(g["nodes"][0], ensure_ascii=False) in html
    assert "vis-network" in html and "new vis.Network" in html
    assert "cdn" not in html.lower()


def test_la_route_api_rend_le_graphe_de_la_vue_roadmap(monkeypatch):
    """La vue `graph_viz.html?vue=roadmap` lit /api/roadmap/arbre : la route doit rendre {nodes, edges} a plat."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.web_hub import wired_routes as W
    # Un seul point de patch : la route lit le keeper par `_doc_arbre` (deux noms d'import = deux instances).
    monkeypatch.setattr(W, "_doc_arbre", lambda: DOUBLURE)
    app = FastAPI()
    app.include_router(W.router)
    r = TestClient(app).get("/api/roadmap/arbre")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and len([n for n in d["nodes"] if n.get("groupe") == "item"]) == 5 and d["edges"]


def test_le_noeud_porte_l_agent_qui_le_travaille():
    """Multi-partite (owner) : un item cite par une tache EN VOL porte le nom de son agent ; les autres n'en ont pas."""
    g = RA.graphe(DOUBLURE, porteurs={"c": "ANTIGRAVITY"})
    c = next(n for n in g["nodes"] if n["id"] == "item:c")
    a = next(n for n in g["nodes"] if n["id"] == "item:a")
    assert c["porteur"] == "ANTIGRAVITY" and "ANTIGRAVITY" in c["label"] and "porteur" not in a


def test_les_porteurs_se_lisent_dans_les_taches_en_vol(tmp_path):
    import sqlite3
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, description TEXT)")
    # Cles realistes (les vraies cles du tableau noir sont longues et datees) : une cle d'une lettre se trouve dans
    # n'importe quel mot.
    con.executemany("INSERT INTO tasks VALUES (?,?,?,?)", [
        ("1", "ANTIGRAVITY", "running", "verifie item_gamma_20261019 et item_alpha_20261019"),
        ("2", "OPENCODE_GLM", "done", "travail sur item_epsilon_20261019"),
        ("3", "CODEX", "pending", "travail sur item_epsilon_20261019 plus tard")])
    con.commit()
    con.close()
    p = RA.porteurs_en_vol(["item_alpha_20261019", "item_gamma_20261019", "item_epsilon_20261019"], db)
    assert p == {"item_alpha_20261019": "ANTIGRAVITY", "item_gamma_20261019": "ANTIGRAVITY"}
    assert RA.porteurs_en_vol(["item_alpha_20261019"], tmp_path / "absent.db") == {}


def test_la_page_est_servie_par_le_portail(monkeypatch):
    """19/10 : graph_viz.html n'etait servi par AUCUNE route -- la vue roadmap n'etait atteignable que par --html."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.web_hub import wired_routes as W
    monkeypatch.setattr(W, "_doc_arbre", lambda: DOUBLURE)
    app = FastAPI()
    app.include_router(W.router)
    r = TestClient(app).get("/roadmap/arbre")
    assert r.status_code == 200 and "ROADMAP_GRAPHE" in r.text and '"item:a"' in r.text
    assert "/static/vis-network.min.js" in r.text


def test_le_tableau_de_bord_mene_a_l_arbre():
    """Une page que rien ne lie n'existe pas pour l'owner : une tuile du tableau de bord vise /roadmap/arbre."""
    import os
    os.environ.setdefault("LAFORGE_AUTH_ENABLED", "0")
    from app.web_hub import app as A
    assert any((c or {}).get("target") == "/roadmap/arbre" for c in A.SERVICES.values())


def test_le_drapeau_html_traverse_le_point_d_entree(tmp_path, monkeypatch):
    import forge_roadmap_keeper as K
    cible = tmp_path / "arbre.html"
    monkeypatch.setattr(K, "arbre", lambda out=None: DOUBLURE)
    monkeypatch.setattr(sys, "argv", ["forge_roadmap_keeper.py", "--html", str(cible)])
    assert K._main() == 0
    page = cible.read_text(encoding="utf-8")
    assert '"item:a"' in page and "new vis.Network" in page
