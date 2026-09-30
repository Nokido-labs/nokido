# -*- coding: utf-8 -*-
"""
test_forge_alignment_trace_introspection.py — Tests unitaires pour emit_introspection.
"""
from __future__ import annotations

import time
from tools.forge_alignment_trace import emit, emit_introspection, recent

def test_emit_backward_compatibility():
    # L'ancien emit doit continuer à fonctionner et à insérer des lignes
    actor = "TEST_LEGACY"
    invariant = "test_inv"
    verdict = "allow"
    target = "test_target"
    reason = "test_reason"
    
    ok = emit(actor, invariant, verdict, target, reason)
    assert ok is True
    
    events = recent(5)
    assert len(events) > 0
    # Retrouver l'événement inséré
    found = False
    for ev in events:
        if ev["actor"] == actor and ev["invariant"] == invariant:
            found = True
            assert ev["meta"] is None  # L'ancien emit n'a pas de meta
            break
    assert found is True

def test_emit_introspection_writes_meta_and_reads():
    actor = "TEST_INTROSPECT"
    action = "test_write"
    target_module = "app/test_module.py"
    ring = 2
    execution_tier = "gvisor"
    is_self_judging = False
    tokens = {"prompt": 100, "completion": 50, "total": 150}
    cost_usd = 0.0045
    
    ok = emit_introspection(
        actor=actor,
        action=action,
        target_module=target_module,
        ring=ring,
        execution_tier=execution_tier,
        is_self_judging=is_self_judging,
        tokens=tokens,
        cost_usd=cost_usd,
        reason="testing rich metadata insertion"
    )
    assert ok is True
    
    events = recent(10)
    assert len(events) > 0
    
    found = False
    for ev in events:
        if ev["actor"] == actor and ev["invariant"] == "introspection":
            found = True
            assert ev["verdict"] == action
            assert ev["target"] == target_module
            # Vérifier la colonne meta enrichie
            meta = ev["meta"]
            assert meta is not None
            assert meta["ring"] == ring
            assert meta["execution_tier"] == execution_tier
            assert meta["is_self_judging"] == is_self_judging
            assert meta["tokens"] == tokens
            assert meta["cost_usd"] == cost_usd
            break
    assert found is True
