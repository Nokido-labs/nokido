"""NR 7/11 : le decompte roadmap couvre toutes les zones/cles, sans ranger l'inconnu en OUVERT ni en clos.
Tableau noir JETABLE (double de read_zone) : aucune base vivante."""
import sys
import types

from app import forge_ssot_maintainer as M

Z = {
    "architecture_rules": [
        {"key": "P0_a", "value": "[CLOS le 1/10] P0: fini"},
        {"key": "P1_b", "value": "[PARTIEL] reste X"},
        {"key": "roadmap_c", "value": "[OWNER_PLANIFIE] c"},
        {"key": "chantier_d", "value": "[DECISION OWNER] d"},
        {"key": "chantier_e", "value": "texte libre sans marqueur"},
        {"key": "chantier_f", "value": "[DIRECTIVE OWNER] inconnu"},
        {"key": "P2_g", "value": "[EN COURS] g"},
        {"key": "P2_h", "value": "[A FAIRE] h"},
        {"key": "P2_i", "value": "[OUVERT] i"},
        {"key": "regle_perm", "value": "[PERMANENT] consigne"},
        {"key": "P1_perm", "value": "[PERMANENT] consigne cle roadmap"},
        {"key": "avis_externes_echecs_20261024", "value": "[OUVERT] chantier hors motif"},
        {"key": "regle_x", "value": "regle de code sans marqueur"},
    ],
    "roadmap": [{"key": "zz", "value": "[RESOLU] r"}],
    "active_bugs": [{"key": "bug_1", "value": "[FERME] b"}],
    "tree_locks": [{"key": "agent", "value": "[OUVERT] fichiers"}],
    "scratch": [{"key": "s", "value": "[OUVERT] s"}],
}


def _double(monkeypatch):
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda zone, *, category=None, min_trust=None, limit=200: list(
        Z.get(zone, []) if category is None else [])
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)


def test_decompte(monkeypatch):
    _double(monkeypatch)
    d = M.decompte_roadmap()
    assert d["total"] == 11, d
    assert d["par_etat"] == {"CLOS": 3, "PARTIEL": 1, "OUVERT": 1, "OWNER_PLANIFIE": 1,
                             "DECISION": 1, "EN_COURS": 1, "A_FAIRE": 1, "SANS_MARQUEUR": 2}, d["par_etat"]
    assert d["exclus"]["permanent"] == 2 and d["exclus"]["tree_locks"] == 1 and d["exclus"]["scratch"] == 1
    assert d["hors_motif_cle"] == 1
    cles = {i["cle"] for i in d["sans_marqueur"]}
    assert cles == {"chantier_e", "chantier_f"}
    assert all(len(i["texte"]) <= 80 for i in d["sans_marqueur"])


def test_etat_inconnu_pas_clos():
    assert M.etat_roadmap_fin("[BIZARRE] x") == "SANS_MARQUEUR"
    assert M.etat_roadmap_fin("P0: [FAIT] x") == "CLOS"


def test_etat_json_prefixe_retracte():
    assert M.etat_roadmap_fin('{"intent":"x","etat":"FAIT"}') == "CLOS"
    assert M.etat_roadmap_fin('{"etat":"PARTIEL"}') == "PARTIEL"
    assert M.etat_roadmap_fin('{"etat":"BIZARRE"}') == "SANS_MARQUEUR"
    assert M.etat_roadmap_fin("{pas du json") == "SANS_MARQUEUR"
    assert M.etat_roadmap_fin("[ÉTAT OUVERT] x") == "OUVERT"
    assert M.etat_roadmap_fin("[ETAT PARTIEL le 1/11] x") == "PARTIEL"
    assert M.etat_roadmap_fin("[RETRACTE] x") == "CLOS"
    for t in ("[MESURE] x", "[INSTRUIT] x", "[A INSTRUIRE] x", "[CORRIGE DANS LE CODE] x"):
        assert M.etat_roadmap_fin(t) == "SANS_MARQUEUR", t


def test_p3_et_alias(monkeypatch, tmp_path):
    import json
    z2 = {"architecture_rules": [
        {"key": "P3_x", "value": "[OWNER_PLANIFIE] x"},
        {"key": "vieille_cle", "value": "[CLOS] y"},
        {"key": "autre_hors", "value": "[CLOS] z"},
    ], "roadmap": [], "active_bugs": []}
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda zone, *, category=None, min_trust=None, limit=200: list(z2.get(zone, []))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)
    f = tmp_path / "alias.json"
    f.write_text(json.dumps({"alias": {"vieille_cle": {"priorite": "P1"}}}), encoding="utf-8")
    monkeypatch.setattr(M, "_ROADMAP_ALIAS_PATH", f)
    d = M.decompte_roadmap()
    assert d["total"] == 2 and d["par_etat"]["CLOS"] == 1 and d["hors_motif_cle"] == 1, d
    assert d["alias_roadmap"]["comptees"] == {"vieille_cle": "P1"} and not d["alias_roadmap"]["erreur"]
    f.write_text("{illisible", encoding="utf-8")
    d = M.decompte_roadmap()
    assert d["alias_roadmap"]["erreur"] and d["hors_motif_cle"] == 2, d


def test_refresh_publie_decompte(monkeypatch):
    _double(monkeypatch)
    doc = M._roadmap_build_doc()
    assert doc["roadmap_decompte"]["total"] == 11
    assert "roadmap_statuts" in doc and "roadmap_clos" in doc
