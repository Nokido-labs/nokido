"""NR -- l'arbre reconnait [OUVERT] et ses synonymes, et les marqueurs de decision owner (22/10).

Point de cloture 22/10 (objectif owner 65 %) : 16 items SANS_MARQUEUR, dont les deux P0 ouverts le 21/10
(« P0: [OUVERT 2026-10-22] ... ») -- donc HORS du plan (vagues, prets) : la liste blanche de _etat_arbre ne connait
pas `OUVERT`. La liste blanche reste la regle (jamais CLOS par defaut) ; il lui manquait des mots.

Contrats :
  1. [OUVERT ...], [EN COURS ...], [A FAIRE ...] -> OUVERT, jouable par le plan ;
  2. [A DECIDER ...], [PROPOSE ..., a valider par l'owner], [EVALUE ..., a valider par l'owner] -> DECISION_OWNER ;
  3. un marqueur ambigu ([MIS A JOUR ...], [MESURE CONSOLIDEE ...]) reste SANS_MARQUEUR (requalification humaine) ;
  4. jamais CLOS par defaut.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_roadmap_keeper as K  # noqa: E402


def test_ouvert_et_synonymes_sont_jouables():
    for t in ("P0: [OUVERT 2026-10-22] regles hors du corps distribue",
              "[EN COURS 21/10] decision owner : copie transitoire",
              "[A FAIRE apres la release 0.20.13] mesurer optimize"):
        assert K._etat_arbre(t) == "OUVERT", t
    assert "OUVERT" in K._JOUABLES


def test_marqueurs_de_decision_owner():
    for t in ("[A DECIDER owner, 21/10] avis d'un pair",
              "[PROPOSE 2026-10-21, a valider par l'owner] P2. instrument",
              "[EVALUE 2026-10-21 par Claude, a valider par l'owner] feuilles de route"):
        assert K._etat_arbre(t) == "DECISION_OWNER", t


def test_arbre_compte_un_item_ouvert_sans_planter(tmp_path, monkeypatch):
    """Regression mesuree le 22/10 : 9bdfe5d41 rendait OUVERT mais _ETATS_ARBRE ne le comptait pas -> KeyError dans
    arbre() des qu'un item REEL portait [OUVERT] (les NR n'avaient aucun item OUVERT). Chemin reel : arbre()."""
    import types
    faits = [{"key": "P1_neuf", "value": "P1: [OUVERT 2026-10-22] item neuf", "trust": 0.9, "updated_at": 1},
             {"key": "P1_vieux", "value": "[PARTIEL 2026-10-20 : reste = x]", "trust": 0.9, "updated_at": 2}]
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda zone, *, category=None, min_trust=None, limit=200: list(faits)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)
    monkeypatch.setattr(K, "CARTE_DEPENDANCES", tmp_path / "absente.json")
    doc = K.arbre(out=tmp_path / "a.json")
    par = {i["cle"]: i["etat"] for i in doc["items"]}
    assert par["P1_neuf"] == "OUVERT"


def test_ambigus_restent_sans_marqueur_jamais_clos():
    for t in ("[MIS A JOUR 21/10 soir] (2) CI privee", "[MESURE CONSOLIDEE 21/10, 3 passes] vivants",
              "[PROPOSE 2026-10-21] sans demande de validation", "texte sans marqueur"):
        assert K._etat_arbre(t) == "SANS_MARQUEUR", t
