"""
forge_docker_monitor — Autonomous Docker Desktop watchdog.

__FORGE_COLOR__ = "#3b82f6"  (blue, system layer / SN vegetatif)

Anatomy : SN vegetatif sympathique (alerte) + parasympathique (boot/heal).
          Sister module to `forge_inspector` (bulbe rachidien) but specialised
          on the Docker Desktop process + dockerd socket + WSL2 backend.

Anti-duplication audit (2026-05-02)
-----------------------------------
Modules checked before creation :

| Module                              | Verdict                           |
|-------------------------------------|-----------------------------------|
| `tools/forge_docker_bridge.py`      | Docker SDK exec inside the        |
|                                     | exegol-nokido container.         |
|                                     | Cannot help when dockerd itself   |
|                                     | is dead (it imports docker-py).   |
|                                     | DIFFERENT CONCERN.                |
| `app/forge_resource_manager.py`     | Docstring promises                |
|                                     | docker_status/docker_pause_all/   |
|                                     | request_resources but body only   |
|                                     | has a basic is_docker_running()   |
|                                     | stub. Does NOT cover process      |
|                                     | restart, WSL2 health, container   |
|                                     | restart loops.                    |
| `app/forge_inspector.py`            | Generic autonomous monitor — no   |
|                                     | docker-specific logic.            |
| `app/forge_idle_watchdog.py`        | Idle detection only. No docker.   |
| `app/forge_ping_monitor.py`         | Generic ping. No docker.          |
| `app/forge_provider_watcher.py`     | LLM providers (Ollama / llama.cpp |
|                                     | / LM Studio). No docker.          |
| `tools/forge_services_launcher.py`  | Launches Nokido services. Does   |
|                                     | not orchestrate Docker Desktop.   |

Decision : new module justified. Pure stdlib (subprocess + json + urllib +
socket + time). NO docker-py import — useless if dockerd is dead anyway.
We talk to Docker Desktop via the `docker` CLI and to Windows via
`powershell` / `wsl.exe`.

Public API
----------
- `docker_state()`      : non-blocking snapshot of all signals.
- `health()`            : Hub /api/swarm/health-friendly dict.
- `auto_heal(dry_run)`  : decide + (optionally) execute heal scenarios.
- `cut_docker(reason)`  : graceful stop Docker Desktop (RAM pressure).
- `relaunch_docker(t)`  : restart Docker Desktop and wait for socket.

Decision tree for auto_heal
---------------------------
1. should_throttle() == True
   → SKIP heavy ops (relaunch / WSL shutdown). Only collect state.

2. Docker process alive AND socket responsive
   → status: ok. No action.

3. Docker process alive BUT socket dead (>5s `docker info` timeout)
   → action: relaunch (kill + restart).

4. Docker process dead AND user expects it (file watchdog or RAM ok)
   → action: relaunch.

5. WSL2 distro `docker-desktop` missing from `wsl -l --running`
   → action: `wsl --shutdown` then relaunch Docker (only if not throttled).

6. Container restart loop : same name restarted >3 times in 60s
   → action: REPORT only. Never auto-kill — could be intentional rolling
     restart of a user workload. Logs alert + sets degraded=True.

Resource gate
-------------
Imports `should_throttle` from `forge_resource_manager`. If RAM/CPU/GPU
above threshold, every heavy code path (relaunch, wsl --shutdown) is
skipped and reported as `skipped_throttle`.

Hub integration
---------------
`tools/nokido_hub.py` can plug `health()` directly into
`/api/swarm/health` :

    from forge_docker_monitor import health as docker_health
    payload["docker"] = docker_health()

CLI
---
    python forge_docker_monitor.py state
    python forge_docker_monitor.py health
    python forge_docker_monitor.py heal           # dry-run
    python forge_docker_monitor.py heal --apply
    python forge_docker_monitor.py cut "free RAM for bench"
    python forge_docker_monitor.py relaunch
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

log = logging.getLogger("Nokido.docker_monitor")


def _audit(action: str, reason: str = "", **extra) -> None:
    """Trace vers le journal d'audit Docker partage. Best-effort, jamais fatal.

    cut_docker() produit exactement la signature observee le 2026-07-22 (--quit
    gracieux, exit status 15, process disparus, vmmem vivant). Sans trace, on ne
    peut pas distinguer cet appel d'une extinction decidee par Docker Desktop.
    """
    try:
        from nokido_agent.app.forge_docker_audit import record as _record

        _record(action, reason=reason, **extra)
    except Exception:  # noqa: BLE001 - le journal ne doit jamais casser l'appelant
        pass

# ────────────────────────────────────────────────────────────────────────────
# Docker Desktop install path detection
# ────────────────────────────────────────────────────────────────────────────
# Order :
#   1. env var FORGE_DOCKER_DESKTOP_EXE (override for tests / non-default install)
#   2. %ProgramFiles%\Docker\Docker\Docker Desktop.exe
#   3. %ProgramFiles(x86)%\Docker\Docker\Docker Desktop.exe (rare 32-bit Windows)
#   4. %LocalAppData%\Docker\Docker\Docker Desktop.exe (per-user install)


def _detect_docker_desktop_exe() -> str | None:
    """Return absolute path to Docker Desktop.exe or None if not found."""
    override = os.environ.get("FORGE_DOCKER_DESKTOP_EXE")
    if override and Path(override).is_file():
        return override

    candidates: list[str] = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LocalAppData", "")
    candidates.append(str(Path(pf) / "Docker" / "Docker" / "Docker Desktop.exe"))
    candidates.append(str(Path(pf86) / "Docker" / "Docker" / "Docker Desktop.exe"))
    if lad:
        candidates.append(str(Path(lad) / "Docker" / "Docker" / "Docker Desktop.exe"))

    for c in candidates:
        if Path(c).is_file():
            return c
    return None


DOCKER_DESKTOP_EXE = _detect_docker_desktop_exe()
DOCKER_PROCESS_NAMES = (
    "Docker Desktop",  # main UI / backend
    "com.docker.backend",
    "com.docker.service",
    "vpnkit",
    "wslhost",  # WSL2 piggyback (filtered later)
)

# Subprocess timeouts — keep all read paths < 3s, never block hub.
TIMEOUT_DOCKER_INFO_S = 3
TIMEOUT_DOCKER_PS_S = 3
TIMEOUT_WSL_LIST_S = 3
TIMEOUT_QUIT_S = 15
TIMEOUT_KILL_S = 5

# Restart-loop heuristic
RESTART_LOOP_WINDOW_S = 60
RESTART_LOOP_THRESHOLD = 3

# Cached restart history { container_id: [unix_ts, ...] }
_RESTART_HISTORY: dict[str, list[float]] = {}


# ────────────────────────────────────────────────────────────────────────────
# Resource gate (lazy import — never crash if module missing)
# ────────────────────────────────────────────────────────────────────────────


def _should_throttle() -> bool:
    try:
        from nokido_agent.app.forge_resource_manager import should_throttle  # type: ignore

        return bool(should_throttle())
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────────────
# Subprocess helpers — timeout + CREATE_NO_WINDOW + never raise
# ────────────────────────────────────────────────────────────────────────────


def _run(cmd: list[str] | str, timeout: int, shell: bool = False) -> tuple[int, str, str]:
    """Run command, return (rc, stdout, stderr). Never raises.

    Reads bytes (not text=True) to dodge cp1252 charmap explosions on Windows
    when tools like wsl.exe emit UTF-16-LE. We decode best-effort with utf-8
    then fall back to utf-16-le, then latin-1 as last resort.
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            timeout=timeout,
            creationflags=flags,
        )
        out = _decode_best_effort(r.stdout or b"")
        err = _decode_best_effort(r.stderr or b"")
        return r.returncode, out, err
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return -2, "", f"not found: {e}"
    except Exception as e:  # pragma: no cover
        return -3, "", f"{type(e).__name__}: {e}"


def _decode_best_effort(b: bytes) -> str:
    if not b:
        return ""
    # UTF-16-LE BOM-less tell : every other byte is 0x00 in ASCII text.
    if len(b) >= 2 and b[1] == 0 and b[0] != 0:
        try:
            return b.decode("utf-16-le", errors="replace").replace("\x00", "")
        except Exception:
            pass
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc, errors="replace")
        except Exception:
            continue
    return b.decode("latin-1", errors="replace")


def _docker_socket_responsive() -> tuple[bool, float, str]:
    """Run `docker info` with timeout. Returns (ok, elapsed_s, error)."""
    t0 = time.time()
    rc, out, err = _run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        timeout=TIMEOUT_DOCKER_INFO_S,
    )
    dt = time.time() - t0
    if rc == 0 and out.strip():
        return True, dt, ""
    return False, dt, (err.strip() or out.strip() or f"rc={rc}")


def _docker_process_pids() -> list[int]:
    """List PIDs of Docker Desktop core processes. Best-effort, no raise."""
    pids: list[int] = []
    try:
        import psutil  # type: ignore
    except ImportError:
        # Fallback to tasklist
        rc, out, _err = _run(
            ["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe", "/FO", "CSV", "/NH"],
            timeout=3,
        )
        if rc == 0:
            for line in out.splitlines():
                parts = [p.strip('"') for p in line.split(",")]
                if len(parts) > 1 and parts[1].isdigit():
                    pids.append(int(parts[1]))
        return pids
    try:
        for p in psutil.process_iter(["pid", "name"]):
            try:
                name = (p.info.get("name") or "").lower()
                if name in {n.lower() for n in DOCKER_PROCESS_NAMES if n != "wslhost"} or name == "docker desktop.exe":
                    pids.append(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return pids


def _wsl_running_distros() -> list[str]:
    """Return list of running WSL2 distros. Empty list on failure."""
    rc, out, _err = _run(["wsl.exe", "-l", "--running", "--quiet"], timeout=TIMEOUT_WSL_LIST_S)
    if rc != 0:
        return []
    distros: list[str] = []
    # WSL output may be UTF-16-LE on some Windows builds; subprocess text decode
    # already collapsed it on miniforge3 default cp utf-8, but strip nulls.
    for line in out.replace("\x00", "").splitlines():
        line = line.strip()
        if line:
            distros.append(line)
    return distros


def _docker_ps_json() -> list[dict[str, Any]]:
    """`docker ps -a --format json` parsed into list of dicts. [] on failure."""
    rc, out, _err = _run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        timeout=TIMEOUT_DOCKER_PS_S,
    )
    if rc != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _detect_restart_loops(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect containers in restart loop using `docker inspect` RestartCount.

    Heuristic : if RestartCount increased >= RESTART_LOOP_THRESHOLD over the
    last RESTART_LOOP_WINDOW_S, flag container.

    To stay non-blocking we sample at most 10 containers per call.
    """
    flagged: list[dict[str, Any]] = []
    now = time.time()

    candidates = [r for r in rows if (r.get("State", "")).lower() in {"restarting", "running"}]
    candidates = candidates[:10]

    for row in candidates:
        cid = row.get("ID") or row.get("Id") or ""
        cname = row.get("Names") or row.get("Name") or ""
        if not cid:
            continue
        rc, out, _err = _run(
            ["docker", "inspect", "--format", "{{.RestartCount}}", cid],
            timeout=2,
        )
        if rc != 0:
            continue
        try:
            count = int(out.strip())
        except ValueError:
            continue

        history = _RESTART_HISTORY.setdefault(cid, [])
        # Append this observation only if RestartCount increased
        if not history or count > history.count(history[-1]):
            history.append(now)
        # Trim to window
        cutoff = now - RESTART_LOOP_WINDOW_S
        history[:] = [t for t in history if t >= cutoff]

        if len(history) >= RESTART_LOOP_THRESHOLD:
            flagged.append(
                {
                    "id": cid[:12],
                    "name": cname,
                    "restart_count": count,
                    "events_in_window": len(history),
                    "window_s": RESTART_LOOP_WINDOW_S,
                    "state": row.get("State"),
                    "status": row.get("Status"),
                }
            )
    return flagged


# ────────────────────────────────────────────────────────────────────────────
# Public API : state / health / heal / cut / relaunch
# ────────────────────────────────────────────────────────────────────────────


def docker_state() -> dict[str, Any]:
    """Return full state snapshot (non-blocking, total budget ~10s worst case).

    Schema :
      {
        "ts": float,
        "exe": str | None,
        "process_alive": bool,
        "process_pids": [int, ...],
        "socket_ok": bool,
        "socket_latency_s": float,
        "socket_error": str,
        "wsl_running": [str, ...],
        "wsl_docker_desktop_up": bool,
        "containers_total": int,
        "containers_running": int,
        "restart_loops": [{...}, ...],
        "throttled": bool,
        "exe_detected": bool,
      }
    """
    pids = _docker_process_pids()
    sock_ok, sock_lat, sock_err = _docker_socket_responsive()
    wsl_running = _wsl_running_distros()
    rows = _docker_ps_json() if sock_ok else []
    running = [r for r in rows if (r.get("State", "")).lower() == "running"]
    loops = _detect_restart_loops(rows) if sock_ok else []

    return {
        "ts": time.time(),
        "exe": DOCKER_DESKTOP_EXE,
        "exe_detected": DOCKER_DESKTOP_EXE is not None,
        "process_alive": len(pids) > 0,
        "process_pids": pids,
        "socket_ok": sock_ok,
        "socket_latency_s": round(sock_lat, 3),
        "socket_error": sock_err,
        "wsl_running": wsl_running,
        "wsl_docker_desktop_up": "docker-desktop" in [d.lower() for d in wsl_running],
        "containers_total": len(rows),
        "containers_running": len(running),
        "restart_loops": loops,
        "throttled": _should_throttle(),
    }


def health() -> dict[str, Any]:
    """Hub /api/swarm/health-compatible dict.

    `degraded=True` if any sympathetic alarm fires :
    - exe not detected (Docker Desktop not installed)
    - process alive but socket dead
    - WSL2 docker-desktop missing while process alive
    - restart loops detected
    """
    s = docker_state()
    degraded_reasons: list[str] = []

    if not s["exe_detected"]:
        degraded_reasons.append("docker_desktop_exe_not_found")
    if s["process_alive"] and not s["socket_ok"]:
        degraded_reasons.append("socket_dead")
    if s["process_alive"] and not s["wsl_docker_desktop_up"]:
        degraded_reasons.append("wsl_docker_desktop_missing")
    if s["restart_loops"]:
        degraded_reasons.append(f"restart_loops:{len(s['restart_loops'])}")

    healthy = (
        s["exe_detected"]
        and s["process_alive"]
        and s["socket_ok"]
        and (s["wsl_docker_desktop_up"] or not s["process_alive"])
    )

    return {
        "module": "forge_docker_monitor",
        "ok": healthy and not degraded_reasons,
        "degraded": bool(degraded_reasons),
        "reasons": degraded_reasons,
        "summary": _summary_line(s),
        "state": s,
    }


def _summary_line(s: dict[str, Any]) -> str:
    proc = "up" if s["process_alive"] else "down"
    sock = "ok" if s["socket_ok"] else f"dead({s['socket_error'][:30]})"
    wsl = "ok" if s["wsl_docker_desktop_up"] else "missing"
    cnt = f"{s['containers_running']}/{s['containers_total']} running"
    loops = f"{len(s['restart_loops'])} loops" if s["restart_loops"] else "no loops"
    return f"docker proc={proc} sock={sock} wsl={wsl} {cnt} {loops}"


def cut_docker(reason: str) -> dict[str, Any]:
    """Graceful stop Docker Desktop. Returns {ok, freed_ram_gb_estimate, reason}.

    Procedure :
      1. Estimate RAM held by docker processes (psutil if available).
      2. `Docker Desktop.exe --quit` (graceful, ~10-15s).
      3. If still alive after 15s : `Stop-Process -Name "Docker Desktop" -Force`.
      4. Optionally `wsl --shutdown` to release WSL2 reserved RAM.
    """
    log.warning("cut_docker called: %s", reason)
    pre_pids = _docker_process_pids()
    pre_ram_gb = _estimate_pids_ram_gb(pre_pids)

    if not DOCKER_DESKTOP_EXE:
        return {
            "ok": False,
            "freed_ram_gb_estimate": 0.0,
            "reason_logged": reason,
            "error": "Docker Desktop.exe not detected",
        }

    # 1. Graceful quit
    _audit("stop", reason or "cut_docker", target="Docker Desktop.exe --quit")
    rc, _out, err1 = _run([DOCKER_DESKTOP_EXE, "--quit"], timeout=TIMEOUT_QUIT_S)
    log.info("docker --quit rc=%s", rc)

    # Wait up to TIMEOUT_QUIT_S for processes to exit
    deadline = time.time() + TIMEOUT_QUIT_S
    while time.time() < deadline:
        if not _docker_process_pids():
            break
        time.sleep(1)

    # 2. Force-kill leftovers
    forced = False
    if _docker_process_pids():
        forced = True
        _audit("kill", "quit gracieux sans effet apres timeout", target="Stop-Process -Force")
        ps = (
            "Stop-Process -Name 'Docker Desktop','com.docker.backend',"
            "'com.docker.service','vpnkit' -Force -ErrorAction SilentlyContinue"
        )
        _run(["powershell", "-NoProfile", "-Command", ps], timeout=TIMEOUT_KILL_S)
        time.sleep(2)

    # 3. WSL release (only if not throttled — `wsl --shutdown` is heavy)
    wsl_shutdown_done = False
    if not _should_throttle():
        rc_w, _, _ = _run(["wsl.exe", "--shutdown"], timeout=10)
        wsl_shutdown_done = rc_w == 0

    post_pids = _docker_process_pids()
    freed = max(0.0, pre_ram_gb - _estimate_pids_ram_gb(post_pids))

    return {
        "ok": len(post_pids) == 0,
        "freed_ram_gb_estimate": round(freed, 2),
        "reason_logged": reason,
        "forced": forced,
        "wsl_shutdown": wsl_shutdown_done,
        "graceful_rc": rc,
        "graceful_err": err1.strip()[:120],
        "post_pids": post_pids,
    }


def _estimate_pids_ram_gb(pids: list[int]) -> float:
    if not pids:
        return 0.0
    try:
        import psutil  # type: ignore
    except ImportError:
        return 0.0
    total = 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
            total += p.memory_info().rss
        except Exception:
            continue
    return round(total / 1024**3, 2)


def relaunch_docker(wait_s: int = 60) -> dict[str, Any]:
    """Restart Docker Desktop and wait until socket responsive.

    Returns {ok, elapsed_s, attempts, final_state}.
    """
    log.warning("relaunch_docker(wait_s=%d)", wait_s)
    _audit("start", "relaunch_docker", wait_s=wait_s)
    if not DOCKER_DESKTOP_EXE:
        return {"ok": False, "elapsed_s": 0.0, "error": "Docker Desktop.exe not detected"}

    if _should_throttle():
        return {
            "ok": False,
            "elapsed_s": 0.0,
            "skipped_throttle": True,
            "error": "system throttled, refusing to launch heavy process",
        }

    t0 = time.time()
    # Use Start-Process so we don't block on the GUI bootstrap.
    ps = f'Start-Process -FilePath "{DOCKER_DESKTOP_EXE}" -WindowStyle Hidden'
    _run(["powershell", "-NoProfile", "-Command", ps], timeout=10)

    attempts = 0
    deadline = t0 + wait_s
    while time.time() < deadline:
        attempts += 1
        ok, _lat, _err = _docker_socket_responsive()
        if ok:
            return {
                "ok": True,
                "elapsed_s": round(time.time() - t0, 1),
                "attempts": attempts,
            }
        time.sleep(2)

    return {
        "ok": False,
        "elapsed_s": round(time.time() - t0, 1),
        "attempts": attempts,
        "final_state": docker_state(),
        "error": f"socket still dead after {wait_s}s",
    }


def auto_heal(dry_run: bool = True) -> dict[str, Any]:
    """Inspect Docker, decide if action needed, take action if dry_run=False.

    Returns full plan + executed actions. See module docstring decision tree.
    """
    # Corrigibility (A#2): verrou humain -> jamais d'action autonome (force dry-run).
    try:
        from nokido_agent.app.forge_opsec import is_human_locked
        if is_human_locked():
            dry_run = True
    except Exception:
        pass
    s = docker_state()
    plan: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []

    throttled = s["throttled"]

    # Scenario : process alive but socket dead → relaunch
    if s["process_alive"] and not s["socket_ok"]:
        action = {
            "scenario": "socket_dead_with_process_alive",
            "action": "cut_then_relaunch",
            "reason": s.get("socket_error", "socket unresponsive"),
            "blocked_by_throttle": throttled,
        }
        plan.append(action)
        if not dry_run and not throttled:
            cut_res = cut_docker(reason="auto_heal:socket_dead")
            relaunch_res = relaunch_docker(wait_s=60)
            executed.append({**action, "cut": cut_res, "relaunch": relaunch_res})

    # Scenario : process dead but exe detected → relaunch (unless throttled)
    elif not s["process_alive"] and s["exe_detected"]:
        action = {
            "scenario": "process_dead",
            "action": "relaunch",
            "blocked_by_throttle": throttled,
        }
        plan.append(action)
        if not dry_run and not throttled:
            relaunch_res = relaunch_docker(wait_s=60)
            executed.append({**action, "relaunch": relaunch_res})

    # Scenario : WSL distro missing while process up → wsl --shutdown then relaunch
    if s["process_alive"] and not s["wsl_docker_desktop_up"]:
        action = {
            "scenario": "wsl_docker_desktop_missing",
            "action": "wsl_shutdown_and_relaunch",
            "blocked_by_throttle": throttled,
        }
        plan.append(action)
        if not dry_run and not throttled:
            cut_res = cut_docker(reason="auto_heal:wsl_distro_missing")
            relaunch_res = relaunch_docker(wait_s=60)
            executed.append({**action, "cut": cut_res, "relaunch": relaunch_res})

    # Scenario : restart loops → REPORT only, never auto-action
    if s["restart_loops"]:
        action = {
            "scenario": "container_restart_loop",
            "action": "report_only",
            "containers": s["restart_loops"],
            "note": "manual inspection required; refusing auto-kill",
        }
        plan.append(action)

    if not plan:
        plan.append({"scenario": "nominal", "action": "none"})

    return {
        "ts": time.time(),
        "dry_run": dry_run,
        "throttled": throttled,
        "plan": plan,
        "executed": executed,
        "state": s,
    }


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge_docker_monitor",
        description="Autonomous Docker Desktop watchdog (Nokido SN vegetatif).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("state", help="JSON snapshot of all signals.")
    sub.add_parser("health", help="Hub /api/swarm/health-friendly dict.")

    p_heal = sub.add_parser("heal", help="Diagnose + (optionally) heal.")
    p_heal.add_argument("--apply", action="store_true", help="Execute heal actions (default = dry-run).")

    p_cut = sub.add_parser("cut", help="Graceful stop Docker Desktop.")
    p_cut.add_argument("reason", help="Reason for the cut (logged).")

    p_re = sub.add_parser("relaunch", help="Restart Docker Desktop.")
    p_re.add_argument("--wait", type=int, default=60, help="Wait timeout in s.")

    args = parser.parse_args(argv)

    if args.cmd == "state":
        print(json.dumps(docker_state(), indent=2, ensure_ascii=False))
    elif args.cmd == "health":
        print(json.dumps(health(), indent=2, ensure_ascii=False))
    elif args.cmd == "heal":
        result = auto_heal(dry_run=not args.apply)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "cut":
        print(json.dumps(cut_docker(args.reason), indent=2, ensure_ascii=False))
    elif args.cmd == "relaunch":
        print(json.dumps(relaunch_docker(wait_s=args.wait), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
