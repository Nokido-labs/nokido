# -*- coding: utf-8 -*-
"""NR -- consolidation epistemique de nuit : job detache borne, modele reveille puis DECHARGE (debat tour 3, Q5).

MESURE QUI L'A DECLENCHE. `epistemic_consolidation` sautait ~20 fois par jour : modele local present mais non
charge, chargement > 55 s, au-dela du tick de 60 s. Un modele chaud 24/7 declencherait l'eviction RAM (87,4 %).

Contrat :
  1. le motif ne lance RIEN hors de la fenetre [2 h, 6 h) ; dans la fenetre, AU PLUS un job par nuit ;
  2. apres un echec (MUET / ERREUR / LANE_REFUSEE), recul de 1, 2, 4 nuits (plafond 7) ;
  3. le job s'admet par la lane : refusee -> rien n'est appele ;
  4. reveil muet -> MUET, aucun lot consomme ; dans TOUS les cas admis, le modele est decharge et la lane rendue ;
  5. l'issue et le compte d'echecs consecutifs sont ecrits (remis a zero sur OK).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_autonomous_loops as al  # noqa: E402
from nokido_agent.tools import forge_epistemic_extract_claims as ec  # noqa: E402


def _a(heure: int, jour: int = 15) -> float:
    return time.mktime((2026, 10, jour, heure, 30, 0, 0, 0, -1))


@pytest.fixture
def etat(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "ETAT_NUIT", tmp_path / "consolidation_nuit.json")
    lances = []
    return lances, (lambda cmd: lances.append(cmd) or 4242)


def test_hors_fenetre_rien_n_est_lance(etat):
    lances, lancer = etat
    assert al._consolidation_de_nuit(maintenant=_a(12), lancer=lancer)["etat"] == "HORS_FENETRE"
    assert lances == []


def test_une_seule_fois_par_nuit(etat):
    lances, lancer = etat
    r = al._consolidation_de_nuit(maintenant=_a(3), lancer=lancer)
    assert r == {"etat": "LANCEE", "pid": 4242}
    assert "--nuit" in lances[0] and str(lances[0][2]).endswith("forge_epistemic_extract_claims.py")
    assert al._consolidation_de_nuit(maintenant=_a(4), lancer=lancer)["etat"] == "DEJA_LANCEE_CETTE_NUIT"
    assert len(lances) == 1
    assert al._consolidation_de_nuit(maintenant=_a(3, jour=16), lancer=lancer)["etat"] == "LANCEE"


def test_recul_apres_echecs(etat):
    _lances, lancer = etat
    ec.ecrire_etat_nuit({"lance_ts": _a(3, 14), "fin_ts": _a(3, 14) + 600, "echecs_consecutifs": 2})
    r = al._consolidation_de_nuit(maintenant=_a(3, 15), lancer=lancer)       # 2 echecs -> 2 nuits
    assert r["etat"] == "RECUL" and r["recul_nuits"] == 2
    assert al._consolidation_de_nuit(maintenant=_a(3, 16), lancer=lancer)["etat"] == "LANCEE"


def _job(etat_tmp, reveil="ok", lane=True, consolider_leve=False):
    vus = {"appels": 0, "lots": 0, "decharge": 0, "rendue": 0}

    def appel(prompt, timeout=0):
        vus["appels"] += 1
        return '{"ok": true}' if reveil == "ok" else ""

    def consolider_fn(limit, juge=None):
        if consolider_leve:
            raise RuntimeError("base verrouillee")
        vus["lots"] += 1
        return {"fermees": 0, "promus": 1, "limit": limit}

    r = ec.consolidation_nuit(
        limit=7, appel=appel, consolider_fn=consolider_fn,
        decharger=lambda: vus.__setitem__("decharge", vus["decharge"] + 1) or True,
        admettre=lambda: {"admit": lane, "reason": "lane occupee"},
        liberer=lambda: vus.__setitem__("rendue", vus["rendue"] + 1))
    return r, vus


def test_lane_refusee_rien_n_est_appele(etat):
    r, vus = _job(etat, lane=False)
    assert r["issue"] == "LANE_REFUSEE" and vus == {"appels": 0, "lots": 0, "decharge": 0, "rendue": 0}


def test_reveil_muet_aucun_lot_mais_decharge_et_lane_rendue(etat):
    r, vus = _job(etat, reveil="muet")
    assert r["issue"] == "MUET" and vus["lots"] == 0 and vus["decharge"] == 1 and vus["rendue"] == 1
    assert ec.lire_etat_nuit()["echecs_consecutifs"] == 1


def test_lot_ok_remet_les_echecs_a_zero(etat):
    ec.ecrire_etat_nuit({"echecs_consecutifs": 3})
    r, vus = _job(etat)
    assert r["issue"] == "OK" and r["rapport"]["limit"] == 7 and r["modele_decharge"] is True
    assert vus["decharge"] == 1 and vus["rendue"] == 1
    e = ec.lire_etat_nuit()
    assert e["issue"] == "OK" and e["echecs_consecutifs"] == 0


def test_erreur_du_lot_decharge_quand_meme(etat):
    r, vus = _job(etat, consolider_leve=True)
    assert r["issue"] == "ERREUR" and "base verrouillee" in r["raison"]
    assert vus["decharge"] == 1 and vus["rendue"] == 1
