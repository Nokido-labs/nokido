# -*- coding: utf-8 -*-
"""
PR-A + PR-B routing switchboard : semantic route-table (bge-m3) + façade capacités.
Embedder injecté (offline) pour PR-A. PR-B = pur agrégateur des specs existants.
"""
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from nokido_agent.app import forge_semantic_route as sr  # noqa: E402
from nokido_agent.app import forge_capability_registry as cr  # noqa: E402


# ── Embedder factice déterministe (offline) ──────────────────────────────────
def _fake_embed(texts):
    """Mappe par mots-clés sur des axes orthogonaux → routage déterministe."""
    out = []
    for t in texts:
        tl = t.lower()
        if any(k in tl for k in ("bug", "refactor", "code", "test", "classe", "algorithme", "fonction")):
            out.append([1.0, 0.0, 0.0, 0.0])
        elif any(k in tl for k in ("image", "écran", "screenshot", "interface", "vois", "bouton")):
            out.append([0.0, 1.0, 0.0, 0.0])
        elif any(k in tl for k in ("raisonne", "architecture", "compare", "stratégie", "planifie", "problème")):
            out.append([0.0, 0.0, 1.0, 0.0])
        else:
            out.append([0.0, 0.0, 0.0, 1.0])
    return out


# ── PR-A : semantic route ─────────────────────────────────────────────────────
def test_route_code():
    uc, score = sr.semantic_route("corrige ce bug dans la fonction", embedder=_fake_embed)
    assert uc == "code"
    assert score > 0.5


def test_route_vision():
    uc, _ = sr.semantic_route("que vois-tu sur cette image", embedder=_fake_embed)
    assert uc == "vision"


def test_route_reasoning():
    uc, _ = sr.semantic_route("raisonne sur ce problème complexe", embedder=_fake_embed)
    assert uc == "reasoning"


def test_route_empty_is_general():
    assert sr.semantic_route("", embedder=_fake_embed)[0] == "general"


def test_route_below_threshold_general():
    # vecteur orthogonal à tous les centroïdes connus → fallback general
    uc, _ = sr.semantic_route("xyzzy random", embedder=lambda ts: [[0.0, 0.0, 0.0, 0.0] for _ in ts])
    assert uc == "general"


def test_build_centroids_offline():
    cents = sr.build_centroids(embedder=_fake_embed, learn_from_wins=False)
    assert "code" in cents and "vision" in cents
    assert len(cents["code"]) == 4


# ── Q5 : centroïdes auto-appris depuis dialogue_win ───────────────────────────
def test_centroids_learn_from_wins():
    # un échange réussi "code" enrichit le centroïde code (semi-supervisé)
    wins = lambda: ["corrige ce bug critique dans le code"]  # noqa: E731
    cents = sr.build_centroids(embedder=_fake_embed, learn_from_wins=True, win_fetcher=wins)
    assert "code" in cents
    # le win étant code-ish, le routage d'un texte code reste code
    uc, _ = sr.semantic_route("refactor cette fonction", embedder=_fake_embed)
    assert uc == "code"


def test_learn_from_wins_disabled_ignores_fetcher():
    called = {"n": 0}

    def _f():
        called["n"] += 1
        return ["x"]

    sr.build_centroids(embedder=_fake_embed, learn_from_wins=False, win_fetcher=_f)
    assert called["n"] == 0  # fetcher jamais appelé


def test_fetch_recent_wins_no_crash():
    assert isinstance(sr._fetch_recent_wins(limit=5), list)


# ── Step 2 : routage sémantique LAZY dans call_cascade (use_case="auto") ───────
def test_call_cascade_auto_use_case(monkeypatch):
    from nokido_agent.app import forge_llm_router as flr
    from nokido_agent.app import forge_semantic_route as sr2
    import litellm

    captured = {}

    def fake_completion(**kw):
        captured.update(kw)

        class _M:
            content = "Interface decrite correctement ici."

        class _C:
            message = _M()

        class _R:
            choices = [_C()]
            usage = type("U", (), {"total_tokens": 5})()

        return _R()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    # "auto" doit appeler semantic_route → vision
    monkeypatch.setattr(sr2, "semantic_route", lambda text, **k: ("vision", 0.9))
    monkeypatch.setattr(flr, "USE_CASE_CHAINS", {"vision": ["node_vision"], "general": ["node_other"]})

    r = flr.LLMRouter()
    r._slots = {"node_vision": _RemoteSlot()}

    res = r.call_cascade("décris cette image", use_case="auto", max_tokens=20, timeout=15)
    assert res.get("ok") is True
    assert res.get("provider") == "node_vision"          # résolu vision depuis "auto"
    assert res.get("use_case") == "vision"


# ── PR-B : façade capacités ───────────────────────────────────────────────────
def test_capabilities_of():
    caps = cr.capabilities_of("groq")
    assert "code" in caps
    assert "vision" not in caps


def test_has_capability():
    assert cr.has_capability("claude", "agent") is True
    assert cr.has_capability("groq", "vision") is False


def test_providers_for_vision_includes_gemini_excludes_groq():
    provs = cr.providers_for("vision")
    assert "gemini_flash" in provs
    assert "groq" not in provs


def test_providers_for_free_only_excludes_paid():
    provs = cr.providers_for("code", free_only=True)
    assert "claude" not in provs  # paid_api
    assert any(p in provs for p in ("groq", "ollama_local", "github_codestral"))


def test_summary_counts():
    s = cr.summary()
    assert s.get("code", 0) > 0 and s.get("vision", 0) > 0


# ── PR-C : façade litellm.Router (model_list depuis specs) ────────────────────
from nokido_agent.app import forge_litellm_router as lr  # noqa: E402

_FAKE_PROVIDERS = {
    "p_fast": {"models": ["groq/llama-3.1-8b"], "env_key": "X_KEY", "base_url": None,
               "rpm": 30, "tpm": 6000, "latency": 200, "use_case": ["speed", "code"]},
    "p_local": {"models": ["ollama/qwen2.5"], "env_key": None, "base_url": "http://localhost:11434",
                "rpm": 0, "tpm": 0, "latency": 1500, "use_case": ["code"]},
    "p_vision": {"models": ["gemini/gemini-2.5-flash"], "env_key": "G_KEY", "base_url": None,
                 "rpm": 15, "tpm": 1000000, "latency": 800, "use_case": ["vision"]},
}


def test_model_list_selects_by_use_case():
    ml = lr.build_model_list("code", providers=_FAKE_PROVIDERS)
    names = {m["model_info"]["provider"] for m in ml}
    assert names == {"p_fast", "p_local"}        # vision exclu
    assert all(m["model_name"] == "code" for m in ml)
    assert ml[0]["litellm_params"]["model"].count("/") == 1


def test_model_list_explicit_chain():
    ml = lr.build_model_list("code", chain=["p_local"], providers=_FAKE_PROVIDERS)
    assert len(ml) == 1 and ml[0]["model_info"]["provider"] == "p_local"
    assert ml[0]["litellm_params"]["api_base"] == "http://localhost:11434"


def test_model_list_injects_api_key(monkeypatch):
    monkeypatch.setenv("X_KEY", "secret123")
    ml = lr.build_model_list("speed", providers=_FAKE_PROVIDERS)
    pf = [m for m in ml if m["model_info"]["provider"] == "p_fast"][0]
    assert pf["litellm_params"].get("api_key") == "secret123"
    assert pf["litellm_params"].get("rpm") == 30


def test_model_list_empty_unknown_use_case():
    assert lr.build_model_list("nonexistent_uc", providers=_FAKE_PROVIDERS) == []


# ── PoC : appeler un spécialiste sur un LLM distant (nœud ollama autre IP) ─────
class _RemoteSlot:
    """Simule un nœud ollama distant déclaré dans PROVIDERS (base_url = autre IP)."""
    is_available = True
    is_configured = True
    _cooldown = 0.0
    api_key = "local"
    config = {"models": ["ollama/llava-v1.5"], "base_url": "http://localhost:11434"}

    def record_call(self):
        pass

    def record_failure(self):
        pass

    def record_rate_limit(self, *a):
        pass


def test_remote_node_vision_routing(monkeypatch):
    """Déclarer un nœud distant → call_cascade(use_case=vision) tape son URL en
    format OpenAI, persona injectée. Prouve le pattern bout-en-bout sans nœud live."""
    from nokido_agent.app import forge_llm_router as flr
    import litellm

    captured = {}

    def fake_completion(**kw):
        captured.update(kw)

        class _M:
            content = "Une interface avec un bouton bleu."

        class _C:
            message = _M()

        class _R:
            choices = [_C()]
            usage = type("U", (), {"total_tokens": 12})()

        return _R()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    # vision → notre nœud distant uniquement
    monkeypatch.setattr(flr, "USE_CASE_CHAINS", {"vision": ["minipc2_vision"], "general": ["minipc2_vision"]})

    r = flr.LLMRouter()
    r._slots = {"minipc2_vision": _RemoteSlot()}

    res = r.call_cascade("décris cette image", use_case="vision")

    assert res.get("ok") is True
    assert res.get("provider") == "minipc2_vision"
    # 1. routé vers l'URL du nœud distant
    assert captured["api_base"] == "http://localhost:11434"
    # 2. bon modèle
    assert captured["model"] == "ollama/llava-v1.5"
    # 3. format OpenAI (messages role/content)
    roles = [m["role"] for m in captured["messages"]]
    assert "user" in roles
    # 4. souveraineté : persona Nokido injectée dans le system
    sys_msg = "".join(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "[LAFORGE_PERSONA]" in sys_msg
