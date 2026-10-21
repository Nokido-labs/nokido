"""NR -- l'arbre roadmap est une VRAIE hierarchie de resolution, pas un eventail sous 4 priorites (owner 19/10).

Owner 19/10 : « l'arborescence a part des noeuds de priorite, tu n'as pas cree de veritable arbre ! la resolution d'une
tache peut aider a resoudre une suivante ? il n'y a aucune hierarchie ». Les liens EXISTENT dans le SSoT : un item cite
la cle d'un autre (« rattache a ... », « complement de ... », « d'abord ... avant ... »). `arbre()` publie ces citations
(`cite`) ; `graphe()` en tire des aretes « debloque » de l'item cite vers l'item citant, rattache a sa priorite tout
item sans prerequis, casse les cycles (citations mutuelles) pour garder un graphe orientable, et dit combien d'items
chacun debloque. La page le dispose en hierarchie haut -> bas (graph_viz, `g.hierarchie`).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_roadmap_keeper as K  # noqa: E402
from app.web_hub import roadmap_arbre as RA  # noqa: E402

FAITS = [
    {"key": "p1_socle_a", "value": "[PARTIEL 2026-10-19 : reste = poser le socle]", "trust": 0.9, "updated_at": 1},
    {"key": "p1_etage_b", "value": "[PARTIEL 2026-10-19 : reste = construire sur p1_socle_a]", "trust": 0.9, "updated_at": 2},
    {"key": "p2_toit_c", "value": "[PARTIEL 2026-10-19 : reste = apres p1_etage_b et p1_socle_a]", "trust": 0.9,
     "updated_at": 3},
    {"key": "p2_isole_d", "value": "[CLOS 2026-10-19 : fait]", "trust": 0.9, "updated_at": 4},
    {"key": "p1_mutuel_e", "value": "[PARTIEL 2026-10-19 : reste = voir p1_mutuel_f]", "trust": 0.9, "updated_at": 5},
    {"key": "p1_mutuel_f", "value": "[PARTIEL 2026-10-19 : reste = voir p1_mutuel_e]", "trust": 0.9, "updated_at": 6},
]


def _arbre(tmp_path, monkeypatch):
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda zone, *, category=None, min_trust=None, limit=200: list(FAITS)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)
    return K.arbre(out=tmp_path / "arbre.json")


def test_arbre_publie_les_citations_entre_items(tmp_path, monkeypatch):
    par = {i["cle"]: i for i in _arbre(tmp_path, monkeypatch)["items"]}
    assert par["p1_etage_b"]["cite"] == ["p1_socle_a"]
    assert sorted(par["p2_toit_c"]["cite"]) == ["p1_etage_b", "p1_socle_a"]
    assert par["p2_isole_d"]["cite"] == []


def test_le_graphe_suit_la_chaine_de_resolution(tmp_path, monkeypatch):
    g = RA.graphe(_arbre(tmp_path, monkeypatch))
    assert g["hierarchie"] is True
    e = {(x["from"], x["to"]) for x in g["edges"]}
    assert ("item:p1_socle_a", "item:p1_etage_b") in e and ("item:p1_etage_b", "item:p2_toit_c") in e
    assert ("prio:P1", "item:p1_socle_a") in e, "un item sans prerequis se rattache a sa priorite"
    assert ("prio:P1", "item:p1_etage_b") not in e, "un item avec prerequis pend sous son prerequis, pas sous la priorite"
    socle = next(n for n in g["nodes"] if n["id"] == "item:p1_socle_a")
    assert socle["debloque"] == 2 and "debloque 2" in socle["label"]


def test_les_cycles_sont_casses(tmp_path, monkeypatch):
    g = RA.graphe(_arbre(tmp_path, monkeypatch))
    e = {(x["from"], x["to"]) for x in g["edges"]}
    assert not {("item:p1_mutuel_e", "item:p1_mutuel_f"), ("item:p1_mutuel_f", "item:p1_mutuel_e")} <= e
    assert g["cycles_casses"] >= 1


def test_la_page_dispose_en_hierarchie_quand_le_graphe_le_demande():
    page = (ROOT / "app" / "web_hub" / "graph_viz.html").read_text(encoding="utf-8")
    assert "g.hierarchie" in page and 'direction: "UD"' in page and "levelSeparation" in page
