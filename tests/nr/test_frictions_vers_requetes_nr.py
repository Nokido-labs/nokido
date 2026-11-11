"""NR : une friction observee devient une requete d'ingenierie generale, sans LLM ni nom interne ; rien n'est lance.

Idee de l'owner 6/11 : chercher ce qui existe au lieu de resoudre a l'aveugle. Mode ombre : on liste, on mesure le bruit.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from nokido_agent.app.forge_epistemic_veille import frictions_vers_requetes  # noqa: E402


def test_friction_connue_donne_une_requete_generale_dedoublonnee():
    r = frictions_vers_requetes([
        {"kind": "attestation_commit_anterieur", "target": "job_1"},
        {"kind": "attestation_contredite", "target": "job_2"},
        {"kind": "ci_en_echec", "target": "CI"},
    ])
    assert r["mode"] == "OMBRE"
    assert len(r["requetes"]) == 2
    a = next(q for q in r["requetes"] if q["famille"] == "fausse_livraison")
    assert a["n"] == 2
    for q in r["requetes"]:
        assert not any(mot in q["requete"].lower() for mot in ("nokido", "forge_", "job_", "laforge"))


def test_requetes_courtes_seule_forme_qui_trouve_au_banc():
    r = frictions_vers_requetes([{"kind": "ci_en_echec"}, {"kind": "flap"}, {"kind": "attestation_contredite"}])
    for q in r["requetes"]:
        assert 2 <= len(q["requete"].split()) <= 3, q["requete"]
        assert q["variantes"], q["famille"]
        assert all(2 <= len(v.split()) <= 3 for v in q["variantes"])


def test_friction_inconnue_est_comptee_pas_devinee():
    r = frictions_vers_requetes([{"kind": "truc_neuf"}])
    assert r["requetes"] == []
    assert r["non_traduites"] == {"truc_neuf": 1}


def test_decision_owner_nest_pas_une_friction():
    r = frictions_vers_requetes([{"kind": "commits_non_pousses"}, {"kind": "submodule_non_bumpe"}])
    assert r["requetes"] == [] and r["non_traduites"] == {}
    assert r["ecartees_decision_owner"] == 2


def test_source_illisible_se_dit():
    r = frictions_vers_requetes(None)
    assert r["etat"] == "ILLISIBLE" and r["requetes"] == []
