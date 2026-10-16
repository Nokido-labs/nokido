"""NR - un fournisseur RETIRE n'est plus route et le dit ; un swarm ne joint que les joignables (15/10).

Owner 15/10 : « gpt4o_github n'existe plus, a supprimer ; si des cles sont absentes, pourquoi tenter
de les joindre ? ». Mesures du jour : GitHub Models rend 410 Gone depuis le 18/08, et pourtant
`forge_task_router` le mettait EN TETE de la revue de code ; le swarm de debat sondait openai et
perplexity, cles absentes. Aucun appel reseau ici.
"""
from __future__ import annotations

import asyncio

from nokido_agent.app import forge_agent_proxy as AP
from nokido_agent.app import forge_llm_router_dt as DT
from nokido_agent.app import forge_provider_alias as AL
from nokido_agent.app import forge_task_router as TR


def test_gpt4o_github_n_est_plus_enregistre_et_un_appel_dit_pourquoi():
    assert "gpt4o_github" not in AP._PROVIDERS
    r = asyncio.run(AP.ask("gpt4o_github", "ping", rag_context=False, raw=True, max_tokens=8, timeout=5))
    assert r["ok"] is False and "RETIRE" in r["error"] and "410" in r["error"]


def test_plus_aucune_route_vers_le_retire():
    assert "gpt4o_github" not in TR.PROVIDERS
    for tache, liste in TR.ROUTING.items():
        assert "gpt4o_github" not in liste, tache
    assert all(regle[2] != "gpt4o_github" for regle in DT._BOOTSTRAP)
    # L'emplacement reste dans la liste du routeur DT (indices du modele persiste), mais redirige.
    assert DT._RETIRES_REDIRIGES["gpt4o_github"] == "groq"
    assert all(v is None for k, v in AL.ALIAS.items() if k.startswith("github_"))
    assert "gpt4o_github" in AL.RETIRES


def test_joignables_ecarte_cle_absente_et_cle_refusee(monkeypatch):
    class _P:
        def __init__(self, dispo):
            self._d = dispo

        def is_available(self):
            return self._d

    monkeypatch.setattr(AP, "_PROVIDERS", {"groq": _P(True), "openai": _P(False), "grok": _P(True)})
    assert AP.fournisseurs_joignables() == ["groq"]  # openai : cle absente ; grok : CLEF_REFUSEE (prepaye)
