"""NR - le digest de veille CAVIARDE sa matiere avant l'envoi cloud (15/10).

Mesure du 15/10 (logs/supervisor/NokidoAutonomousLoops.log) : « digest lot KO : pas de JSON dans la
reponse groq : [FIREWALL] envoi cloud bloque (groq) : DLP : 1 donnees sensibles » a chaque passage.
`pre_flight` est un garde BINAIRE : une seule donnee sensible et tout le lot est refuse. Le digest
passe desormais sa matiere par `redact_text`. L'appel cloud est simule.
"""
from __future__ import annotations

from nokido_agent.app import forge_agent_proxy, forge_veille_digest as V

COURRIEL = "jean.dupont@exemple-veille.fr"


def test_la_donnee_sensible_ne_part_pas_et_la_reponse_est_lue(monkeypatch):
    vus = []

    async def faux_ask(provider, prompt, **_k):
        vus.append(prompt)
        return {"ok": True, "text": '{"suggestions": [{"titre": "t"}]}'}

    monkeypatch.setattr(forge_agent_proxy, "ask", faux_ask)
    r = V._hub_json("groq", "Matiere de veille. Contact : %s. Resume les points utiles." % COURRIEL)
    assert vus and COURRIEL not in vus[0]
    assert "Matiere de veille" in vus[0]
    assert r == {"suggestions": [{"titre": "t"}]}


def test_redacteur_indisponible_n_empeche_pas_l_appel(monkeypatch):
    from nokido_agent.app import forge_semantic_firewall as F

    def _boum(*_a, **_k):
        raise RuntimeError("redacteur hors service")

    vus = []

    async def faux_ask(provider, prompt, **_k):
        vus.append(prompt)
        return {"ok": True, "text": "[]"}

    monkeypatch.setattr(F, "redact_text", _boum)
    monkeypatch.setattr(forge_agent_proxy, "ask", faux_ask)
    assert V._hub_json("groq", "matiere") == {"suggestions": []}
    assert vus == ["matiere"]  # le garde binaire de pre_flight reste seul juge, et c'est journalise
