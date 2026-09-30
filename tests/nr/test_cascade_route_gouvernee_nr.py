# -*- coding: utf-8 -*-
"""La cascade frugale doit joindre les providers par la ROUTE GOUVERNEE.

Recadrage owner 2026-08-30. `forge_frugal_cascade` tapait des URL et des modeles
EN DUR par `urllib`, hors du routeur souverain : sans rotation de cles, sans
circuit breaker, sans RPM, et surtout SANS REPLI LOCAL -- `CASCADE_BY_USE_CASE`
n'aligne que du cloud la ou toutes les chaines de `forge_llm_router` se terminent
par `lmstudio_native` puis `ollama_local`.

Consequence mesuree : les trois tiers cloud rendaient 402 / 403 / 404 et la GUI
generative etait morte, alors que la machine porte un modele local. Les codes HTTP
n'etaient pas le defaut, ils etaient le SYMPTOME du contournement.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _faux_routeur(monkeypatch, reponse: dict):
    mod = types.ModuleType("forge_llm_router")
    mod.get_router = lambda: types.SimpleNamespace(
        call_cascade=lambda *_a, **_kw: reponse)
    monkeypatch.setitem(sys.modules, "forge_llm_router", mod)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_llm_router", mod)
    return mod


def _interdire_appels_directs(monkeypatch):
    """Le chemin `urllib` en dur ne doit PLUS servir quand le routeur repond."""
    import forge_frugal_cascade as fc

    appels = {"n": 0}

    def _interdit(*_a, **_kw):
        appels["n"] += 1
        raise AssertionError("appel direct alors que le routeur a repondu")

    monkeypatch.setattr(fc, "_call_llm", _interdit)
    return appels


def test_succes_du_routeur_renseigne_le_provider_et_la_route(monkeypatch):
    import forge_frugal_cascade as fc

    _faux_routeur(monkeypatch, {"ok": True, "text": "<div>ok</div>",
                                "provider": "ollama_local", "model": "qwen",
                                "elapsed_ms": 42.0,
                                "attempts": [("groq_fast", "429"),
                                             ("ollama_local", None)]})
    _interdire_appels_directs(monkeypatch)

    r = fc.cascade("un prompt", use_case="general")
    assert r["response"] == "<div>ok</div>"
    assert r["model_used"] == "ollama_local"
    assert r["route"] == "routeur souverain"
    # Le repli local a servi APRES un echec cloud : c'est une escalade.
    assert r["escalated"] is True
    assert r["echecs"] == {"groq_fast": "429"}


def test_echec_du_routeur_ne_retombe_pas_sur_les_appels_directs(monkeypatch):
    """Repasser par `urllib` referait exactement le contournement qu'on retire.

    Le routeur a deja essaye la chaine entiere, repli local compris : insister en
    direct ne peut que re-frapper des providers qu'il vient d'ecarter.
    """
    import forge_frugal_cascade as fc

    _faux_routeur(monkeypatch, {"ok": False, "text": "", "provider": None,
                                "elapsed_ms": 10.0,
                                "attempts": [("groq_fast", "402 Payment Required"),
                                             ("ollama_local", "connexion refusee")]})
    appels = _interdire_appels_directs(monkeypatch)

    r = fc.cascade("un prompt")
    assert r["response"] is None
    assert appels["n"] == 0, "aucun appel direct ne doit avoir lieu"
    assert "aucun slot" in r["route"]
    # Les RAISONS remontent, par slot : c'est ce qui manquait au diagnostic.
    assert r["echecs"]["groq_fast"].startswith("402")
    assert r["tiers_tried"] == ["groq_fast", "ollama_local"]


def test_routeur_indisponible_replie_en_le_NOMMANT(monkeypatch):
    """Un repli silencieux ferait passer une panne de routeur pour un choix."""
    import forge_frugal_cascade as fc

    mod = types.ModuleType("forge_llm_router")

    def _boum():
        raise RuntimeError("routeur casse")

    mod.get_router = _boum
    monkeypatch.setitem(sys.modules, "forge_llm_router", mod)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_llm_router", mod)
    # Ici l'ancien chemin a le droit de servir : c'est le SEUL cas.
    monkeypatch.setattr(fc, "_call_llm", lambda *_a, **_kw: "repli direct")

    r = fc.cascade("un prompt")
    assert "routeur indisponible" in r["route"]
    assert r["response"] == "repli direct"
