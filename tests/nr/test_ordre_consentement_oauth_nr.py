"""NR 3/11 — E4 du plan OAuth MCP : le consentement d'un client OAuth passe par le TRAY, et lui seul decide.

Contrat :
  * le hub depose un ordre `oauth-consentement` a valider, cible = identifiant de la demande ;
  * seul un consommateur PROUVE (TRAY/MASTER) prend l'ordre ; une fois pris, il attend une DECISION ;
  * `decider` n'accepte QUE le consommateur qui a pris l'ordre : un agent (CLAUDE, CODEX...) ne peut pas approuver
    son propre client OAuth -- sinon le consentement owner ne protegerait rien ;
  * decision a usage UNIQUE, bornee dans le temps ; le decideur enregistre recoit (cible, oui) ;
  * sans decideur enregistre : la decision est REFUSEE et DITE (jamais un octroi silencieux).
"""
import pytest

from app import forge_ordres_bureau as B


@pytest.fixture(autouse=True)
def propre(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "JOURNAL", tmp_path / "ordres.jsonl")
    monkeypatch.setattr(B, "_ORDRES", [])
    monkeypatch.setattr(B, "_A_DECIDER", {})
    monkeypatch.setattr(B, "_DECIDEURS", {})
    yield


def _deposer_et_prendre(qui="TRAY", t=1000.0):
    o = B.deposer("oauth-consentement", "HUB", "VS Code demande l'acces (mcp:hub)", maintenant=t, a_valider=True,
                  cible="demande-123")
    pris = B.prendre(qui, maintenant=t + 1)
    assert pris["etat"] == B.ORDRE and pris["ordre"]["cible"] == "demande-123" and pris["ordre"]["a_valider"]
    return o["id"]


def test_tray_decide_oui_et_le_decideur_recoit_la_cible():
    recus = []
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui: recus.append((cible, oui)) or "url")
    oid = _deposer_et_prendre()
    r = B.decider("TRAY", oid, True, maintenant=1010.0)
    assert r["etat"] == "DECIDE" and recus == [("demande-123", True)]


def test_un_agent_ne_peut_pas_decider():
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui: "url")
    oid = _deposer_et_prendre()
    for agent in ("CLAUDE", "CODEX", "HUB", ""):
        assert B.decider(agent, oid, True, maintenant=1010.0)["etat"] == B.REFUSE


def test_seul_celui_qui_a_pris_decide():
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui: "url")
    oid = _deposer_et_prendre(qui="TRAY")
    assert B.decider("MASTER", oid, True, maintenant=1010.0)["etat"] == B.REFUSE


def test_decision_unique():
    recus = []
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui: recus.append(oui) or "url")
    oid = _deposer_et_prendre()
    assert B.decider("TRAY", oid, False, maintenant=1010.0)["etat"] == "DECIDE"
    assert B.decider("TRAY", oid, True, maintenant=1011.0)["etat"] == B.REFUSE
    assert recus == [False]


def test_decision_echue_refusee():
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui: "url")
    oid = _deposer_et_prendre()
    assert B.decider("TRAY", oid, True, maintenant=1001.0 + B.DUREE_DECISION_S + 1)["etat"] == B.REFUSE


def test_sans_decideur_refus_dit():
    oid = _deposer_et_prendre()
    r = B.decider("TRAY", oid, True, maintenant=1010.0)
    assert r["etat"] == B.REFUSE and "decideur" in r["raison"]


def test_la_decision_passe_par_la_porte_generique_demander_ordre():
    # Le registre ne bouge pas (« les ordres suivants s'ajoutent dans forge_ordres_bureau, plus ici ») : le tray
    # repond par `hub action=demander_ordre ordre=decision-oui|decision-non cible=<ordre>`.
    import asyncio
    import time
    recus = []
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui: recus.append(oui) or "url")
    oid = _deposer_et_prendre(t=time.time())     # demander_ordre decide au temps REEL : l'ordre aussi doit l'etre
    assert asyncio.run(B.demander_ordre("CLAUDE", "decision-oui", cible=oid))["etat"] == B.REFUSE
    assert recus == []
    r = asyncio.run(B.demander_ordre("TRAY", "decision-non", cible=oid))
    assert r["etat"] == "DECIDE" and recus == [False]


def test_decision_oui_ring1_transmet_le_ring_choisi_au_tray():
    # 3/11 (decision owner « ring choisi au tray + inscrit au registre ») : la 2e fenetre du tray (droits eleves ?)
    # repond decision-oui-ring1 ; le decideur recoit ring=1. decision-oui garde l'appel historique (cible, oui).
    import asyncio
    import time
    recus = []
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui, **k: recus.append((cible, oui, k)) or "url")
    oid = _deposer_et_prendre(t=time.time())
    r = asyncio.run(B.demander_ordre("TRAY", "decision-oui-ring1", cible=oid))
    assert r["etat"] == "DECIDE" and recus == [("demande-123", True, {"ring": 1})]
    oid2 = _deposer_et_prendre(t=time.time())
    asyncio.run(B.demander_ordre("TRAY", "decision-oui", cible=oid2))
    assert recus[-1] == ("demande-123", True, {})


def test_ring_hors_borne_refuse():
    B.enregistrer_decideur("oauth-consentement", lambda cible, oui, **k: "url")
    oid = _deposer_et_prendre()
    assert B.decider("TRAY", oid, True, maintenant=1010.0, ring=0)["etat"] == B.REFUSE


def test_revocation_demandee_par_un_agent_decidee_par_le_tray():
    # 3/11 (owner « fais revoquer_client ») : un agent DEMANDE (oauth-revoquer), l'owner DECIDE au tray.
    import asyncio
    import time
    recus = []
    B.enregistrer_decideur("oauth-revocation", lambda cible, oui: recus.append((cible, oui)) or "fait")
    r = asyncio.run(B.demander_ordre("CLAUDE", "oauth-revoquer", raison="client abandonne", cible="nkc_vieux"))
    assert r["etat"] == B.DEPOSE and r["a_valider"] is True
    pris = B.prendre("TRAY", maintenant=time.time())
    assert pris["ordre"]["action"] == "oauth-revocation" and pris["ordre"]["cible"] == "nkc_vieux"
    assert B.decider("CLAUDE", pris["ordre"]["id"], True)["etat"] == B.REFUSE          # l'agent ne decide pas
    assert B.decider("TRAY", pris["ordre"]["id"], True)["etat"] == "DECIDE" and recus == [("nkc_vieux", True)]


def test_revocation_sans_cible_refusee():
    import asyncio
    assert asyncio.run(B.demander_ordre("CLAUDE", "oauth-revoquer", cible=""))["etat"] == B.REFUSE


def test_ordre_ordinaire_n_attend_pas_de_decision():
    o = B.deposer("tailscale-statut", "CLAUDE", maintenant=1000.0)
    B.prendre("TRAY", maintenant=1001.0)
    assert B.decider("TRAY", o["id"], True, maintenant=1002.0)["etat"] == B.REFUSE
