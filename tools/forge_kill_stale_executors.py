#!/usr/bin/env python
"""forge_kill_stale_executors.py — tue les instances python de forge_task_executor.py
(orphelines de restarts en rafale, injoignables par ensure_service).

FIX 23/07 : Get-CimInstance rend CommandLine=NULL pour les process d'un AUTRE compte.
On active SeDebugPrivilege (compte trusted/admin) + psutil pour LIRE les cmdlines
cross-compte. Ciblage strict par cmdline (jamais tout python.exe). trusted_script.

Args : --list (n'imprime que, ne tue pas) | <rien> (liste ET tue).
"""
from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/keeper : tue les executors python orphelins des restarts"  # organe declare le 2026-09-06 (audit de raccordement)
import json
import sys


def _enable_se_debug() -> bool:
    """Active SeDebugPrivilege pour lire/tuer les process d'autres comptes."""
    try:
        import ctypes
        from ctypes import wintypes
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD),
                        ("Privileges", LUID_AND_ATTRIBUTES * 1)]

        TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY = 0x20, 0x8
        SE_PRIVILEGE_ENABLED = 0x2
        hproc = k32.GetCurrentProcess()
        htok = wintypes.HANDLE()
        if not adv.OpenProcessToken(hproc, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(htok)):
            return False
        luid = LUID()
        if not adv.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            return False
        tp = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
        return bool(adv.AdjustTokenPrivileges(htok, False, ctypes.byref(tp), 0, None, None))
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    do_kill = "--list" not in sys.argv
    se = _enable_se_debug()
    import os as _os
    import psutil  # type: ignore
    me = _os.getpid()
    found, killed, errs = [], [], []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info["pid"] == me:
                continue
            cl = " ".join(p.info.get("cmdline") or [])
            if "forge_task_executor.py" not in cl:
                continue
            found.append({"pid": p.info["pid"], "cmd": cl[-120:]})
            if do_kill:
                try:
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except Exception:  # noqa: BLE001
                        p.kill()
                    killed.append(p.info["pid"])
                except Exception as e:  # noqa: BLE001
                    errs.append({"pid": p.info["pid"], "err": str(e)[:80]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    print(json.dumps({"se_debug": se, "found": found, "killed": killed, "errs": errs},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
