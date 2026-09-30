"""Tests du keeper SearXNG — logique _ensure_running + _write_settings.

Couvre les fixes 2026-05-29 :
  - état docker "exited" (jamais "stopped") géré → start, pas run-conflict
  - start KO → rm -f + run frais
  - running mais json KO (container nu) → recreate avec settings
  - run inclut le -v settings.yml ; settings.yml généré + idempotent
Tout mocké (pas de docker réel).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import forge_searxng_keeper as k  # type: ignore[import-not-found]


class FakeProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


@pytest.fixture
def sandbox_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(k, "SETTINGS_DIR", tmp_path / "searxng")
    monkeypatch.setattr(k, "SETTINGS_FILE", tmp_path / "searxng" / "settings.yml")
    return tmp_path / "searxng" / "settings.yml"


def install_docker(monkeypatch, calls, inspect_status="absent", start_rc=0):
    def fake(*args, capture=True, timeout=15):
        calls.append(args)
        verb = args[0]
        if verb == "inspect":
            if inspect_status == "absent":
                return FakeProc(rc=1)
            return FakeProc(rc=0, out=inspect_status)
        if verb == "start":
            return FakeProc(rc=start_rc, err="boom" if start_rc else "")
        return FakeProc(rc=0)

    monkeypatch.setattr(k, "_docker", fake)


def _verbs(calls):
    return [c[0] for c in calls]


def _run_call(calls):
    return next((c for c in calls if c[0] == "run"), None)


def test_exited_starts_no_run(monkeypatch, sandbox_settings):
    calls = []
    install_docker(monkeypatch, calls, inspect_status="exited", start_rc=0)
    k._ensure_running()
    assert "start" in _verbs(calls)
    assert "run" not in _verbs(calls)  # le bug d'origine faisait un run → Conflict


def test_exited_start_fails_recreates(monkeypatch, sandbox_settings):
    calls = []
    install_docker(monkeypatch, calls, inspect_status="exited", start_rc=1)
    k._ensure_running()
    assert "start" in _verbs(calls)
    assert ("rm", "-f", k.CONTAINER) in calls
    run = _run_call(calls)
    assert run is not None and "-v" in run


def test_running_json_ok_leaves(monkeypatch, sandbox_settings):
    calls = []
    install_docker(monkeypatch, calls, inspect_status="running")
    monkeypatch.setattr(k, "_probe_http", lambda: (True, ""))
    k._ensure_running()
    assert "run" not in _verbs(calls)
    assert "start" not in _verbs(calls)
    assert all(c[0] != "rm" for c in calls)


def test_running_json_ko_recreates(monkeypatch, sandbox_settings):
    calls = []
    install_docker(monkeypatch, calls, inspect_status="running")
    monkeypatch.setattr(k, "_probe_http", lambda: (False, "403"))
    k._ensure_running()
    assert ("rm", "-f", k.CONTAINER) in calls
    run = _run_call(calls)
    assert run is not None and "-v" in run


def test_absent_runs_with_settings_mount(monkeypatch, sandbox_settings):
    calls = []
    install_docker(monkeypatch, calls, inspect_status="absent")
    k._ensure_running()
    run = _run_call(calls)
    assert run is not None
    assert "-v" in run
    assert any("/etc/searxng/settings.yml" in str(x) for x in run)
    assert sandbox_settings.exists()  # _write_settings a écrit le fichier avant le run


def test_write_settings_content_and_idempotent(monkeypatch, sandbox_settings):
    k._write_settings()
    assert sandbox_settings.exists()
    txt = sandbox_settings.read_text(encoding="utf-8")
    assert "limiter: false" in txt
    assert "- json" in txt
    assert "secret_key:" in txt
    first = txt
    k._write_settings()  # 2e appel : ne doit pas régénérer le secret
    assert sandbox_settings.read_text(encoding="utf-8") == first
