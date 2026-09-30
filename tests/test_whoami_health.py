"""Tests des helpers purs du cross-ref santé whoami (forge_mcp_registry).

Couvre whoami_degraded_services + whoami_health_actions (extraits 2026-05-29
pour rendre le cross-ref /supervisor/status testable). RCA : whoami était
aveugle à une infra cassée → faux "rien à reprendre".
"""
from __future__ import annotations

# conftest.py met LaForge/app sur sys.path.
from forge_mcp_registry import whoami_degraded_services, whoami_health_actions  # type: ignore[import-not-found]


def test_healthy_states_excluded():
    svc = {
        "A": {"status": "running"},
        "B": {"status": "sleeping"},
        "C": {"status": "disabled"},
        "D": {"status": "starting"},
    }
    assert whoami_degraded_services(svc) == []


def test_degraded_detected():
    svc = {"X": {"status": "stopped", "restarts": 2}, "Y": {"status": "running"}}
    assert whoami_degraded_services(svc) == [{"service": "X", "status": "stopped", "restarts": 2}]


def test_missing_status_is_unknown_and_degraded():
    d = whoami_degraded_services({"Z": {}})
    assert d == [{"service": "Z", "status": "?", "restarts": 0}]


def test_empty_and_none_safe():
    assert whoami_degraded_services({}) == []
    assert whoami_degraded_services(None) == []


def test_health_actions_only_tried_or_hard():
    deg = [
        {"service": "IdleClean", "status": "stopped", "restarts": 0},  # essential=false idle → ignoré
        {"service": "Tried", "status": "stopped", "restarts": 2},  # a essayé+échoué → action
        {"service": "Crashed", "status": "crashed", "restarts": 0},  # état dur → action
    ]
    acts = whoami_health_actions(deg)
    whys = " ".join(a["why"] for a in acts)
    assert "Tried" in whys and "Crashed" in whys and "IdleClean" not in whys


def test_health_actions_cmd_shape_and_limit():
    deg = [{"service": f"S{i}", "status": "crashed", "restarts": 0} for i in range(6)]
    acts = whoami_health_actions(deg)
    assert len(acts) == 4  # cap
    assert acts[0]["cmd"] == (
        'run action=trusted_script path=tools/forge_supervisor_ctl.py script_args="restart S0"'
    )
