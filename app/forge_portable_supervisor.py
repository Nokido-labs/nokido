"""forge_portable_supervisor.py - Cross-OS supervisor Phase 2 reference impl.

Per Gemini Web + Cerebras + Mistral + GPT-4o consensus 2026-05-29 :
- custom asyncio + psutil (reject supervisord/circus/honcho)
- portable Job Object (Win) / cgroups (Linux) / rlimit (macOS)
- watchdog file-system hot-reload services.toml
- backoff exponential restart on crash
- RotatingFileHandler portable log rotation
- bootstrap auto-install sc.exe / systemd / launchd

DESIGN GOALS
============
Phase 2 = drop NSSM dependency. 1 system service per OS = entry point that
launches LaForge-Master supervisor. ALL workers spawned via asyncio Popen.
services.toml = single source of truth.

CURRENT STATUS
==============
Reference impl + roadmap. Production LaForge-Master = proxy_deno/core/supervisor.ts
(Deno/TypeScript). This module = blueprint for future Python rewrite or
secondary supervisor (e.g., AMI workers cluster).

USAGE
=====
    from forge_portable_supervisor import Supervisor
    sup = Supervisor("services.toml")
    asyncio.run(sup.main())

INSTALL SYSTEM SERVICE
======================
    python -m app.forge_portable_supervisor install
    -> Windows : sc create NokidoMaster binPath="..."
    -> Linux   : /etc/systemd/system/nokido.service + systemctl enable
    -> macOS   : /Library/LaunchDaemons/com.nokido.master.plist + launchctl
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import signal
import subprocess
import sys
import time
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import psutil

ROOT = Path(__file__).resolve().parent.parent
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"
LOG_DIR = ROOT / "logs" / "supervisor_py"
PID_FILE = ROOT / "sandbox" / "supervisor_py.pid"


# ── Portable resource isolation ───────────────────────────────────────────────


class PortableJobBox:
    """Wraps spawn'd process in OS-native resource isolation.

    Windows : Job Object (kill-on-job-close + mem cap)
    Linux   : cgroups v2 (cpu.max + memory.max)
    macOS   : rlimit (POSIX RSS cap)
    """

    def __init__(self, name: str, mem_mb: Optional[int] = None, cpu_pct: Optional[float] = None):
        self.name = name
        self.mem_mb = mem_mb
        self.cpu_pct = cpu_pct
        self._job_handle = None

    def apply(self, pid: int) -> bool:
        sysname = sys.platform
        try:
            if sysname == "win32":
                return self._apply_windows(pid)
            elif sysname == "linux":
                return self._apply_linux(pid)
            elif sysname == "darwin":
                return self._apply_macos(pid)
        except Exception as e:
            logging.warning(f"PortableJobBox.apply({pid}) failed: {e}")
        return False

    def _apply_windows(self, pid: int) -> bool:
        try:
            import win32job  # type: ignore

            job = win32job.CreateJobObject(None, f"Nokido_{self.name}_{pid}")
            info = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            if self.mem_mb:
                info["BasicLimitInformation"]["LimitFlags"] |= (
                    win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
                )
                info["ProcessMemoryLimit"] = self.mem_mb * 1024 * 1024
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, info
            )
            win32job.AssignProcessToJobObject(job, pid)
            self._job_handle = job
            return True
        except ImportError:
            logging.warning("pywin32 not installed -- skip Job Object")
            return False

    def _apply_linux(self, pid: int) -> bool:
        # cgroups v2 via /sys/fs/cgroup direct fs ops (no cgroupspy dep).
        cgroup_path = Path(f"/sys/fs/cgroup/nokido/{self.name}_{pid}")
        try:
            cgroup_path.mkdir(parents=True, exist_ok=True)
            if self.mem_mb:
                (cgroup_path / "memory.max").write_text(str(self.mem_mb * 1024 * 1024))
            if self.cpu_pct:
                # cpu.max = "quota period" (us). 100% of 1 core = "100000 100000"
                quota = int(self.cpu_pct * 1000)
                (cgroup_path / "cpu.max").write_text(f"{quota} 100000")
            (cgroup_path / "cgroup.procs").write_text(str(pid))
            return True
        except PermissionError:
            logging.warning("cgroups need root -- skip")
            return False

    def _apply_macos(self, pid: int) -> bool:
        # macOS has no cgroups. Limited rlimit applies to current process only,
        # not arbitrary PIDs. Best-effort : nothing for now.
        # TODO : explore tasks_set_resource_limits via Mach API if needed.
        return False


# ── Service definition ────────────────────────────────────────────────────────


class ServiceDef:
    def __init__(self, name: str, cmd: str, args: list[str], cwd: str = ".",
                 env: dict | None = None, mem_mb: Optional[int] = None,
                 cpu_pct: Optional[float] = None, max_restarts: int = 10,
                 restart_window_s: int = 3600):
        self.name = name
        self.cmd = cmd
        self.args = args
        self.cwd = cwd
        self.env = env or {}
        self.mem_mb = mem_mb
        self.cpu_pct = cpu_pct
        self.max_restarts = max_restarts
        self.restart_window_s = restart_window_s

    @classmethod
    def from_toml_entry(cls, entry: dict) -> "ServiceDef":
        return cls(
            name=entry["name"],
            cmd=entry.get("cmd", ""),
            args=entry.get("args", []),
            cwd=entry.get("cwd", "."),
            env=entry.get("env", {}),
            mem_mb=entry.get("mem_mb"),
            cpu_pct=entry.get("cpu_pct"),
        )


# ── Worker process wrapper ────────────────────────────────────────────────────


class Worker:
    def __init__(self, sdef: ServiceDef):
        self.sdef = sdef
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.start_history: list[float] = []
        self.backoff_idx = 0
        self.log_handler: Optional[RotatingFileHandler] = None
        self.job_box = PortableJobBox(sdef.name, sdef.mem_mb, sdef.cpu_pct)

    async def spawn(self):
        cmd_list = [self.sdef.cmd] + list(self.sdef.args)
        env = {**os.environ, **self.sdef.env}
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{self.sdef.name}.log"

        self.log_handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        logger = logging.getLogger(f"worker.{self.sdef.name}")
        logger.addHandler(self.log_handler)

        self.proc = await asyncio.create_subprocess_exec(
            *cmd_list,
            cwd=self.sdef.cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if self.proc.pid:
            self.job_box.apply(self.proc.pid)
        logger.info(f"spawned pid={self.proc.pid}")
        self.start_history.append(time.time())

        # Drain stdout into log file
        asyncio.create_task(self._drain(logger))

    async def _drain(self, logger):
        if not self.proc or not self.proc.stdout:
            return
        async for line in self.proc.stdout:
            try:
                logger.info(line.decode("utf-8", errors="replace").rstrip())
            except Exception:
                pass

    def is_alive(self) -> bool:
        if not self.proc:
            return False
        if self.proc.returncode is not None:
            return False
        try:
            return psutil.Process(self.proc.pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    async def stop(self, timeout_s: float = 10):
        if not self.proc or self.proc.returncode is not None:
            return
        try:
            self.proc.terminate()
            await asyncio.wait_for(self.proc.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            self.proc.kill()
            await self.proc.wait()

    def in_quarantine(self) -> bool:
        cutoff = time.time() - self.sdef.restart_window_s
        recent = [t for t in self.start_history if t >= cutoff]
        return len(recent) > self.sdef.max_restarts

    def backoff_seconds(self) -> float:
        # Exponential backoff : 1, 2, 4, 8, 16, ... cap 300s
        b = min(2 ** self.backoff_idx, 300)
        self.backoff_idx += 1
        return b


# ── Supervisor ────────────────────────────────────────────────────────────────


class Supervisor:
    def __init__(self, toml_path: Path = SERVICES_TOML):
        self.toml_path = toml_path
        self.workers: dict[str, Worker] = {}
        self._stop_requested = False

    def _load_services(self) -> list[ServiceDef]:
        data = tomllib.loads(self.toml_path.read_text(encoding="utf-8"))
        return [ServiceDef.from_toml_entry(s) for s in data.get("service", [])]

    async def hot_reload(self):
        new_defs = self._load_services()
        new_names = {d.name for d in new_defs}
        current_names = set(self.workers.keys())

        for name in current_names - new_names:
            logging.info(f"hot_reload: stop removed worker {name}")
            await self.workers[name].stop()
            del self.workers[name]

        for sdef in new_defs:
            if sdef.name in self.workers:
                self.workers[sdef.name].sdef = sdef
            else:
                w = Worker(sdef)
                self.workers[sdef.name] = w
                await w.spawn()

    async def watchdog(self):
        while not self._stop_requested:
            for name, w in list(self.workers.items()):
                if not w.is_alive():
                    if w.in_quarantine():
                        logging.warning(f"{name}: QUARANTINE -- too many restarts")
                        await asyncio.sleep(60)
                        continue
                    backoff = w.backoff_seconds()
                    logging.warning(f"{name}: crash detected, restart in {backoff}s")
                    await asyncio.sleep(backoff)
                    await w.spawn()
            await asyncio.sleep(5)

    async def main(self):
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda *_: setattr(self, "_stop_requested", True))
            except Exception:
                pass

        for sdef in self._load_services():
            w = Worker(sdef)
            self.workers[sdef.name] = w
            await w.spawn()

        await self.watchdog()

        for w in self.workers.values():
            await w.stop()


# ── Bootstrap auto-install ────────────────────────────────────────────────────


def install_service():
    """Install LaForge-Master as system service. Requires admin/root."""
    osys = sys.platform
    exec_path = sys.executable
    script_path = Path(__file__).resolve()

    if osys == "win32":
        cmd = [
            "sc", "create", "NokidoMaster",
            f"binPath= \"{exec_path}\" \"{script_path}\"",
            "start= auto",
            "DisplayName= Nokido Master Supervisor",
        ]
        subprocess.run(cmd, check=True)
        print("[install] Windows : sc create NokidoMaster done")
    elif osys == "linux":
        unit_path = Path("/etc/systemd/system/laforge-master.service")
        user = os.environ.get("USER", "root")
        unit_content = f"""[Unit]
Description=Nokido Master Supervisor
After=network.target

[Service]
Type=simple
ExecStart={exec_path} {script_path}
Restart=always
RestartSec=5
User={user}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
        unit_path.write_text(unit_content)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "laforge-master"], check=True)
        print(f"[install] Linux : {unit_path} + systemctl enable done")
    elif osys == "darwin":
        plist_path = Path("/Library/LaunchDaemons/com.nokido.master.plist")
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nokido.master</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exec_path}</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/laforge-master.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/laforge-master.err</string>
</dict>
</plist>
"""
        plist_path.write_text(plist_content)
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        print(f"[install] macOS : {plist_path} + launchctl load done")
    else:
        print(f"unsupported OS: {osys}", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "install", "status"], default="run", nargs="?")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        handlers=[
            RotatingFileHandler(LOG_DIR / "supervisor_py.log",
                                maxBytes=20 * 1024 * 1024, backupCount=5),
            logging.StreamHandler(),
        ],
    )

    if args.cmd == "install":
        install_service()
    elif args.cmd == "status":
        if PID_FILE.exists():
            pid = int(PID_FILE.read_text())
            try:
                p = psutil.Process(pid)
                print(f"running pid={pid} status={p.status()} mem_mb={p.memory_info().rss/(1024*1024):.1f}")
            except psutil.NoSuchProcess:
                print(f"stale PID file (pid {pid} dead)")
        else:
            print("not running")
    else:
        sup = Supervisor()
        asyncio.run(sup.main())


if __name__ == "__main__":
    main()
