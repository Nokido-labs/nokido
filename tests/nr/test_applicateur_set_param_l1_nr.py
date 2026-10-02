"""NR -- l'action L1 `set_param` de l'applicateur (mission regeneration du 2026-10-01).

Note RSI §2.2 : le premier niveau de la boucle proposer -> verifier -> appliquer -> mesurer
est un PARAMETRE, parce que c'est le plus reversible. Ce NR fige les quatre conditions :
  1. liste BLANCHE : un parametre non declare reste CORTICAL, une valeur non conforme est
     REFUSEE (jamais executee) ;
  2. la porte d'evolution : CORTICAL tant qu'elle n'est pas ARMEE -- absente ou illisible
     vaut FERMEE (INCONNU) ;
  3. la valeur PRECEDENTE est memorisee : le retour redonne l'empreinte d'avant, a l'octet ;
  4. arme, l'acte passe par le controleur : une regression mesuree est defaite et marquee
     `rolled_back`, un gain dans la bande est garde.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from nokido_agent.app import forge_autonomous_loops as al
from nokido_agent.app import forge_mutation_controller as mc
from nokido_agent.app import forge_mutation_judge as juge
from nokido_agent.app import forge_proposal_applier as pa

DECL = {"seuil_x": {"type": "float", "min": 0.0, "max": 1.0, "defaut": 0.5,
                    "mesure": "inutilise:inutilise", "bruit": {"score": 0.01}}}


@pytest.fixture
def l1(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARAMS_L1_FICHIER", tmp_path / "parametres_l1.json")
    monkeypatch.setattr(pa, "PARAMS_L1", json.loads(json.dumps(DECL)))
    monkeypatch.setattr(al, "_EVOLUTION_LEDGER", tmp_path / "evolution_experiences.jsonl")
    monkeypatch.setattr(al, "_ensure_ledger_migrated", lambda: None)
    monkeypatch.setattr(mc, "_generation_avant", lambda: None)
    return tmp_path


def _porte(monkeypatch, etat):
    monkeypatch.setattr(juge, "evolution_autorisee",
                        lambda: {"autorisee": etat == "ARMEE", "etat": etat, "motif": "nr"},
                        raising=False)


def _etage(action, conf=0.9, porte=None):
    return pa._etage_set_param(action, conf, porte or pa.porte_evolution())


# ── 1. liste blanche et conformite ───────────────────────────────────────────────────
def test_parametre_non_declare_reste_cortical(l1, monkeypatch):
    _porte(monkeypatch, "ARMEE")
    etage, motif = _etage({"type": "set_param", "param": "inconnu", "valeur": 1})
    assert etage == "CORTICAL" and "liste blanche" in motif


@pytest.mark.parametrize("valeur", [1.5, -0.1, True, "0.3", None])
def test_valeur_non_conforme_est_refusee(l1, monkeypatch, valeur):
    _porte(monkeypatch, "ARMEE")
    etage, _ = _etage({"type": "set_param", "param": "seuil_x", "valeur": valeur})
    assert etage == "REFUSE"


def test_sans_mesure_declaree_reste_cortical(l1, monkeypatch):
    _porte(monkeypatch, "ARMEE")
    pa.PARAMS_L1["seuil_x"].pop("mesure")
    etage, motif = _etage({"type": "set_param", "param": "seuil_x", "valeur": 0.7})
    assert etage == "CORTICAL" and "mesure" in motif


# ── 2. la porte ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("etat", ["DESARMEE", "HALTED", "VERROU_HUMAIN", "INCONNU"])
def test_porte_fermee_rend_cortical(l1, monkeypatch, etat):
    _porte(monkeypatch, etat)
    etage, motif = _etage({"type": "set_param", "param": "seuil_x", "valeur": 0.7})
    assert etage == "CORTICAL" and etat in motif


def test_porte_absente_ou_qui_leve_vaut_fermee(l1, monkeypatch):
    monkeypatch.delattr(juge, "evolution_autorisee", raising=False)
    assert pa.porte_evolution() == {"autorisee": False, "etat": "INCONNU",
                                    "motif": pa.porte_evolution()["motif"]}

    def _boum():
        raise RuntimeError("porte cassee")
    monkeypatch.setattr(juge, "evolution_autorisee", _boum, raising=False)
    p = pa.porte_evolution()
    assert p["autorisee"] is False and p["etat"] == "INCONNU" and "porte cassee" in p["motif"]


def test_porte_armee_et_confiance_suffisante_rend_reflexe(l1, monkeypatch):
    _porte(monkeypatch, "ARMEE")
    assert _etage({"type": "set_param", "param": "seuil_x", "valeur": 0.7})[0] == "REFLEXE"
    assert _etage({"type": "set_param", "param": "seuil_x", "valeur": 0.7}, conf=0.5)[0] == "CORTICAL"


# ── 3. valeur precedente memorisee, retour a l'octet ────────────────────────────────
def test_retour_redonne_l_empreinte_d_avant_cle_absente(l1):
    avant = pa.empreinte_l1()
    trace = pa._set_param({"param": "seuil_x", "valeur": 0.7})
    assert trace["ok"] and pa.valeur_l1("seuil_x") == 0.7 and pa.empreinte_l1() != avant
    pa._restaurer_param(trace)
    assert pa.empreinte_l1() == avant and pa.valeur_l1("seuil_x") == 0.5  # defaut declare


def test_retour_redonne_l_entree_precedente_entiere(l1):
    t1 = pa._set_param({"param": "seuil_x", "valeur": 0.2, "exp_id": "e1"})
    assert t1["ok"]
    avant = pa.empreinte_l1()
    entree_avant = pa._lire_l1()["seuil_x"]
    t2 = pa._set_param({"param": "seuil_x", "valeur": 0.9, "exp_id": "e2"})
    assert pa._lire_l1()["seuil_x"]["precedente"] == entree_avant  # memorisee DANS le magasin
    pa._restaurer_param(t2)
    assert pa.empreinte_l1() == avant and pa._lire_l1()["seuil_x"] == entree_avant


# ── 4. de bout en bout dans l'applicateur ───────────────────────────────────────────
def _base(action, conf=0.95):
    cx = sqlite3.connect(":memory:")
    cx.execute("CREATE TABLE orchestrator_recommendations (id INTEGER, param TEXT, confidence REAL,"
               " evidence TEXT, reason TEXT, applied_at TEXT)")
    cx.execute("INSERT INTO orchestrator_recommendations VALUES (1,'seuil_x',?,?,'r',NULL)",
               (conf, json.dumps({"action": action})))
    return cx


@pytest.fixture
def armee(l1, monkeypatch):
    _porte(monkeypatch, "ARMEE")
    monkeypatch.setenv("LAFORGE_APPLIER_ARMED", "1")
    marques = []
    monkeypatch.setattr(pa, "_marquer", lambda i, par, rolled_back: marques.append(
        (i, rolled_back)) or True)
    # Mesure declaree : le score SUIT le reglage. Au-dela de 0.6, la capacite s'effondre.
    monkeypatch.setattr(pa, "_mesure_declaree", lambda nom: (
        lambda: {"score": 1.0 if pa.valeur_l1("seuil_x") <= 0.6 else 0.2}))
    return marques


def test_desarme_aucun_reglage_n_est_pose(l1, monkeypatch):
    _porte(monkeypatch, "ARMEE")
    monkeypatch.delenv("LAFORGE_APPLIER_ARMED", raising=False)
    monkeypatch.setattr(pa, "_conn_ro", lambda: _base({"type": "set_param", "param": "seuil_x",
                                                       "valeur": 0.4}))
    r = pa.appliquer()
    assert r["dry_run"] is True and r["actes"] == [] and pa._lire_l1() == {}


def test_arme_un_reglage_dans_la_bande_est_garde(armee, monkeypatch):
    monkeypatch.setattr(pa, "_conn_ro", lambda: _base({"type": "set_param", "param": "seuil_x",
                                                       "valeur": 0.4}))
    r = pa.appliquer()
    (acte,) = r["actes"]
    assert acte["verdict"] == "CONSERVE" and acte["succes"] is True
    assert pa.valeur_l1("seuil_x") == 0.4 and armee == [(1, False)]


def test_arme_une_regression_est_defaite_et_prouvee(armee, monkeypatch):
    avant = pa.empreinte_l1()
    monkeypatch.setattr(pa, "_conn_ro", lambda: _base({"type": "set_param", "param": "seuil_x",
                                                       "valeur": 0.9}))
    r = pa.appliquer()
    (acte,) = r["actes"]
    assert acte["verdict"] == "REVERTE", acte
    assert acte["preuve"]["empreinte_identique"] and acte["preuve"]["mesure_revenue_dans_bande"]
    assert pa.empreinte_l1() == avant and armee == [(1, True)]
    assert al.verifier_chaine_evolution()["ok"] is True


def test_porte_serree_entre_plan_et_acte_rien_n_est_pose(armee, monkeypatch):
    """La porte est RELUE par le controleur juste avant l'acte (frein tire entre-temps)."""
    monkeypatch.setattr(pa, "_conn_ro", lambda: _base({"type": "set_param", "param": "seuil_x",
                                                       "valeur": 0.4}))
    p = pa.plan()
    assert p[0]["etage"] == "REFLEXE"
    monkeypatch.setattr(pa, "plan", lambda: p)
    _porte(monkeypatch, "HALTED")
    r = pa.appliquer()
    (acte,) = r["actes"]
    assert acte["verdict"] == "HALTED" and acte["fait"] is False
    assert pa._lire_l1() == {} and armee == []
