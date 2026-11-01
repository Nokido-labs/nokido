"""NR regle d'or : payload d'agent sans tools -> journalise (observation, jamais de refus)."""
import asyncio
import logging
from types import SimpleNamespace

from app import forge_agent_proxy as fap
from app import forge_handoff as fh


def _outil(x: str = "a") -> str:
    """outil de test"""
    return x


def _agent(provider, model="code", with_tools=True):
    return SimpleNamespace(
        instructions="sys", mode="EXECUTE", provider=provider, model=model,
        tools=[_outil] if with_tools else [],
    )


def test_handoff_agent_porteur_d_outils_sans_tools_journalise(monkeypatch, caplog):
    """Tout envoi EFFECTIF sans outils alors que l'agent en porte est journalise."""
    envoyes = []
    monkeypatch.setattr(fh, "_call_router_provider",
                        lambda flat, provider=None: envoyes.append(flat) or {"message": {"content": "x"}})
    n0 = fh.REGLE_D_OR_INERTES
    with caplog.at_level(logging.WARNING):
        r = fh._llm_round(_agent("groq"), [{"role": "user", "content": "hi"}], False)
    assert r and envoyes  # aucun refus, l'envoi a bien eu lieu
    assert "agent inerte : payload sans tools" in caplog.text
    assert fh.REGLE_D_OR_INERTES == n0 + 1


def test_handoff_transport_outils_en_echec_aucun_envoi_sans_outils(monkeypatch):
    """Mode outils en echec : rien ne part sans outils (donc rien a journaliser), l'erreur remonte."""
    envoyes = []
    monkeypatch.setattr(fh, "_call_router_provider", lambda *a, **k: envoyes.append(a) or {})
    monkeypatch.setattr(fh, "_call_router", lambda *a, **k: envoyes.append(a) or {})
    monkeypatch.setattr(fh, "_cloud_slot_info", lambda p: (_ for _ in ()).throw(RuntimeError("down")))
    r = fh._llm_round(_agent("groq"), [{"role": "user", "content": "hi"}], True)
    assert not envoyes
    assert r["_router_meta"]["ok"] is False and r["message"]["content"] == ""


def test_handoff_agent_avec_tools_transmis_ne_journalise_pas(monkeypatch, caplog):
    seen = {}

    def fake(model, full, tools=None, **kw):
        seen["tools"] = tools
        return {"message": {"content": "x"}}

    monkeypatch.setattr(fh, "_call_ollama_chat", fake)
    with caplog.at_level(logging.WARNING):
        fh._llm_round(_agent("ollama_local"), [{"role": "user", "content": "hi"}], True)
    assert seen["tools"]
    assert "agent inerte" not in caplog.text


def test_handoff_agent_sans_outils_ne_journalise_pas(monkeypatch, caplog):
    monkeypatch.setattr(fh, "_call_router_provider", lambda flat, provider=None: {"message": {"content": "x"}})
    with caplog.at_level(logging.WARNING):
        fh._llm_round(_agent("groq", with_tools=False), [{"role": "user", "content": "hi"}], True)
    assert "agent inerte" not in caplog.text


class _Prov:
    model = "m"
    display_name = "P"
    api_key_env = "X"

    def is_available(self):
        return True

    async def ask_tracked(self, **kw):
        assert "tools" not in kw
        return "reponse"


def _ask(monkeypatch, tools):
    monkeypatch.setattr(fap, "get_provider", lambda name: _Prov())
    return asyncio.run(fap.ask("p", "salut", rag_context=False, raw=True, tools=tools, _bascule=False))


TOOL = [{"name": "t", "description": "d", "inputSchema": {"type": "object", "properties": {}}}]


def test_proxy_ask_avec_tools_journalise_non_transmis(monkeypatch, caplog):
    n0 = fap.REGLE_D_OR_TOOLS_NON_TRANSMIS
    with caplog.at_level(logging.WARNING):
        r = _ask(monkeypatch, TOOL)
    assert r["ok"] is True
    assert "PAS transmis au fournisseur" in caplog.text
    assert fap.REGLE_D_OR_TOOLS_NON_TRANSMIS == n0 + 1


def test_proxy_ask_texte_sans_tools_ne_journalise_rien(monkeypatch, caplog):
    n0 = fap.REGLE_D_OR_TOOLS_NON_TRANSMIS
    with caplog.at_level(logging.WARNING):
        r = _ask(monkeypatch, None)
    assert r["ok"] is True
    assert "PAS transmis" not in caplog.text
    assert fap.REGLE_D_OR_TOOLS_NON_TRANSMIS == n0
