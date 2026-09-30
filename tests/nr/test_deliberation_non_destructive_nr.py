"""NR — l'etat de deliberation ne detruit plus son antecedent.

P1 de fondation (2026-09-04). Avant : `axes[nom] = {...}` ECRASAIT la position
precedente dans `forge_m2m_debate_antiregression._applique_delta`. Consequence :
aucune filiation reconstructible, et le REJEU impossible — pas faute de journal,
mais parce que l'information disparaissait avant de pouvoir etre rejouee.

Ces tests verrouillent les six invariants poses avec l'owner. Ils portent sur la
CAUSALITE, pas sur la forme : un futur patch qui reintroduirait l'ecrasement doit
echouer ici, meme si toute la suite passe par ailleurs.

Perimetre STRICT de ce P1 : rendre l'etat non destructif. Ni CHALLENGE, ni
EVIDENCE, ni SNN — ces couches viennent apres, et sur ce socle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    if not (ROOT / "tools" / "forge_m2m_debate_antiregression.py").exists():
        pytest.skip("module de debat absent")
    for zone in ("tools", "app"):
        chemin = str(ROOT / zone)
        if chemin not in sys.path:
            sys.path.insert(0, chemin)
    import forge_m2m_debate_antiregression as D
    return D


FLUX = [
    ("AGY", "AXE: cablage_snn | candidat | signal event manquant"),
    ("CLAUDE", "AXE: cablage_snn | rejete | baseline if non battue"),
    ("AGY", "AXE: autre_axe | admis | mesure passee"),
]


def _rejouer(flux):
    D = _module()
    etat = {"tour": 0, "axes": {}, "tensions": [], "acquis": []}
    for qui, texte in flux:
        D._applique_delta(etat, qui, texte)
    return etat


def test_aucune_position_precedente_n_est_perdue():
    """INVARIANT 1. Le remplacement d'un axe conserve l'antecedent."""
    etat = _rejouer(FLUX)
    ids = [p["id"] for p in etat.get("positions", [])]
    assert "P_cablage_snn_1" in ids, "la position remplacee a ete DETRUITE"
    assert "P_cablage_snn_2" in ids
    ancienne = [p for p in etat["positions"] if p["id"] == "P_cablage_snn_1"][0]
    assert ancienne["statut"] == "candidat", (
        "l'antecedent existe mais son contenu a ete altere")


def test_la_filiation_est_reconstructible():
    """INVARIANT 3. `supersedes` relie la revision a ce qu'elle remplace."""
    etat = _rejouer(FLUX)
    par_id = {p["id"]: p for p in etat["positions"]}
    assert par_id["P_cablage_snn_2"]["supersedes"] == "P_cablage_snn_1"
    assert par_id["P_cablage_snn_1"]["supersedes"] is None, (
        "une premiere position ne remplace rien")
    assert par_id["P_autre_axe_1"]["supersedes"] is None, (
        "la filiation ne doit pas traverser les axes")


def test_le_rejeu_du_meme_flux_rend_le_meme_etat():
    """INVARIANT 4 (NR-7a). Sans lui, aucun event log ni banc SNN n'est possible."""
    a = json.dumps(_rejouer(FLUX), sort_keys=True)
    b = json.dumps(_rejouer(FLUX), sort_keys=True)
    assert a == b, "le rejeu diverge : identifiants non deterministes ?"


def test_les_identifiants_ne_dependent_ni_du_temps_ni_du_hasard():
    """Corollaire de l'invariant 4, teste SEPAREMENT.

    Un id fonde sur un horodatage ou un uuid rendrait le test de rejeu vert
    dans la meme seconde et rouge le lendemain — un garde qui ne mord qu'a
    certaines heures ne garde rien.
    """
    etat = _rejouer(FLUX)
    for p in etat["positions"]:
        assert p["id"].startswith("P_"), p["id"]
        rang = p["id"].rsplit("_", 1)[-1]
        assert rang.isdigit(), "l'identite doit etre un RANG, pas un horodatage"
        assert len(p["id"]) < 80


def test_la_vue_courante_garde_sa_forme():
    """INVARIANT 5. `_ssot_compact` et `agent_testeur` lisent les memes clefs."""
    etat = _rejouer(FLUX)
    vue = etat["axes"]["cablage_snn"]
    for clef in ("statut", "par", "why", "mesure"):
        assert clef in vue, "clef historique disparue : %s" % clef
    assert vue["statut"] == "rejete", "la vue courante doit etre la DERNIERE"
    assert vue["id"] == "P_cablage_snn_2"


def test_le_journal_permet_un_rejeu_reel():
    """NR-7a. Rejouer le JOURNAL, pas un flux ecrit a la main.

    `positions[]` est une PROJECTION : sans les deltas bruts on peut relire
    l'etat, jamais le rejouer. Un test qui rejoue un flux code en dur simule le
    systeme au lieu de le rejouer — c'est cette nuance qui decide si l'invariant
    mesure quelque chose.
    """
    D = _module()
    etat = _rejouer(FLUX)
    reconstruit = D.rejouer(etat["journal"])
    derive = lambda e: {k: e.get(k) for k in ("axes", "tensions", "acquis", "positions")}
    assert derive(reconstruit) == derive(etat), (
        "l'etat reconstruit depuis le journal differe de l'etat courant")


def test_un_tour_muet_reste_au_journal():
    """Une abstention doit rester VISIBLE.

    Un delta sans ligne reconnue n'entre pas dans l'etat, mais s'il disparait du
    journal le rejeu ne reproduit plus le meme decompte de tours, et le silence
    d'un agent devient indiscernable de son absence.
    """
    D = _module()
    etat = _rejouer(FLUX + [("MUET", "(rien de reconnaissable)")])
    assert any("rien de reconnaissable" in e["texte"] for e in etat["journal"])
    reconstruit = D.rejouer(etat["journal"])
    assert len(reconstruit["journal"]) == len(etat["journal"])


def test_le_statut_reste_ferme_et_fail_closed():
    """Ne pas perdre un garde existant en ajoutant la causalite.

    Un statut invente doit toujours retomber au plus bas — c'est ce qui empeche
    un modele de s'auto-promouvoir en `admis`.
    """
    etat = _rejouer([("X", "AXE: nouvel_axe | ADMIS_PAR_MOI_MEME | tentative")])
    assert etat["axes"]["nouvel_axe"]["statut"] == "candidat"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
