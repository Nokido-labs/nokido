"""NR -- un compteur de cache ABSENT de la reponse vaut None (inconnu), jamais 0.

Et le cache lu par ClaudeOpenRouter arrive au journal (log_call) via l'appel DEJA
existant de `_record_provider_call` (pas de second appel : pas de double comptage).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402
from nokido_agent.app.forge_prompt_cache import track_cache_usage  # noqa: E402

def test_dict_sans_compteurs_cache_donne_none():
    s = track_cache_usage({"prompt_tokens": 10, "completion_tokens": 5})
    assert s["cache_hit"] is None and s["cache_write"] is None
    assert s["savings_pct"] is None
    assert s["input"] == 10 and s["output"] == 5

def test_objet_sans_cache_creation_donne_none():
    u = SimpleNamespace(cache_read_input_tokens=100, input_tokens=50, output_tokens=5)
    s = track_cache_usage(u)
    assert s["cache_hit"] == 100
    assert s["cache_write"] is None
    assert s["savings_pct"] is None

def test_zero_explicite_reste_zero():
    s = track_cache_usage({"cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                           "input_tokens": 10, "output_tokens": 1})
    assert s["cache_hit"] == 0 and s["cache_write"] == 0 and s["savings_pct"] == 0.0

def test_donnees_completes_calculent_le_pourcentage():
    s = track_cache_usage({"cache_read_input_tokens": 50, "cache_creation_input_tokens": 0,
                           "input_tokens": 50, "output_tokens": 1})
    assert s["savings_pct"] == 50.0

def test_cache_lu_transmis_a_log_call(monkeypatch):
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, cache_read_input_tokens=100,
                            input_tokens=10, output_tokens=5)
    resp = SimpleNamespace(usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    class _Completions:
        async def create(self, **kw):
            return resp

    class _Client:
        def __init__(self, **kw):
            self.chat = SimpleNamespace(completions=_Completions())

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", _Client)
    monkeypatch.setattr(ap, "_load_api_key", lambda *_a, **_k: "k")
    appels = []
    from nokido_agent.app import forge_token_monitor as tm
    monkeypatch.setattr(tm, "log_call", lambda **kw: appels.append(kw))

    prov = ap.ClaudeOpenRouter()
    tiroir = {}
    jeton = ap._USAGE_RAPPORTE.set(tiroir)
    try:
        out = asyncio.run(prov.ask("salut", [], "sys", 50, 5))
        assert out == "ok"
        ap._record_provider_call(prov, "salut", out, "sys", 1.0, usage=tiroir)
    finally:
        ap._USAGE_RAPPORTE.reset(jeton)
    assert len(appels) == 1
    assert appels[0]["cache_read_tokens"] == 100
    assert appels[0]["cache_write_tokens"] is None
    assert appels[0]["provider"] == prov.name and appels[0]["model"] == prov.model
