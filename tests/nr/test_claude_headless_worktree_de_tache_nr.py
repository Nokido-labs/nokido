# -*- coding: utf-8 -*-
"""NR -- defaut 2 : claude headless invoque dans le worktree reel de la tache.

Mesure job_bdab9595 : CLAUDE_HEADLESS doit recevoir son worktree de tache comme cwd reel,
transmis a CliHarness/process_job.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as T  # noqa: E402
from nokido_agent.app import forge_cli_harness as H  # noqa: E402


def test_job_claude_porte_cwd_du_worktree():
    wt = Path("%NOKIDO_ROOT%_worktrees/taches/claude_headless_bdab95958a8c")
    job = T._job_claude("job_bdab9595", "prompt consigne", wt, "M")
    assert job["cwd"] == str(wt)
    assert job["agent"] == "claude_api"
    assert "--mcp-config" in job["args"]
    idx = job["args"].index("--mcp-config")
    assert str(wt) in job["args"][idx + 1]


def test_harness_for_utilise_cwd_transmis(monkeypatch):
    monkeypatch.setattr(H, "_verifier_cle_api_obligatoire", lambda *a, **k: None)
    wt = r"%NOKIDO_ROOT%_worktrees\taches\claude_headless_bdab95958a8c"

    # Vérifie que harness_for passe le cwd au CliHarness et son backend _PipeBackend
    h = H.harness_for("claude_api", args=["-p", "--bare"], cwd=wt)
    assert h._b.cwd == wt
