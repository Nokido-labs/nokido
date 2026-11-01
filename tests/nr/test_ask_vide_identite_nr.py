"""NR: provider vide et acteur resolu restent explicites dans les sinks, sans reseau.

Repris de 5c9d9158c (CODEX, 23/10) sans son 3e test : celui-ci imposait que le hub
ecrase le nom declare par le principal, refuse a la relecture (le hub porte desormais
les deux, cf. 04b231cab / b314096c0)."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("OTEL_SDK_DISABLED", "true")
AP = pytest.importorskip("nokido_agent.app.forge_agent_proxy")


class _ProviderVide(AP.Provider):
    name = "nr_fake_empty"
    model = "nr_fake_model"
    display_name = "NR fake"
    api_key_env = None
    cost_tier = 0

    def is_available(self):
        return True

    async def ask(self, message, thread_messages, system_prompt, max_tokens, timeout):
        return ""


def test_ask_provider_vide_est_un_echec_explicite(monkeypatch):
    provider = _ProviderVide()
    monkeypatch.setattr(AP, "get_provider", lambda name: provider if name == provider.name else None)
    monkeypatch.setattr(AP, "_record_provider_call", lambda *a, **k: None)
    monkeypatch.setattr(AP, "_emit", lambda *a, **k: None)
    import nokido_agent.app.forge_network_logger as netlog
    monkeypatch.setattr(netlog, "log_cloud_out", lambda *a, **k: None)
    monkeypatch.setattr(netlog, "log_cloud_in", lambda *a, **k: None)

    result = asyncio.run(AP.ask(provider.name, "message neutre", rag_context=False, raw=True))

    assert result["ok"] is False, result
    assert result["error"] == "Provider returned empty response"


def test_acteur_resolu_atteint_token_monitor_et_evenements_cloud(monkeypatch):
    import nokido_agent.app.forge_trace_context as trace
    import nokido_agent.app.forge_token_monitor as monitor
    import nokido_agent.app.forge_network_logger as netlog

    calls = []
    monkeypatch.setattr(netlog, "log_cloud_out", lambda *a, **kw: calls.append(("out", a[2])))
    monkeypatch.setattr(netlog, "log_cloud_in", lambda *a, **kw: calls.append(("in", a[2])))
    monkeypatch.setattr(AP, "_emit", lambda *a, **k: None)
    import nokido_agent.app.forge_langfuse_hook as langfuse
    monkeypatch.setattr(langfuse, "emit", lambda *a, **k: None)
    monkeypatch.setattr(AP, "_citer_reponse", lambda *a, **k: None)
    monkeypatch.setattr(AP, "_borner_contexte", lambda msgs, system, msg, provider: (msgs, 0))
    monkeypatch.setattr(AP, "_get_thread", lambda tid: ("nr-thread", []))
    monkeypatch.setattr(AP, "_get_rag_context", lambda *a, **k: "")
    monkeypatch.setattr(AP, "_add_to_thread", lambda *a, **k: None)
    monkeypatch.setattr(monitor, "log_call", lambda **kw: calls.append(("token", kw.get("agent_id"))))
    fake = _ProviderVide()

    async def answer(*a, **k):
        return "reponse"
    fake.ask = answer
    monkeypatch.setattr(AP, "get_provider", lambda name: fake)

    jeton_ctx = trace.set_actor("PRINCIPAL_RESOLU", ring=1, channel="MCP", transport="http")
    try:
        result = asyncio.run(AP.ask(fake.name, "prompt prive", rag_context=False, raw=True))
    finally:
        trace.reset_actor(jeton_ctx)

    assert result["ok"] is True
    assert [kind for kind, _ in calls] == ["out", "token", "in"]
    assert all(agent == "PRINCIPAL_RESOLU" for _, agent in calls), calls
    assert "prompt prive" not in repr(calls)


# --- Extension 23/10 : principal / declared ADDITIFS, `agent` garde son sens ---------------
import ast
import json


def test_actor_context_un_principal_deux_declared_et_agent_distincts():
    import nokido_agent.app.forge_trace_context as trace

    vus = []
    for decl in ("CLAUDE_DESKTOP", "CLAUDE_HEADLESS"):
        tok = trace.set_actor(decl, principal="AGT_CLAUDE", declared=decl, ring=1)
        try:
            vus.append(trace.get_actor())
        finally:
            trace.reset_actor(tok)
    assert {a["principal"] for a in vus} == {"AGT_CLAUDE"}
    assert [a["declared"] for a in vus] == ["CLAUDE_DESKTOP", "CLAUDE_HEADLESS"]
    assert [a["agent"] for a in vus] == ["CLAUDE_DESKTOP", "CLAUDE_HEADLESS"]  # agent != principal
    assert [a["ring"] for a in vus] == [1, 1]


def test_set_actor_sans_principal_le_deduit_de_agent():
    import nokido_agent.app.forge_trace_context as trace

    tok = trace.set_actor("X", ring=1)
    try:
        a = trace.get_actor()
    finally:
        trace.reset_actor(tok)
    assert (a["agent"], a["principal"], a["declared"]) == ("X", "X", "UNKNOWN")


def test_net_log_audit_porte_principal_declared_et_garde_agent(monkeypatch):
    import nokido_agent.app.forge_trace_context as trace
    import nokido_agent.app.forge_network_logger as netlog

    vus = []
    monkeypatch.setattr(netlog, "_get_audit", lambda: lambda tool, args, status: vus.append(args))
    tok = trace.set_actor("CLAUDE_CLI", principal="AGT_CLAUDE", declared="CLAUDE_CLI", ring=1)
    try:
        netlog.net_log(netlog.NetworkChannel.HUB, netlog.Direction.IN, method="initialize",
                       agent="CLAUDE_CLI", ring=1)
    finally:
        trace.reset_actor(tok)
    assert vus[0]["principal"] == "AGT_CLAUDE"
    assert vus[0]["declared"] == "CLAUDE_CLI"
    assert vus[0]["agent"] == "CLAUDE_CLI"


def test_token_monitor_et_cloud_transmettent_principal_declared_sans_changer_agent(monkeypatch):
    import nokido_agent.app.forge_trace_context as trace
    import nokido_agent.app.forge_token_monitor as monitor
    import nokido_agent.app.forge_network_logger as netlog
    import nokido_agent.app.forge_langfuse_hook as langfuse

    calls = []
    monkeypatch.setattr(netlog, "log_cloud_out", lambda *a, **kw: calls.append(("out", a[2], kw)))
    monkeypatch.setattr(netlog, "log_cloud_in", lambda *a, **kw: calls.append(("in", a[2], kw)))
    monkeypatch.setattr(monitor, "log_call", lambda **kw: calls.append(("token", kw.get("agent_id"), kw)))
    monkeypatch.setattr(AP, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(langfuse, "emit", lambda *a, **k: None)
    monkeypatch.setattr(AP, "_citer_reponse", lambda *a, **k: None)
    monkeypatch.setattr(AP, "_borner_contexte", lambda msgs, system, msg, provider: (msgs, 0))
    monkeypatch.setattr(AP, "_get_thread", lambda tid: ("nr-thread", []))
    monkeypatch.setattr(AP, "_get_rag_context", lambda *a, **k: "")
    monkeypatch.setattr(AP, "_add_to_thread", lambda *a, **k: None)
    fake = _ProviderVide()

    async def answer(*a, **k):
        return "reponse"
    fake.ask = answer
    monkeypatch.setattr(AP, "get_provider", lambda name: fake)

    tok = trace.set_actor("CLAUDE_DESKTOP", principal="AGT_CLAUDE", declared="CLAUDE_DESKTOP", ring=1)
    try:
        asyncio.run(AP.ask(fake.name, "p", rag_context=False, raw=True))
    finally:
        trace.reset_actor(tok)
    assert [k for k, _, _ in calls] == ["out", "token", "in"]
    for _, agent, kw in calls:
        assert agent == "CLAUDE_DESKTOP"
        assert kw["principal"] == "AGT_CLAUDE"
        assert kw["declared"] == "CLAUDE_DESKTOP"


def _mcp_post():
    tree = ast.parse((ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "mcp_post")


def test_mcp_post_agent_garde_la_declaration_et_principal_vient_de_resolve_ring():
    mp = _mcp_post()
    assigns = {}
    for n in sorted((n for n in ast.walk(mp) if isinstance(n, ast.Assign)), key=lambda n: n.lineno):
        for t in n.targets:
            if isinstance(t, ast.Name):
                assigns.setdefault(t.id, ast.unparse(n.value))  # 1re affectation
    # agent_hdr : en-tete declare s'il existe, sinon auth_agent (semantique d'origine)
    assert "auth_agent" in assigns["agent_hdr"] and "X-Agent-Name" in assigns["agent_hdr"]
    assert "UNKNOWN" not in assigns["agent_hdr"]
    assert "auth_agent" in assigns["principal"] and "headers" not in assigns["principal"]
    assert "X-Agent-Name" in assigns["declared_agent"]
    call = next(n for n in ast.walk(mp) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "set_actor")
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "agent_hdr"
    kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
    assert kw["principal"] == "principal" and kw["declared"] == "declared_agent" and kw["ring"] == "ring"
    # ring<0 -> principal UNKNOWN
    assert any(isinstance(n, ast.If) and "ring < 0" in ast.unparse(n.test) and "UNKNOWN" in ast.unparse(n)
               for n in ast.walk(mp))


def test_delegation_journalisee_avec_delegue_par_sans_changer_via(monkeypatch, tmp_path):
    import forge_videur as v

    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LAFORGE_DATA_DIR", raising=False)
    v._emettre_evenement_auth("B", "jeton", {"via": "delegated:A", "agent": "B", "ring": 1}, "P")
    v._emettre_evenement_auth("B", "jeton", {"via": "token", "agent": "B", "ring": 1}, "P")
    lignes = [json.loads(x) for x in
              (tmp_path / "sandbox" / "logs" / "auth_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lignes[0]["via"] == "token" and lignes[0]["delegue_par"] == "A"
    assert lignes[1]["via"] == "token" and lignes[1]["delegue_par"] == ""


def test_jeton_partage_deux_en_tetes_meme_principal_aucun_ring_par_en_tete(monkeypatch):
    from types import SimpleNamespace
    import nokido_hub as hub

    monkeypatch.setattr(hub, "HUB_TOKEN", "jeton-maitre-nr", raising=False)
    monkeypatch.setattr(hub, "_AGENT_TOKENS", {"AGT_CLAUDE": "partage-nr"}, raising=False)
    rings = []
    for nom in ("CLAUDE_DESKTOP", "CLAUDE_HEADLESS"):
        req = SimpleNamespace(headers={"LaForge-Agent-Name": nom, "Authorization": "Bearer partage-nr"},
                              client=SimpleNamespace(host="127.0.0.1"))
        rings.append(hub._resolve_ring(req)[0])
    assert rings[0] == rings[1]
    sans = SimpleNamespace(headers={"LaForge-Agent-Name": "AGT_CLAUDE"},
                           client=SimpleNamespace(host="127.0.0.1"))
    assert hub._resolve_ring(sans)[0] < 0
