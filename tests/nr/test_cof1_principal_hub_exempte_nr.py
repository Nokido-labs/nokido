"""NR 30/10 : COF-1 tranche 1 -- le HUB, principal de service PROUVE, est exempte du refus de lecture des identites.

Mesure COF-1 (22 h d'observation) : 2 027 lectures « aurait_refuse:bac_ring_le_3 », TOUTES des FORGE_TOKEN_* ; 1 320
viennent du hub (tools/nokido_hub.py::_load_agent_tokens, table {agent: jeton} au demarrage). Le hub en a besoin en
CLAIR : comparaison du Bearer (videur) ET codes HMAC des boites aux lettres (forge_mailbox.verify_code) -- des
empreintes seules casseraient le courrier. Plan owner 30/10 (« 3 ok ») : le hub est exempte s'il est PROUVE, par la
meme attestation que les executeurs (parente du process jusqu'au pid que le superviseur declare pour son service).
Une seule primitive : forge_process_inventory.service_porteur. Sans preuve : la decision reste celle d'avant.
"""
from nokido_agent.app import forge_coffre_cloisonne as CC
from nokido_agent.tools import forge_process_inventory as PI

DECLARES = {"NokidoMCP": {"status": "running", "pid": 300},
            "NokidoTaskExecutorAntigravity": {"status": "running", "pid": 500}}


def test_service_porteur_remonte_la_parente():
    service, profondeur, _ = PI.service_porteur(DECLARES, [900, 300, 4])
    assert service == "NokidoMCP" and profondeur == 1


def test_service_porteur_sans_ancetre_declare():
    service, _, motif = PI.service_porteur(DECLARES, [900, 77])
    assert service is None and "aucun ancetre" in motif


def test_service_porteur_superviseur_muet():
    service, _, motif = PI.service_porteur({"__erreur__": {"status": "superviseur injoignable: x"}}, [900, 300])
    assert service is None and "injoignable" in motif


def test_decision_exempte_le_principal_prouve():
    ok, raison = CC.decision_lecture("LaForgeSbxOffline", "identite", 3, ["LaForgeSbxOffline"], "enforce",
                                     principal_exempte="NokidoMCP")
    assert ok is True and raison == "exempte:NokidoMCP"


def test_decision_sans_principal_inchangee():
    assert CC.decision_lecture("LaForgeSbxOffline", "identite", 3, ["LaForgeSbxOffline"], "enforce") == \
        (False, "bac_ring_le_3")
    assert CC.decision_lecture("LaForgeSbxOffline", "identite", 3, ["LaForgeSbxOffline"], "observation") == \
        (True, "aurait_refuse:bac_ring_le_3")


def _principal_pour(monkeypatch, service, profondeur):
    from nokido_agent.app import forge_secrets as S
    monkeypatch.setattr(PI, "service_porteur", lambda *a, **k: (service, profondeur, "essai"))
    monkeypatch.setattr(S, "_PRINCIPAL_MEMO", {})
    return S._principal_exempte()


def test_le_hub_lui_meme_est_exempte(monkeypatch):
    assert _principal_pour(monkeypatch, "NokidoMCP", 0) == "NokidoMCP"


def test_un_job_lance_par_le_hub_n_est_pas_exempte(monkeypatch):
    """30/10, mesure par les NR du coffre : tout run_job DESCEND du hub. Une exemption par simple parente aurait
    couvert tous les jobs du bac -- exactement les lecteurs que COF-1 doit couper. Seul le process du hub (profondeur
    0) est exempte."""
    assert _principal_pour(monkeypatch, "NokidoMCP", 1) is None
    assert _principal_pour(monkeypatch, "NokidoMCP", 3) is None


def test_un_autre_service_n_est_pas_exempte(monkeypatch):
    assert _principal_pour(monkeypatch, "NokidoTaskExecutorAntigravity", 0) is None


def test_observation_journalise_l_exemption_sous_sa_propre_raison(monkeypatch):
    """31/10 : l'exemption ne laissait AUCUNE trace -- « 0 observation du hub » ne distinguait pas « exempte » de « n'a
    rien lu » (le hub n'avait deja plus rien observe apres le 30/10 03 h, AVANT l'exemption). L'exemption s'ecrit,
    sous la raison exempte:<service>, jamais confondue avec un aurait_refuse a traiter."""
    from nokido_agent.app import forge_secrets as S
    journal = []
    monkeypatch.setattr(S, "_compte_du_jeton", lambda: "LaForgeSbxOffline")
    monkeypatch.setattr(S, "_journaliser_observation", lambda *a: journal.append(a))
    monkeypatch.setattr(S, "_principal_exempte", lambda: "NokidoMCP")
    ok, raison = S.observer_lecture_cloisonnee("FORGE_TOKEN_CLAUDE")
    assert ok is True and raison == "exempte:NokidoMCP"
    assert journal == [("FORGE_TOKEN_CLAUDE", "LaForgeSbxOffline", "exempte:NokidoMCP")]
    assert S.OBSERVES_CLOISONNEMENT == [] or all(o["cle"] != "FORGE_TOKEN_CLAUDE" or "exempte" not in o["raison"]
                                                 for o in S.OBSERVES_CLOISONNEMENT)


def test_observation_journalise_toujours_un_client_non_prouve(monkeypatch):
    from nokido_agent.app import forge_secrets as S
    journal = []
    monkeypatch.setattr(S, "_compte_du_jeton", lambda: "LaForgeSbxOffline")
    monkeypatch.setattr(S, "_journaliser_observation", lambda *a: journal.append(a))
    monkeypatch.setattr(S, "_principal_exempte", lambda: None)
    ok, raison = S.observer_lecture_cloisonnee("FORGE_TOKEN_SUPERVISOR_CTL")
    assert raison == "aurait_refuse:bac_ring_le_3" and len(journal) == 1
