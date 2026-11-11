# -*- coding: utf-8 -*-
"""NR -- apres `task action=assign`, le gate rappelle d'armer le Monitor gratuit `--task`.

Owner 2026-11-08 : « il n'y a pas de mecanisme gratuit en token pour monitorer son retour ? ».
Il existe : `tools/forge_job_watch_cli.py --task <task_id>` dans un Monitor natif ne coute
aucun token jusqu'au rendu ou au gel. Trois taches AGY assignees le 08/11 sans lui, suivies a
la main par `task status`. Contrat : verdict_forme sur un assign -> rappel non bloquant qui nomme
`--task` ; un `task status` ne tire rien.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _gate():
    spec = importlib.util.spec_from_file_location("hook_capability_gate_nr_assign", ROOT / "tools" / "hook_capability_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_assign_rappelle_le_monitor_task():
    touche, msg = _gate().verdict_forme("mcp__nokido-oauth__task", {"action": "assign", "agent": "ANTIGRAVITY"})
    assert touche and "--task" in msg and "forge_job_watch_cli" in msg


def test_status_ne_tire_pas():
    touche, _ = _gate().verdict_forme("mcp__nokido-oauth__task", {"action": "status", "task_id": "x"})
    assert not touche
