# -*- coding: utf-8 -*-
"""
test_forge_policy_rego.py — Tests unitaires pour l'évaluateur Rego/OPA.
"""
from __future__ import annotations

import pytest
from app.forge_policy_rego import evaluate

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus opa (code appele) (l.19)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

def test_allow_ring0():
    # Ring 0 SYSTEM-VERIFIED bypass toutes les restrictions
    inp = {
        "actor_agent": "GEMINI",
        "ring": 0,
        "system_verified": True,
        "action": "edit",
        "target_module": "app/forge_pool_registry.py"  # Fichier critique
    }
    res = evaluate(inp)
    assert res["allow"] is True
    assert "Ring 0" in res["reason"]


def test_deny_ring0_no_flag_on_critical():
    # Ring 0 SANS system_verified (default/spoof) ne bypasse PAS : module critique
    # reste protege (durcissement anti catch-all ring==0).
    inp = {
        "actor_agent": "GEMINI",
        "ring": 0,
        "action": "edit",
        "target_module": "app/forge_pool_registry.py"
    }
    res = evaluate(inp)
    assert res["allow"] is False

def test_deny_edit_critical_module_ring_greater_than_0():
    # Un agent de ring > 0 (comme 1 ou 2) ne doit pas pouvoir éditer un module critique
    inp = {
        "actor_agent": "CLAUDE",
        "ring": 1,
        "action": "edit",
        "target_module": "app/forge_pool_registry.py"
    }
    res = evaluate(inp)
    assert res["allow"] is False
    assert "forbidden" in res["reason"] or "OPA_DENY" in res["reason"]

def test_deny_edit_new_critical_module_alignment_invariants():
    # Test Nit A1: forge_alignment_invariants doit être protégé
    inp = {
        "actor_agent": "CLAUDE",
        "ring": 1,
        "action": "edit",
        "target_module": "app/forge_alignment_invariants.py"
    }
    res = evaluate(inp)
    assert res["allow"] is False
    assert "forbidden" in res["reason"] or "OPA_DENY" in res["reason"]

def test_allow_governed_edit_non_critical_module_ring_1():
    # Test Nit A2: governed_edit non critique ring 1 -> ALLOW
    inp = {
        "actor_agent": "CLAUDE",
        "ring": 1,
        "action": "governed_edit",
        "target_module": "app/some_random_module.py"
    }
    res = evaluate(inp)
    assert res["allow"] is True

def test_allow_edit_non_critical_module_ring_less_than_equal_to_1():
    # Un agent de ring 1 peut éditer un module non critique
    inp = {
        "actor_agent": "CLAUDE",
        "ring": 1,
        "action": "edit",
        "target_module": "app/some_random_module.py"
    }
    res = evaluate(inp)
    assert res["allow"] is True

def test_deny_edit_non_critical_module_ring_greater_than_1():
    # Un agent de ring 2 ne peut pas éditer un module non critique de Nokido
    inp = {
        "actor_agent": "GEMINI",
        "ring": 2,
        "action": "edit",
        "target_module": "app/some_random_module.py"
    }
    res = evaluate(inp)
    assert res["allow"] is False

def test_deny_self_validation():
    # Un agent ne doit pas pouvoir s'auto-valider
    inp = {
        "actor_agent": "CLAUDE",
        "ring": 1,
        "action": "validate_task",
        "target_agent": "CLAUDE"
    }
    res = evaluate(inp)
    assert res["allow"] is False
    assert "own task work" in res["reason"] or "self" in res["reason"] or "OPA_DENY" in res["reason"]

def test_deny_same_lineage_validation():
    # Deux agents de même lignée ne doivent pas se valider (ex: AGY et GEMINI)
    inp = {
        "actor_agent": "AGY",
        "ring": 2,
        "action": "validate_task",
        "target_agent": "GEMINI"
    }
    res = evaluate(inp)
    assert res["allow"] is False
    assert "same-lineage" in res["reason"] or "collusion-by-lineage" in res["reason"] or "OPA_DENY" in res["reason"]

def test_allow_different_lineage_validation():
    # Deux agents de lignées différentes peuvent se valider (ex: CLAUDE et GEMINI)
    inp = {
        "actor_agent": "CLAUDE",
        "ring": 1,
        "action": "validate_task",
        "target_agent": "GEMINI"
    }
    res = evaluate(inp)
    assert res["allow"] is True

def test_deny_task_result_same_agent():
    # task.result refuse si actor_agent == target_agent (créateur == worker)
    inp = {
        "actor_agent": "GEMINI",
        "ring": 2,
        "action": "task.result",
        "target_agent": "GEMINI"
    }
    res = evaluate(inp)
    assert res["allow"] is False
    assert "same" in res["reason"] or "OPA_DENY" in res["reason"]

def test_allow_task_result_different_agent():
    # task.result autorise si différent
    inp = {
        "actor_agent": "CLAUDE",
        "ring": 1,
        "action": "task.result",
        "target_agent": "GEMINI"
    }
    res = evaluate(inp)
    assert res["allow"] is True
