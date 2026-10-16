"""NR -- la surface swarm ne rend jamais une coroutine comme reponse (debat anatomie du 15/10 : le participant litellm
appelait `forge_litellm_bridge.ask`, ASYNCHRONE, sans l'attendre -> `'coroutine' object has no attribute 'strip'`,
session entiere perdue)."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_une_erreur_en_texte_n_est_jamais_une_reponse():
    # Debat anatomie du 15/10 : 3 participants sur 9 comptes `ok=True` avec une chaine d'erreur.
    from nokido_agent.app import forge_swarm_team as st
    rr = st.LeadOrchestrator._reponse_reelle
    for faux in ("[groq error] HTTP Error 403: Forbidden", "[router error] boom", "[litellm error] x",
                 "litellm.BadRequestError: OpenAIException - modele inconnu", "Traceback (most recent call last):",
                 "", "   ", None, object()):
        assert rr(faux) is False, faux
    assert rr("Voici une reponse structuree en 3 points") is True
    assert rr("Une erreur de prediction coute cher : [groq error] cite dans le texte") is True


def test_le_participant_litellm_rend_un_texte(monkeypatch):
    faux = types.ModuleType("forge_litellm_bridge")

    async def ask(task, context="", max_tokens=500, **_k):
        return "reponse:" + task[:5]
    faux.ask = ask
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_litellm_bridge", faux)
    from nokido_agent.app import forge_swarm_team as st
    r = st.LeadOrchestrator()._litellm_call("bonjour le corps", "", {})
    assert isinstance(r, str) and r == "reponse:bonjo"
