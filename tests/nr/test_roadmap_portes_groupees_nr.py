# -*- coding: utf-8 -*-
"""NR (owner 19/10, « liens de cause a effet pour avancer plus efficacement ») : le plan groupe les items par PORTE.

Mesure du 19/10 sur 58 items ouverts : le graphe des dependances est plat (meilleur levier = 4 items en aval, 16 items
sans lien) ; les causes COMMUNES sont des portes -- geste owner 20, serie d'observation 11, relance 6, executeur 6,
CI 3. Une relance constate 6 items d'un coup. `porte_item` classe le reste d'un item (premiere porte reconnue, ordre
OWNER > RELANCE > CI > SERIE > EXECUTEUR, sinon LIBRE) ; `gestes_groupes` rend une ligne par porte avec ses items et ce
qu'ils debloquent en aval, triee par levier ; plan_puct la publie (`portes`). Pur : l'elagage, sans modele entraine.
"""
from nokido_agent.tools import forge_roadmap_keeper as K


def _it(cle, reste, etat="PARTIEL", cite=()):
    return {"cle": cle, "etat": etat, "priorite": "P1", "reste": reste, "cite": list(cite)}


ITEMS = [
    _it("a", "derogation owner sur nokido_hub.py"),
    _it("b", "constater le demarrage au journal apres relance du keeper"),
    _it("c", "rejouer a la prochaine CI de reference"),
    _it("d", "serie hamilton_observe puis remesurer"),
    _it("e", "deleguer le lot 3 a un executeur AGY"),
    _it("f", "ecrire l'extracteur"),
    _it("g", "geste owner : relancer le connecteur", cite=["a"]),
    _it("h", "constater apres relance", cite=["b"]),
    _it("z", "derogation owner", etat="CLOS"),
]


def test_porte_item_premiere_porte_reconnue():
    p = {i["cle"]: K.porte_item(i) for i in ITEMS}
    assert p == {"a": "OWNER", "b": "RELANCE", "c": "CI", "d": "SERIE", "e": "EXECUTEUR", "f": "LIBRE",
                 "g": "OWNER", "h": "RELANCE", "z": "OWNER"}


def test_gestes_groupes_par_levier_hors_clos_et_libres():
    g = K.gestes_groupes(ITEMS)
    portes = [x["porte"] for x in g]
    assert portes[:2] == ["OWNER", "RELANCE"] and "LIBRE" not in portes
    owner = g[0]
    assert owner["cles"] == ["a", "g"] and owner["n"] == 2   # z est CLOS : hors du compte
    assert owner["aval"] == 1                                # a debloque g, deja compte une fois


def test_le_levier_pese_la_priorite_pas_seulement_le_nombre():
    """19/10 : compter les items faisait passer 3 items P2 derriere une porte OWNER devant 2 items P0 bloques par une
    relance. Le levier somme les poids de priorite (_POIDS_PRIORITE) des items de la porte et de leur aval."""
    items = [dict(_it("o%d" % i, "derogation owner"), priorite="P2") for i in range(3)]
    items += [dict(_it("r%d" % i, "constater apres relance"), priorite="P0") for i in range(2)]
    g = K.gestes_groupes(items)
    assert [x["porte"] for x in g] == ["RELANCE", "OWNER"]
    assert g[0]["poids"] > g[1]["poids"] and g[1]["n"] > g[0]["n"]


def test_plan_puct_publie_les_portes():
    plan = K.plan_puct(ITEMS, [], [])
    assert [x["porte"] for x in plan["portes"]][:2] == ["OWNER", "RELANCE"]
