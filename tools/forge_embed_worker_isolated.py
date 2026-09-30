"""
forge_embed_worker_isolated.py — Wrapper Win32 Job Object pour brain_worker BGE-M3.

Phases roadmap_bge_m3_isolation livrees :
  A. Process separe sous Job Object (memory cap + KILL_ON_JOB_CLOSE)
  B. TDR-aware pause via flag sandbox/embed_rebuild_pause (NtSuspend/Resume process)
  C. ZMQ :5557 inchange (le worker Rust expose le meme socket)
  D. Heartbeat sandbox/embed_worker_isolated.heartbeat pour watchdog supervisor

Usage :
  LAFORGE_PYTHON tools/forge_embed_worker_isolated.py [--mem-gb 5] [--pause-flag PATH]

Sortie : 0 = arret propre, 1 = crash worker, 2 = init impossible.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [embed_worker_isolated] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("embed_worker_isolated")

ROOT = Path(__file__).resolve().parent.parent
WORKER_EXE = (
    ROOT / "go_services" / "forge_brain_worker" / "target" / "release" / "forge_brain_worker.exe"
)
WORKER_CWD = ROOT / "go_services" / "forge_brain_worker"
HEARTBEAT_PATH = ROOT / "sandbox" / "embed_worker_isolated.heartbeat"
DEFAULT_PAUSE_FLAG = ROOT / "sandbox" / "embed_rebuild_pause"

# --- Win32 constants ---
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JobObjectExtendedLimitInformation = 9
PROCESS_ALL_ACCESS = 0x1F0FFF
CREATE_SUSPENDED = 0x00000004
INFINITE = 0xFFFFFFFF

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_job_with_mem_cap(mem_bytes: int) -> wt.HANDLE:
    """Cree un Job Object Win32 avec cap memoire process + KILL_ON_JOB_CLOSE."""
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    info.ProcessMemoryLimit = mem_bytes
    ok = kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        kernel32.CloseHandle(job)
        raise OSError(f"SetInformationJobObject failed: {ctypes.get_last_error()}")
    return job


def assign_to_job(job: wt.HANDLE, pid: int) -> None:
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        raise OSError(f"OpenProcess({pid}) failed: {ctypes.get_last_error()}")
    try:
        ok = kernel32.AssignProcessToJobObject(job, h)
        if not ok:
            raise OSError(f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")
    finally:
        kernel32.CloseHandle(h)


def suspend_process(pid: int) -> bool:
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        return False
    try:
        return ntdll.NtSuspendProcess(h) == 0
    finally:
        kernel32.CloseHandle(h)


def resume_process(pid: int) -> bool:
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        return False
    try:
        return ntdll.NtResumeProcess(h) == 0
    finally:
        kernel32.CloseHandle(h)


def write_heartbeat(state: dict) -> None:
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        log.warning("heartbeat write failed: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mem-gb", type=float, default=5.0, help="Cap memoire process (GB)")
    parser.add_argument("--pause-flag", type=Path, default=DEFAULT_PAUSE_FLAG)
    parser.add_argument("--tick-s", type=float, default=2.0)
    args = parser.parse_args()

    if not WORKER_EXE.exists():
        log.error("worker binary missing: %s", WORKER_EXE)
        return 2

    mem_bytes = int(args.mem_gb * 1024 * 1024 * 1024)
    log.info("creating Job Object mem_cap=%.1f GB", args.mem_gb)
    job = create_job_with_mem_cap(mem_bytes)

    env = os.environ.copy()
    env.setdefault("LAFORGE_ROOT", str(ROOT))
    env.setdefault("RUST_LOG", "info")

    log.info("spawning worker: %s", WORKER_EXE)
    proc = subprocess.Popen(
        [str(WORKER_EXE)],
        cwd=str(WORKER_CWD),
        env=env,
        creationflags=CREATE_SUSPENDED,
    )
    try:
        assign_to_job(job, proc.pid)
    except OSError as exc:
        log.error("failed to assign worker to job: %s", exc)
        proc.kill()
        kernel32.CloseHandle(job)
        return 2

    # Reprend le thread principal (CREATE_SUSPENDED a fige le main thread)
    # subprocess.Popen sur Win expose _handle / pid mais pas le thread handle.
    # On utilise NtResumeProcess qui resume tous les threads suspendus.
    resume_process(proc.pid)
    log.info("worker pid=%d assigned to job, resumed", proc.pid)

    paused = False
    iter_count = 0

    def shutdown(_signum=None, _frame=None):
        log.info("shutdown requested; terminating job")
        kernel32.CloseHandle(job)  # KILL_ON_JOB_CLOSE -> tue worker
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            iter_count += 1

            # Phase B : TDR-aware pause
            should_pause = args.pause_flag.exists()
            if should_pause and not paused:
                if suspend_process(proc.pid):
                    paused = True
                    log.info("TDR pause flag detected; worker suspended")
            elif not should_pause and paused:
                if resume_process(proc.pid):
                    paused = False
                    log.info("TDR pause flag cleared; worker resumed")

            # Verifie liveness worker
            rc = proc.poll()
            if rc is not None:
                log.error("worker exited rc=%s", rc)
                kernel32.CloseHandle(job)
                return 1 if rc != 0 else 0

            write_heartbeat(
                {
                    "iter": iter_count,
                    "pid": proc.pid,
                    "paused": paused,
                    "mem_cap_gb": args.mem_gb,
                    "ts": time.time(),
                }
            )
            time.sleep(args.tick_s)
    except KeyboardInterrupt:
        shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
