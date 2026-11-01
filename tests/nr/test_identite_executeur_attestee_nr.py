"""NR 30/10 : l'identite d'un executeur se PROUVE par l'organe qui le lance, pas par son drapeau --agent.

Mesure : `_identite_executeur` posait `prouve: False` en dur (preuve « non cablee ») ; 1 209 des 1 214 refus de claim
observes venaient de la, et LAFORGE_CLAIM_ENFORCE ne pouvait pas etre arme (enquete
docs/enquetes/identite_executeurs_claim_20261030.md). Preuve cablee : ce process DESCEND du pid que le superviseur
declare pour un service, et ce service porte `--agent <sub>` dans services.toml. Sans cette chaine : non prouve, DIT.
"""
from nokido_agent.tools import forge_task_executor as te

SERVICES = {
    "NokidoTaskExecutorAntigravity": ["${NOKIDO_DEPOT}/tools/forge_task_executor.py", "--agent", "ANTIGRAVITY"],
    "NokidoTaskExecutor": ["${NOKIDO_DEPOT}/tools/forge_task_executor.py"],
}
DECLARES = {"NokidoTaskExecutorAntigravity": {"status": "running", "pid": 500},
            "NokidoTaskExecutor": {"status": "running", "pid": 600}}


def test_descendant_du_service_qui_porte_son_agent_est_prouve():
    ok, preuve = te._attester_par_le_superviseur("ANTIGRAVITY", DECLARES, [900, 500, 4], SERVICES)
    assert ok is True
    assert "NokidoTaskExecutorAntigravity" in preuve


def test_sujet_qui_ne_correspond_pas_au_service_n_est_pas_prouve():
    ok, preuve = te._attester_par_le_superviseur("CODEX", DECLARES, [900, 500, 4], SERVICES)
    assert ok is False
    assert "ANTIGRAVITY" in preuve


def test_generique_sans_agent_est_prouve_par_son_service():
    ok, _ = te._attester_par_le_superviseur("TASK_EXECUTOR", DECLARES, [901, 600], SERVICES)
    assert ok is True


def test_superviseur_injoignable_rend_non_prouve_et_le_dit():
    ok, preuve = te._attester_par_le_superviseur(
        "ANTIGRAVITY", {"__erreur__": {"status": "superviseur injoignable: x"}}, [900, 500], SERVICES)
    assert ok is False
    assert "injoignable" in preuve


def test_aucun_ancetre_declare_rend_non_prouve():
    ok, preuve = te._attester_par_le_superviseur("ANTIGRAVITY", DECLARES, [900, 77, 4], SERVICES)
    assert ok is False
    assert "aucun ancetre" in preuve


def test_identite_attestee_ouvre_la_reclamation(monkeypatch):
    monkeypatch.setattr(te, "_attester_par_le_superviseur", lambda sub, *a, **k: (True, "service X"))
    ident = te._identite_executeur("ANTIGRAVITY")
    assert ident["prouve"] is True
    assert te._autoriser_reclamation("ANTIGRAVITY", ident)[0] is True


def test_identite_non_attestee_reste_non_prouvee(monkeypatch):
    monkeypatch.setattr(te, "_attester_par_le_superviseur", lambda sub, *a, **k: (False, "superviseur injoignable"))
    ident = te._identite_executeur("ANTIGRAVITY")
    assert ident["prouve"] is False
    assert "injoignable" in ident["pourquoi"]
