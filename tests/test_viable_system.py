"""forge_viable_system — planification multi-pool (fonctions PURES, sans hub).

Vérifie : niveau VSM, couplage provider round-robin (2 CLI OAuth alternés),
structure du plan + détection CLI OAuth + groupement par pool.
"""
import importlib

import pytest

vs = importlib.import_module("forge_viable_system")


@pytest.fixture(autouse=True)
def _no_quota_skip(monkeypatch):
    # déterminisme : par défaut le tracker quota ne skip rien (tests quota override localement)
    monkeypatch.setattr("forge_provider_quota.should_skip", lambda p: False, raising=False)


def test_level_of_agent_recursive():
    assert vs.level_of("agent_cryptographe") == "S1"
    assert vs.level_of("agent_pentester_red_teamer") == "S1"


def test_level_of_organs():
    assert vs.level_of("forge_immunitaire_firewall") == "S5"
    assert vs.level_of("forge_resource_manager_vegetatif") == "S3"
    assert vs.level_of("forge_cognition_agent") == "S4"


def test_assign_provider_round_robin_clis(monkeypatch):
    # force codex présent pour tester l'alternance 3-CLI non figée
    monkeypatch.setitem(vs.PROVIDER_TIERS, "reason_premium", ["claude_cli", "gemini_cli", "codex_cli"])
    rr = {}
    seq = [vs.assign_provider({"name": f"r{i}", "tier": "reason_premium"}, rr) for i in range(4)]
    assert seq == ["claude_cli", "gemini_cli", "codex_cli", "claude_cli"]


def test_quota_aware_skips_exhausted(monkeypatch):
    monkeypatch.setattr("forge_provider_quota.should_skip", lambda p: p == "gemini_cli", raising=False)
    rr = {}
    seq = [vs.assign_provider({"name": f"r{i}", "tier": "reason_premium"}, rr) for i in range(4)]
    assert "gemini_cli" not in seq and "claude_cli" in seq  # gemini épuisé -> évité


def test_quota_all_exhausted_falls_local(monkeypatch):
    monkeypatch.setattr("forge_provider_quota.should_skip", lambda p: True, raising=False)
    p = vs.assign_provider({"name": "x", "tier": "reason_premium"})
    assert p.startswith("ollama")  # tout cloud épuisé -> repli LOCAL gratuit (token economy)


def test_plan_couples_cli_local_cloud():
    roles = [
        {"name": "architecte", "tier": "reason_premium", "pool": "design"},
        {"name": "reviewer", "tier": "reason_premium", "pool": "design"},
        {"name": "bulk1", "tier": "bulk_local", "pool": "grind"},
        {"name": "fast1", "tier": "fast_cloud", "pool": "grind"},
    ]
    plan = vs.plan_orchestration("macro X", roles, "test1")
    # 2 CLI OAuth simultanés détectés
    assert set(plan["cli_oauth"]) == {"claude_cli", "gemini_cli"}
    # local + cloud présents
    provs = " ".join(plan["providers_used"])
    assert "ollama" in provs and ("groq" in provs or "cerebras" in provs)
    # groupement par pool
    assert set(plan["pools"]) == {"design", "grind"}
    assert len(plan["pools"]["design"]) == 2


def test_default_tier_is_local():
    plan = vs.plan_orchestration("m", [{"name": "x"}], "t2")
    assert plan["assignments"][0]["provider"].startswith("ollama")


def test_no_claude_gemini_api():
    # garde anti-API : jamais 'claude'/'gemini' bare (payant/429) -> CLI OAuth
    assert vs._safe_provider("claude") == "claude_cli"
    assert vs._safe_provider("gemini") == "gemini_cli"
    assert vs._safe_provider("anthropic") == "anthropic_cli"
    assert vs._safe_provider("claude_cli") == "claude_cli"
    assert vs._safe_provider("groq:llama-3.3-70b-versatile") == "groq:llama-3.3-70b-versatile"
    # rôle avec provider API explicite -> redirigé vers le CLI
    assert vs.assign_provider({"name": "x", "provider": "gemini"}) == "gemini_cli"
    assert vs.assign_provider({"name": "y", "provider": "claude"}) == "claude_cli"


def test_s5_gate_allocation():
    r = vs.s5_gate_allocation("CLAUDE", tool=None, local=True)
    assert "allow" in r


def test_algedonic_to_police():
    assert vs.algedonic_to_police({"severity": "critical"})["escalate"] is True
    assert vs.algedonic_to_police({"severity": "low"})["escalate"] is False


def test_loop_status():
    s = vs.loop_status()
    assert "loops" in s and "all_closed" in s and "open" in s


def test_execute_plan_serve_fn_seam():
    plan = vs.plan_orchestration("m", [{"name": "a", "tier": "bulk_local", "pool": "p"}], "sf1")
    called = {}

    def serve(allowed):
        called["n"] = len(allowed)
        return "served"

    res = vs.execute_plan(plan, serve_fn=serve)
    assert res["pools"]["p"] == "served" and called["n"] == 1


def test_serve_via_swarm_router_compo():
    # compo #2 : execute_plan -> serve_via_swarm_router -> route_subtask (mocke) par membre
    plan = vs.plan_orchestration("m", [
        {"name": "arch", "tier": "reason_premium", "pool": "p", "task": "design"},
        {"name": "rev", "tier": "reason_premium", "pool": "p", "task": "review"}], "sr1")
    calls = []

    def fake_route(agent_cible, task_prompt, tool_vise, token, local, use_case):
        calls.append((agent_cible, use_case))
        return {"status": "ok", "result": f"served {agent_cible}"}

    res = vs.execute_plan(plan, serve_fn=lambda m: vs.serve_via_swarm_router(m, _route_fn=fake_route))
    assert len(calls) == 2 and calls[0][1] == "reason_premium"  # tier -> use_case
    assert any("served arch" in str(r) for r in res["pools"]["p"])


def test_read_my_inbox_scoped(monkeypatch):
    captured = {}

    def fake_read_zone(zone):
        captured["zone"] = zone
        return [{"key": "p1", "value": "{}"}]

    monkeypatch.setattr("forge_swarm_blackboard.read_zone", fake_read_zone, raising=False)
    r = vs.read_my_inbox("gemini_cli")
    assert captured["zone"] == "orchestration_inbox_GEMINI" and r[0]["key"] == "p1"
