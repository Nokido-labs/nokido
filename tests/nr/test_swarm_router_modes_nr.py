# -*- coding: utf-8 -*-
"""La couche a preuves du router : fanout, arret sur sûrete, abstention.

Aucun appel reseau : `route_subtask` est remplace par un double, ce qui est
justement le point -- la couche doit se comporter correctement QUELLE QUE SOIT
la fiabilite de ce qu'il y a en dessous.
"""
from __future__ import annotations

import pytest

from app import forge_swarm_router as R


@pytest.fixture
def double(monkeypatch):
    """Remplace le routage single-shot par une reponse programmee par angle."""
    appels = []

    def _poser(reponses):
        def _faux(agent_cible, task_prompt, **kw):
            angle = task_prompt.rsplit("[ANGLE IMPOSE]", 1)[-1].strip()
            appels.append(angle)
            rep = reponses[len(appels) - 1] if len(appels) <= len(reponses) else reponses[-1]
            return rep
        monkeypatch.setattr(R, "route_subtask", _faux)
        return appels

    return _poser


def _ok(texte, provider="qwen3-coder"):
    return {"status": "ok", "result": texte, "provider_used": provider}


def _ko(motif, provider="qwen3-coder"):
    return {"status": "error", "reason": motif, "provider_used": provider}


def test_un_refus_de_surete_arrete_le_fanout(double):
    """Sinon on cherche le provider qui accepte ce qu'un garde a refuse."""
    appels = double([_ko("REFUS DU GARDE: secret en clair"), _ok("A"), _ok("A")])
    v = R.route_swarm("CLAUDE", "tache", politique="critique")
    assert len(appels) == 1, "le fanout a insiste apres un refus de sûrete"
    assert v["etat"] == "REJECTED" and v["action"] == "abstain"


def test_un_quota_epuise_n_arrete_pas_la_tache(double):
    """Changer de source est justement ce qu'il faut faire ici."""
    appels = double([_ko("cle ECARTEE par la rotation"), _ok("A"), _ok("A")])
    R.route_swarm("CLAUDE", "tache", politique="important")
    assert len(appels) == 3, "un quota a ete pris pour un verdict sur la tache"


def test_une_dependance_cassee_ne_se_retente_pas(double):
    appels = double([_ko("ModuleNotFoundError: no module named zzz"), _ok("A")])
    R.route_swarm("CLAUDE", "tache", politique="important")
    assert len(appels) == 1, "reessayer ne fera pas apparaitre le module manquant"


def test_sans_verificateur_le_critique_ne_conclut_jamais(double):
    """Un swarm sans preuve deterministe doit le DIRE, pas conclure."""
    double([_ok("A"), _ok("A"), _ok("A"), _ok("A"), _ok("A")])
    v = R.route_swarm("CLAUDE", "tache", politique="critique")
    assert v["action"] != "accept"
    assert v["etat"] == "UNKNOWN" and v["status"] == "pending"


def test_avec_preuves_le_quorum_conclut(double):
    double([_ok("A"), _ok("A"), _ok("A")])
    v = R.route_swarm("CLAUDE", "tache", politique="important",
                      verificateur=lambda t: (True, ["test::x"]))
    assert v["action"] == "accept" and v["result"] == "A"
    assert v["voix_independantes"] >= 2


def test_un_verificateur_en_panne_ne_vaut_pas_un_test_vert(double):
    """La porte deterministe qui casse doit degrader vers l'abstention."""
    def _hs(_):
        raise RuntimeError("porte HS")

    double([_ok("A"), _ok("A"), _ok("A")])
    v = R.route_swarm("CLAUDE", "tache", politique="important", verificateur=_hs)
    assert v["action"] != "accept"


def test_deux_solutions_prouvees_appellent_un_contradicteur(double):
    double([_ok("solution A"), _ok("solution B"), _ok("solution A")])
    v = R.route_swarm("CLAUDE", "tache", politique="important",
                      verificateur=lambda t: (True, ["test::" + t[-1]]))
    assert v["etat"] == "CONTESTED" and v["action"] == "challenge"


def test_le_mode_single_reste_un_seul_appel(double):
    """Compatibilite : la politique simple ne doit rien multiplier."""
    appels = double([_ok("A")])
    R.route_swarm("CLAUDE", "tache", politique="simple")
    assert len(appels) == 1


def test_le_mode_adversarial_pose_l_angle_contradicteur(double):
    appels = double([_ok("A")] * 5)
    R.route_swarm("CLAUDE", "tache", politique="critique")
    assert R.ANGLES["adversaire"] in appels
    assert len(appels) == 5


def test_empreinte_ignore_blancs_et_casse():
    """Deux formulations identiques ne doivent pas compter comme deux solutions."""
    assert R._empreinte("def f():\n  return 1") == R._empreinte("def  F():\n\n   RETURN 1".lower())
    assert R._empreinte("") == ""


def test_politique_ou_mode_inconnu_est_refuse():
    assert R.route_swarm("CLAUDE", "t", politique="nimporte")["status"] == "error"
    assert R.route_swarm("CLAUDE", "t", mode="nimporte")["status"] == "error"


def test_toutes_les_tentatives_sont_tracees(double):
    double([_ko("timeout"), _ok("A"), _ok("A")])
    v = R.route_swarm("CLAUDE", "tache", politique="important",
                      verificateur=lambda t: (True, ["test::x"]))
    assert len(v["tentatives"]) == 3
    assert v["tentatives"][0]["classe"] == "TRANSPORT_TIMEOUT"
    assert all("angle" in t for t in v["tentatives"])
