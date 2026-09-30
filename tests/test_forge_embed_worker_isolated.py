"""Smoke tests for forge_embed_worker_isolated — verifie Job Object + cap + flag."""
from __future__ import annotations

import ctypes
import importlib
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus notepad.exe / python (l.52)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(scope="module")
def mod():
    if sys.platform != "win32":
        pytest.skip("Job Object = Windows only")
    return importlib.import_module("forge_embed_worker_isolated")


def test_constants_present(mod):
    assert mod.JOB_OBJECT_LIMIT_PROCESS_MEMORY == 0x00000100
    assert mod.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x00002000
    assert mod.JobObjectExtendedLimitInformation == 9


def test_extended_limit_struct_layout(mod):
    s = mod.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    s.ProcessMemoryLimit = 5 * 1024 * 1024 * 1024
    assert s.ProcessMemoryLimit == 5 * 1024 * 1024 * 1024
    s.BasicLimitInformation.LimitFlags = (
        mod.JOB_OBJECT_LIMIT_PROCESS_MEMORY | mod.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    assert s.BasicLimitInformation.LimitFlags == 0x2100


def test_create_job_with_mem_cap_returns_handle(mod):
    job = mod.create_job_with_mem_cap(1 * 1024 * 1024 * 1024)
    try:
        assert job != 0 and job is not None
    finally:
        mod.kernel32.CloseHandle(job)


def test_create_job_kills_on_close_via_notepad(mod, tmp_path):
    """Spawn notepad sous Job, ferme handle Job, verifie notepad mort."""
    import subprocess
    import time

    job = mod.create_job_with_mem_cap(512 * 1024 * 1024)
    proc = subprocess.Popen(
        ["notepad.exe"],
        creationflags=mod.CREATE_SUSPENDED,
    )
    try:
        mod.assign_to_job(job, proc.pid)
        mod.resume_process(proc.pid)
        time.sleep(0.3)
        assert proc.poll() is None, "notepad should be alive"
    finally:
        mod.kernel32.CloseHandle(job)  # KILL_ON_JOB_CLOSE
    # Laisser temps Windows propager
    for _ in range(20):
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    assert proc.poll() is not None, "Job close should kill child"


def test_suspend_resume_cycle(mod):
    """NtSuspendProcess + NtResumeProcess sur process courant ne crash pas."""
    # Skip self-suspend (deadlock). Spawn python sleep subprocess (cmd `timeout`
    # exit immediate quand stdin redirige par Popen).
    import subprocess
    import time

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        assert proc.poll() is None, "child should still be alive"
        assert mod.suspend_process(proc.pid)
        assert mod.resume_process(proc.pid)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_pause_flag_default_path(mod):
    expected = ROOT / "sandbox" / "embed_rebuild_pause"
    assert mod.DEFAULT_PAUSE_FLAG == expected
