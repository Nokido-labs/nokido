# -*- coding: utf-8 -*-
"""NR -- tools/forge_ordo_demarrage.py : le rejeu d'un plan de demarrage juge ce qu'il pretend juger.

Le module a ete ajoute sans NR (cliquet test_nr_coverage_ratchet_nr, 31/10). Ce qu'il fige : `rejouer`
denonce un service lance AVANT que sa dependance soit prete, compte les instants ou la RAM depasse le
budget (pic au demarrage, regime ensuite), et nomme les taches reportees -- un plan reporte n'est pas
un plan reussi. Instance a la main : les nombres attendus se recalculent sans le module.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ordo():
    spec = importlib.util.spec_from_file_location("forge_ordo_demarrage_nr", ROOT / "tools" / "forge_ordo_demarrage.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


INST = {"taches": [
    {"nom": "A", "duree": 2, "pic": 500, "ram": 100, "deps": []},
    {"nom": "B", "duree": 1, "pic": 300, "ram": 50, "deps": ["A"]},
    {"nom": "C", "duree": 1, "pic": 10, "ram": 10, "deps": []},
]}


def test_un_service_lance_avant_sa_dependance_est_denonce():
    r = _ordo().rejouer(INST, {"A": 0, "B": 1}, budget_mo=None)
    assert r["violations_deps"] == [{"tache": "B", "dep": "A", "debut": 1, "dep_pret": 2}], r
    assert r["reportes"] == ["C"]


def test_plan_valide_profil_ram_et_depassements_du_budget():
    r = _ordo().rejouer(INST, {"A": 0, "B": 2}, budget_mo=450)
    assert r["violations_deps"] == []
    # u0,u1 : A au pic (500) ; u2 : A en regime (100) + B au pic (300) ; u3 : 100 + 50
    assert r["profil"] == [500, 500, 400, 150], r["profil"]
    assert r["pic_ram_mo"] == 500 and r["fin"] == 3
    assert r["instants_hors_budget"] == 2


def test_budget_inconnu_ne_compte_aucun_depassement():
    """UNKNOWN n'est pas NO : sans budget mesure, on ne fabrique pas de depassement -- 0, pas une panne."""
    r = _ordo().rejouer(INST, {"A": 0, "B": 2, "C": 0}, budget_mo=None)
    assert r["instants_hors_budget"] == 0 and r["reportes"] == []
