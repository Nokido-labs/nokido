# -*- coding: utf-8 -*-
"""NR (roadmap P2 convergence census -> matrice, 19/10) : la matrice ne contredit plus le census.

`voies_joignables` (lue par la bascule d'ask) servait les couples JOIGNABLES de la matrice, mesuree une fois
(15/10), meme quand le registre free tier a PROUVE depuis le couple mort (402/404/410) ou en 429 persistant.
Elle consomme desormais `forge_llm_router.injoignables_prouves` -- le MEME contrat que le routeur, aucune
seconde lecture du census -- et NOMME ce qu'elle ecarte. Census illisible : rien n'est ecarte, et c'est dit.
"""
import json
import time

from nokido_agent.tools import forge_provider_catalogue as P
from nokido_agent.app import forge_llm_router as R


def _matrice(tmp_path, monkeypatch):
    fam = P.famille_de("gpt-oss-120b")
    m = {"mesure_le": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "familles": {fam: [{"fournisseur": "groq", "modele": "openai/gpt-oss-120b", "etat": "JOIGNABLE", "latence_ms": 300},
                            {"fournisseur": "cerebras", "modele": "gpt-oss-120b", "etat": "JOIGNABLE", "latence_ms": 200}]}}
    p = tmp_path / "matrice.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(P, "MATRICE", p)


def test_un_couple_prouve_mort_par_le_census_est_ecarte_et_nomme(tmp_path, monkeypatch):
    _matrice(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "injoignables_prouves", lambda *a, **k: {"cerebras:gpt-oss-120b"})
    r = P.voies_joignables("gpt-oss-120b")
    assert [v[0] for v in r["voies"]] == ["groq"]
    assert r["ecartees_census"] == ["cerebras:gpt-oss-120b"] and r["census"] == "lu"


def test_census_illisible_rien_n_est_ecarte_et_c_est_dit(tmp_path, monkeypatch):
    _matrice(tmp_path, monkeypatch)

    def casse(*a, **k):
        raise OSError("illisible")
    monkeypatch.setattr(R, "injoignables_prouves", casse)
    r = P.voies_joignables("gpt-oss-120b")
    assert len(r["voies"]) == 2 and r["census"] == "illisible" and r["ecartees_census"] == []
