# -*- coding: utf-8 -*-
"""NR — Le modèle dans after_model_hook dépend de l'appelant et non d'un GEMINI_MODEL global figé.

Décision owner du 15/10/2026 :
- L'appelant CLI (Gemini CLI / Antigravity) utilise un modèle spécifique à sa session ou tâche.
- after_model_hook doit comptabiliser les quotas selon le modèle réel de l'appelant (CLI/config/arg).
- Il ne doit pas dépendre d'un GEMINI_MODEL global figé qui fausserait la répartition des buckets.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import after_model_hook as H


def test_resolve_caller_model_priorite_argument_cli(monkeypatch):
    """Un argument CLI passé au hook a priorité absolue."""
    monkeypatch.setattr(sys, "argv", ["after_model_hook.py", "--model", "gemini-3.1-pro-preview"])
    monkeypatch.setenv("GEMINI_CLI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

    m = H.resolve_caller_model()
    assert m == "gemini-3.1-pro-preview"


def test_resolve_caller_model_priorite_env_appelant(monkeypatch):
    """En l'absence d'arg CLI, GEMINI_CLI_MODEL / AGY_MODEL de l'appelant prime sur GEMINI_MODEL."""
    monkeypatch.setattr(sys, "argv", ["after_model_hook.py"])
    monkeypatch.setenv("GEMINI_CLI_MODEL", "gemini-3.1-flash-lite-preview")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")

    m = H.resolve_caller_model()
    assert m == "gemini-3.1-flash-lite-preview"


def test_track_quota_bucket_correct(tmp_path):
    """track_quota incrémente le bucket correspondant au modèle de l'appelant."""
    state_file = tmp_path / "quota_state.json"

    # Test avec modèle preview_pro
    st1 = H.track_quota("gemini-3.1-pro-preview", 100, 200, state_file=state_file)
    assert st1.get("tokens_preview_pro") == 300
    assert st1.get("last_model") == "gemini-3.1-pro-preview"

    # Test avec modèle flash-lite
    st2 = H.track_quota("gemini-2.5-flash-lite", 50, 50, state_file=state_file)
    assert st2.get("tokens_flash_lite") == 100
    assert st2.get("tokens_preview_pro") == 300  # inchangé
    assert st2.get("last_model") == "gemini-2.5-flash-lite"
