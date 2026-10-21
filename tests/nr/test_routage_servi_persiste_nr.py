"""NR -- le modele SERVI et la chaine des tentatives survivent jusqu'a la ligne d'usage.

Audit pair E du 19/10 (docs/audit/routage_demande_vs_servi.md, sections 5.1/5.2/5.4) :
quand `forge_agent_proxy` passe par le routeur (`RouterCascadeProvider`), `call_cascade`
produit un dict complet (`served_model`, `attempts`) mais `RouterCascadeProvider.ask` ne
rend QUE le texte. Le proxy ecrit donc `provider='router'`, `model='cascade qualite (use_case
auto)'` -- les 95 appels du 12 au 19/10 ne disent NULLE PART quel modele a reellement repondu
ni combien de maillons ont echoue avant.

Second volet (5.4) : sur 396 appels proxy en 7 j, seuls 19 (4,8 %) portent un comptage
REPORTED, parce que la SEULE classe `Groq` appelle `_noter_usage_rapporte(resp)`. Les autres
fournisseurs OpenAI-compat recoivent pourtant le meme `resp.usage` et le jettent.

Ce qui est garde ici, par le chemin REEL, sans reseau :

  1. un appel servi via le routeur ecrit `served_model` ET le nombre de tentatives dans la
     ligne d'usage ;
  2. valeur inconnue = NULL, jamais un modele devine ;
  3. tout fournisseur OpenAI-compat dont la reponse PORTE `usage` est note REPORTED -- pas
     seulement Groq ;
  4. un fournisseur OpenAI-compat SANS usage rendu reste compte ESTIMATED (temoin negatif :
     on ne fabrique pas un REPORTED).

Auteur : OPENCODE_NEMOTRON (job_d4e2061c), integre par CLAUDE depuis la sauvegarde de l'executeur.
"""
from __future__ import annotations

import asyncio
import sys
import types as _types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402
from nokido_agent.app import forge_token_monitor as tm  # noqa: E402


@pytest.fixture(autouse=True)
def _pas_de_reseau_ni_de_persona(monkeypatch):
    monkeypatch.setenv("FORGE_PERSONA_INJECT", "0")
    monkeypatch.setenv("FORGE_AGENTPROXY_FIREWALL", "0")


def _capturer(monkeypatch):
    vus: list[dict] = []
    monkeypatch.setattr(tm, "log_call", lambda **k: vus.append(k))
    monkeypatch.setattr(tm, "count_text_tokens", lambda texte, *a, **k: len(texte.split()))
    return vus


class _BoucleInline:
    """Loop-proxy dont `run_in_executor` execute l'appel EN LIGNE, dans le contexte
    appelant et sur la boucle REELLEMENT en cours d'execution.

    Reproduit fidelement la traversee `RouterCascadeProvider.ask -> call_cascade`
    sans thread : le tiroir d'usage (ContextVar depose par `ask_tracked`) reste
    partage par reference, exactement comme sur le chemin reel. Le Future doit
    appartenir a la boucle qui tourne, sinon `asyncio.wait` refuse un objet d'une
    autre boucle."""

    def run_in_executor(self, executor, fn, *a):
        fut = asyncio.get_running_loop().create_future()
        try:
            fut.set_result(fn(*a))
        except Exception as e:  # noqa: BLE001
            fut.set_exception(e)
        return fut


def _router_par_ask_tracked(monkeypatch, cascade: dict):
    faux = SimpleNamespace(call_cascade=lambda *a, **k: cascade)
    faux_mod = _types.ModuleType("nokido_agent.app.forge_llm_router")
    faux_mod.get_router = lambda: faux
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_llm_router", faux_mod)

    monkeypatch.setattr(asyncio, "get_event_loop", lambda: _BoucleInline())

    vus = _capturer(monkeypatch)
    asyncio.run(ap.RouterCascadeProvider().ask_tracked("bonjour", [], "systeme", 64, 10))
    assert len(vus) == 1, "log_call atteint %d fois" % len(vus)
    return vus[0]


def test_routeur_ecrit_le_modele_servi_et_les_tentatives(monkeypatch):
    cascade = {
        "ok": True,
        "text": "une reponse servie",
        "provider": "mistral_small",
        "model": "mistral-small-latest",
        "requested_model": "mistral-small-latest",
        "served_model": "mistral-small-latest-2026",
        "attempts": [("openrouter_gpt_oss", "402"), ("mistral_small", "429")],
    }
    k = _router_par_ask_tracked(monkeypatch, cascade)
    assert k.get("served_model") == "mistral-small-latest-2026", (
        "le modele SERVI n'arrive pas dans la ligne d'usage : %r" % k.get("served_model"))
    assert k.get("attempts") == 2, (
        "le nombre de tentatives n'arrive pas dans la ligne d'usage : %r" % k.get("attempts"))


def test_routeur_modele_servi_inconnu_reste_null(monkeypatch):
    cascade = {"ok": True, "text": "x", "served_model": "UNKNOWN", "attempts": []}
    k = _router_par_ask_tracked(monkeypatch, cascade)
    assert k.get("served_model") is None, (
        "un modele servi inconnu a ete ecrit en clair : %r" % k.get("served_model"))
    assert k.get("attempts") == 0


def _fournisseur_par_ask_tracked(monkeypatch, classe, usage):
    class _Completions:
        async def create(self, **kw):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=usage)

    class _Client:
        def __init__(self, *a, **k):
            self.chat = SimpleNamespace(completions=_Completions())

    faux_openai = _types.ModuleType("openai")
    faux_openai.AsyncOpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", faux_openai)

    vus = _capturer(monkeypatch)
    monkeypatch.setattr(ap, "_load_api_key", lambda *a, **k: "cle-factice")
    assert asyncio.run(classe().ask_tracked("bonjour", [], "systeme", 32, 10)) == "ok"
    assert len(vus) == 1, "log_call atteint %d fois" % len(vus)
    return vus[0]


def _usage(prompt=1200, completion=40):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                           prompt_tokens_details=SimpleNamespace(cached_tokens=1024))


def test_un_fournisseur_quelconque_note_le_reporting_pas_seulement_groq(monkeypatch):
    k = _fournisseur_par_ask_tracked(monkeypatch, ap.MistralLarge, _usage())
    assert k.get("measurement_kind") == "REPORTED", (
        "un fournisseur OpenAI-compat hors Groq ne note pas le reporting : %r"
        % k.get("measurement_kind"))
    assert (k.get("prompt_tokens"), k.get("completion_tokens")) == (1200, 40)
    assert k.get("cache_read_tokens") == 1024


def test_sans_usage_rendu_on_retombe_sur_l_estimation(monkeypatch):
    k = _fournisseur_par_ask_tracked(monkeypatch, ap.MistralLarge, None)
    assert k.get("measurement_kind") == "ESTIMATED", (
        "une reponse SANS usage rendu a ete comptee %r" % k.get("measurement_kind"))


def test_le_writer_porte_served_model_et_attempts():
    """Schema additif : les deux colonnes sont declarees pour la migration."""
    from nokido_agent.app import forge_llm_usage_adapters as ad
    assert "served_model" in ad.COLONNES_AJOUTEES
    assert "attempts" in ad.COLONNES_AJOUTEES
