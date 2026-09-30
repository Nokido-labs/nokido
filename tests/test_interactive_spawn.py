"""Tests for spawn_as_interactive_jobbed — user-session spawn via
WTSQueryUserToken. Requires :
  - Windows (skipped elsewhere)
  - A logged-in console user (WTSGetActiveConsoleSessionId != 0xFFFFFFFF)
  - Caller has SeTcbPrivilege (LocalSystem default ; user session lacks it
    → SandboxError expected — tests for the failure-mode signal too).

Tests bake the contract used by tools/forge_runas_launcher.py :
spawn returns dict with {ok, pid, sandbox_user, _job, _proc}, closing _job
kills the child via JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only (pywin32 + WTSQueryUserToken)",
                allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import forge_sandbox_exec as fse  # noqa: E402


def _has_se_tcb_privilege() -> bool:
    """Check caller has SeTcbPrivilege (LocalSystem service only)."""
    try:
        import ntsecuritycon
        import win32api
        import win32con
        import win32security
        tok = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY)
        privs = win32security.GetTokenInformation(
            tok, ntsecuritycon.TokenPrivileges)
        for luid, _attrs in privs:
            name = win32security.LookupPrivilegeName(None, luid)
            if name == "SeTcbPrivilege":
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def test_active_console_session_id_present():
    """Logged-in user session must be detectable (≠ 0xFFFFFFFF)."""
    import win32ts
    sid = win32ts.WTSGetActiveConsoleSessionId()
    assert sid != 0xFFFFFFFF, "no active console session — log in first"
    assert sid > 0, f"unexpected sid={sid}"


def test_repli_sans_setcb_est_borne_a_la_session():
    """Sans SeTcbPrivilege, le repli CreateProcess n'est tolere QUE depuis la
    session visee, et il doit se NOMMER.

    Contrat revise le 2026-09-10. L'ancienne version exigeait un SandboxError
    des que SeTcbPrivilege manquait ; un repli a ete ajoute depuis, legitime
    quand le superviseur tourne deja comme l'owner. Il reste destructeur depuis
    SYSTEM en session 0, ou il livrait un enfant en session 0 : le runner
    GitHub y a ecrit son `_work`, et le checkout suivant est mort en
    `detected dubious ownership`. Le garde est donc la SESSION, pas le
    privilege. Cf. tests/nr/test_repli_interactif_meme_session_nr.py.
    """
    if _has_se_tcb_privilege():
        pytest.skip("test only meaningful in user context (lacks SeTcbPrivilege)")
    import win32api
    import win32ts
    sid = win32ts.WTSGetActiveConsoleSessionId()
    courant = win32ts.ProcessIdToSessionId(os.getpid())
    if courant != sid:
        with pytest.raises(fse.SandboxError, match=r"REFUSE|SeTcbPrivilege"):
            fse.spawn_as_interactive_jobbed("cmd.exe /c echo nope")
        return
    spawned = fse.spawn_as_interactive_jobbed("cmd.exe /c exit 0")
    try:
        assert spawned["sandbox_user"] == f"current-user-fallback-sid{courant}", (
            "un repli anonyme est indiscernable d'un spawn correct")
    finally:
        for h in (spawned.get("_proc"), spawned.get("_job")):
            try:
                if h:
                    win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001
                pass


@pytest.mark.skipif(not _has_se_tcb_privilege(),
                    reason="needs LocalSystem (SeTcbPrivilege) — supervisor only")
def test_spawn_returns_jobbed_handles():
    """Happy path : spawn cmd.exe /c echo, get pid > 0, _job + _proc handles,
    child exits 0 within 5s."""
    import win32event
    import win32process
    spawned = fse.spawn_as_interactive_jobbed("cmd.exe /c exit 0")
    try:
        assert spawned["ok"] is True
        assert spawned["pid"] > 0
        assert spawned["sandbox_user"].startswith("interactive-sid")
        assert spawned["_job"] is not None
        assert spawned["_proc"] is not None
        rc = win32event.WaitForSingleObject(spawned["_proc"], 5000)
        assert rc == win32event.WAIT_OBJECT_0, f"child still running (rc={rc})"
        code = win32process.GetExitCodeProcess(spawned["_proc"])
        assert code == 0, f"exit code = {code}"
    finally:
        import win32api
        for h in (spawned.get("_proc"), spawned.get("_job")):
            try:
                if h:
                    win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001
                pass


@pytest.mark.skipif(not _has_se_tcb_privilege(),
                    reason="needs LocalSystem (SeTcbPrivilege) — supervisor only")
def test_job_kill_on_close_terminates_child():
    """Closing the _job handle MUST kill the child within 2s
    (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE contract)."""
    import win32api
    import win32event
    # Long-running child : timeout 30s.
    spawned = fse.spawn_as_interactive_jobbed("cmd.exe /c timeout /t 30 /nobreak")
    try:
        # Confirm alive : WaitForSingleObject 200ms should timeout.
        rc = win32event.WaitForSingleObject(spawned["_proc"], 200)
        assert rc == win32event.WAIT_TIMEOUT, "child died before kill test"
        # Close job → child must die.
        win32api.CloseHandle(spawned["_job"])
        spawned["_job"] = None
        rc = win32event.WaitForSingleObject(spawned["_proc"], 2000)
        assert rc == win32event.WAIT_OBJECT_0, \
            f"child survived job close (rc={rc})"
    finally:
        for h in (spawned.get("_proc"), spawned.get("_job")):
            try:
                if h:
                    win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001
                pass
