"""
forge_llama_worker_isolated.py - Wrapper Win32 Job Object pour llama-server.exe.

Calque de forge_embed_worker_isolated.py (memory roadmap_bge_m3_isolation) :
  A. Process llama-server.exe sous Job Object (process memory cap + KILL_ON_JOB_CLOSE)
  B. Pause via flag sandbox/llama_rebuild_pause (NtSuspend/Resume process)
  C. Forward de tous les args llama-server (apres `--`) sans interpretation
  D. Heartbeat sandbox/llama_worker_isolated.heartbeat pour supervisor :8765

But : meme lance standalone (sans NSSM/supervisor), llama-server ne peut PAS
deborder en RAM (cap process) et meurt si le wrapper meurt (KILL_ON_JOB_CLOSE).
Mitige scenario BSOD 0x119 incident 2026-05-24 (DirectML brain_worker) ou tout
OOM saturant l'UMA Radeon 780M.

Usage :
  LAFORGE_PYTHON tools/forge_llama_worker_isolated.py [--mem-gb 16] -- <llama-server args>

Exemple :
  LAFORGE_PYTHON tools/forge_llama_worker_isolated.py --mem-gb 16 -- ^
    -m C:/path/model.gguf --host 127.0.0.1 --port 8091 --api-key %FORGE_LLAMA_KEY%

Sortie : 0 = arret propre, 1 = crash llama-server, 2 = init impossible.
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
    format="%(asctime)s [llama_worker_isolated] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("llama_worker_isolated")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LLAMA_EXE = Path(
    os.environ.get("LAFORGE_LLAMA_EXE", __import__("os").path.expanduser(r"~\llama-vulkan\llama-server.exe"))
)
HEARTBEAT_PATH = ROOT / "sandbox" / "llama_worker_isolated.heartbeat"
DEFAULT_PAUSE_FLAG = ROOT / "sandbox" / "llama_rebuild_pause"

JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_ALL_ACCESS = 0x1F0FFF
CREATE_SUSPENDED = 0x00000004

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mem-gb",
        type=float,
        default=16.0,
        help="Cap memoire process (GB). Default 16 (sur 32 GB UMA).",
    )
    parser.add_argument("--pause-flag", type=Path, default=DEFAULT_PAUSE_FLAG)
    parser.add_argument("--tick-s", type=float, default=2.0)
    parser.add_argument(
        "--llama-exe",
        type=Path,
        default=DEFAULT_LLAMA_EXE,
        help="Chemin llama-server.exe (override env LAFORGE_LLAMA_EXE).",
    )
    parser.add_argument(
        "--require-api-key",
        action="store_true",
        help="Refuser de demarrer si --api-key absent des args forwardes.",
    )
    parser.add_argument(
        "llama_args",
        nargs=argparse.REMAINDER,
        help="Args forwardes a llama-server.exe (prefixer par --).",
    )
    args = parser.parse_args(argv)

    if not args.llama_exe.exists():
        log.error("llama-server binary missing: %s", args.llama_exe)
        return 2

    forwarded = list(args.llama_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if not forwarded:
        log.error("no llama-server args provided (use `-- <args>` after wrapper flags)")
        return 2

    if args.require_api_key and "--api-key" not in forwarded:
        log.error("--require-api-key set mais aucun --api-key dans les args forwardes")
        return 2

    mem_bytes = int(args.mem_gb * 1024 * 1024 * 1024)
    log.info("creating Job Object mem_cap=%.1f GB", args.mem_gb)
    job = create_job_with_mem_cap(mem_bytes)

    env = os.environ.copy()
    env.setdefault("LAFORGE_ROOT", str(ROOT))

    cmd = [str(args.llama_exe), *forwarded]
    redacted = list(cmd)
    for i, tok in enumerate(redacted):
        if tok in ("--api-key", "--api_key") and i + 1 < len(redacted):
            redacted[i + 1] = "<redacted>"
    log.info("spawning llama-server: %s", " ".join(redacted))
    proc = subprocess.Popen(
        cmd,
        env=env,
        creationflags=CREATE_SUSPENDED,
    )
    try:
        assign_to_job(job, proc.pid)
    except OSError as exc:
        log.error("failed to assign llama-server to job: %s", exc)
        proc.kill()
        kernel32.CloseHandle(job)
        return 2

    resume_process(proc.pid)
    log.info("llama-server pid=%d assigned to job, resumed", proc.pid)

    paused = False
    iter_count = 0

    def shutdown(_signum=None, _frame=None):
        log.info("shutdown requested; terminating job")
        kernel32.CloseHandle(job)  # KILL_ON_JOB_CLOSE -> tue llama-server
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            iter_count += 1

            should_pause = args.pause_flag.exists()
            if should_pause and not paused:
                if suspend_process(proc.pid):
                    paused = True
                    log.info("pause flag detected; llama-server suspended")
            elif not should_pause and paused:
                if resume_process(proc.pid):
                    paused = False
                    log.info("pause flag cleared; llama-server resumed")

            rc = proc.poll()
            if rc is not None:
                log.error("llama-server exited rc=%s", rc)
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
