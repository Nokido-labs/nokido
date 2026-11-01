"""NR -- conseiller souverain : cas d'usage `conseil`, fournisseur ollama_cloud, escalade free -> Claude en dernier.
Faux fournisseurs : aucun reseau."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_llm_router as lr  # noqa: E402
from nokido_agent.tools.forge_provider_catalogue import OLLAMA_CLOUD_FREE  # noqa: E402

OC = ("ollama_cloud_ultra", "ollama_cloud_gptoss")
URL = "https://ollama.com/v1"


def _resp(txt):
    m = types.SimpleNamespace(content=txt)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m)],
                                 usage=types.SimpleNamespace(total_tokens=3), model="x")


def _prepare(monkeypatch, comportement):
    """comportement(model, api_base) -> texte ou leve. Cles factices, pas de sonde, pas de reseau."""
    import litellm
    appels = []

    def faux(**kw):
        appels.append((kw["model"], kw.get("api_base")))
        return _resp(comportement(kw["model"], kw.get("api_base")))

    monkeypatch.setattr(litellm, "completion", faux)
    monkeypatch.setattr(lr.ProviderSlot, "is_configured", property(lambda s: True))
    monkeypatch.setattr(lr.ProviderSlot, "api_key", property(lambda s: "k"))
    monkeypatch.setattr(lr, "capacite_epuisee", lambda p: None)
    monkeypatch.setattr(lr, "_emit_nervous_event", lambda *a, **k: None)
    monkeypatch.setattr(lr, "_capter_capacite", lambda *a, **k: None)
    monkeypatch.setattr(lr, "_emettre_effort", lambda *a, **k: None)
    monkeypatch.setattr(lr, "_slots_prouves_morts", lambda n: set())
    monkeypatch.setattr(lr, "_REPLIS_RECENTS", [])
    monkeypatch.setattr(lr, "LLMRouter", lr.LLMRouter)
    return appels


def _routeur():
    return lr.LLMRouter()  # instance neuve : pas d'etat de cooldown herite


def test_chaine_conseil_ordre_et_modeles_du_catalogue():
    ch = lr.USE_CASE_CHAINS["conseil"]
    assert ch[:2] == list(OC)
    assert ch[2] == "groq_gpt_oss_120b"
    assert ch[3:] == ["nvidia_nemotron_super", "mistral_large", "openrouter_free"]
    for n in OC:
        cfg = lr.PROVIDERS[n]
        assert cfg["base_url"] == URL and cfg["env_key"] == "OLLAMA_API_KEY"
        for m in cfg["models"]:
            assert m.split("/", 1)[1] in OLLAMA_CLOUD_FREE


def test_aucun_modele_ollama_cloud_hors_catalogue():
    for cfg in lr.PROVIDERS.values():
        if cfg.get("base_url") == URL:
            for m in cfg["models"]:
                assert lr.palier_ollama_cloud_ok(m)
    assert lr.palier_ollama_cloud_ok("openai/nemotron-3-ultra")
    assert not lr.palier_ollama_cloud_ok("openai/kimi-k2-thinking")


def test_ollama_429_bascule_sur_groq(monkeypatch):
    def comp(model, base):
        if base == URL:
            raise RuntimeError("429 quota exceeded (weekly usage limit)")
        return "avis groq"
    appels = _prepare(monkeypatch, comp)
    r = _routeur().call_cascade("q", use_case="conseil", max_tokens=64, max_attempts=6)
    assert r["ok"] and r["provider"] == "groq_gpt_oss_120b"
    assert [a for a in appels if a[1] == URL]
    assert len(r["attempts"]) >= 2


def test_tous_free_epuises_repli_oauth_appele(monkeypatch):
    def comp(model, base):
        raise RuntimeError("429 rate limit")
    _prepare(monkeypatch, comp)
    vus = []

    def proxy(f, p, s, m, t):
        vus.append(f)
        return {"ok": True, "text": "avis claude", "model": "m"}
    monkeypatch.setattr(lr, "_demander_au_proxy", proxy)
    r = _routeur().call_cascade("q", use_case="conseil", max_tokens=64, max_attempts=6)
    assert r["ok"] and r["provider"] in ("gemini_cli", "claude_cli") and vus


def test_appel_reel_frugal_opt_in():
    """Opt-in (NOKIDO_APPEL_REEL=1) : UN appel reel max_tokens 64 ; ne s'execute jamais en CI."""
    import os
    import pytest
    if os.environ.get("NOKIDO_APPEL_REEL") != "1":
        pytest.skip("opt-in : NOKIDO_APPEL_REEL=1")
    out = lr.conseiller("test", "ping", "reponds ok", max_tokens=64)
    print("FOURNISSEUR_REEL=", out["fournisseur"], [e[0] for e in out["escalade"]], out["erreur"])
    assert out["fournisseur"], out["escalade"]


def test_conseiller_borne_et_dit_l_escalade(monkeypatch):
    def comp(model, base):
        if base == URL:
            raise RuntimeError("429 quota")
        return "x" * 5000
    _prepare(monkeypatch, comp)
    monkeypatch.setattr(lr, "get_router", _routeur)
    out = lr.conseiller("tache", "etape", "contexte de la tache. " * 2500)
    assert out["contexte_tronque"] is True
    assert {"avis", "fournisseur", "escalade"} <= set(out)
    assert out["fournisseur"] == "groq_gpt_oss_120b"
    assert len(out["avis"]) <= lr.CONSEIL_AVIS_MAX and out["tronque"] is True
    assert any(e[0] in OC for e in out["escalade"])
