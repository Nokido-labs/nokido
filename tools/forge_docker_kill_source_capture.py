"""forge_docker_kill_source_capture.py — RCA blocker Docker (2026-08-06) : capture
QUI envoie le SIGTERM (exit status 15) qui tue com.docker.backend.exe.

Complement de sandbox/capture_docker_instrumented.py (AGY, 31-07) : celui-la
echantillonnait l'ETAT et a trouve la piste VHD, mais ne NOMMAIT pas le tueur.
Ici on vise le QUI, par correlation temporelle a l'instant precis de la mort.

Ce que le RCA du 06/08 a etabli, et que ce capteur doit trancher :
  - le backend meurt d'un SIGTERM PROPRE (exit 15), pas d'un crash/OOM/panic ;
  - l'auto-update est desactive (le backend logue 'background update disabled') et il
    tombe quand meme -> updater ELIMINE ;
  - Docker Desktop.exe constate 'backend process exited' SANS raison ;
  - le keeper Nokido est SILENT -> tueur EXTERNE a Nokido.
  Candidats restants : com.docker.service (helper SCM qui gere le cycle backend),
  un settings-change qui restart l'engine, WSL/OS.

Methode : poll PRECIS du backend (pid + create_time). Mort = disparition ;
restart = create_time qui change. A la transition, HARVEST immediat (fenetre -120s) :
  1. SCM (System / Service Control Manager) : stop/start de com.docker.service* ;
  2. Sysmon ProcessAccess (EID 10) ciblant le backend, GrantedAccess terminate (0x1)
     -> nomme le tueur SI il fait OpenProcess+TerminateProcess (config fournie) ;
  3. Security 4689 (exit code du backend, si audit process-termination actif) ;
  4. tail Docker Desktop.exe.log + monitor.log au moment T ;
  5. WSL : 'wsl -l -v'.
Rapport horodate -> sandbox/docker_kill_source_<ts>.log, avec un VERDICT motive.

USAGE (compte OWNER — subprocess requis, PAS le sandbox du hub) :
    ~/miniforge3/python.exe tools/forge_docker_kill_source_capture.py --minutes 90
Laisser tourner PENDANT que Docker est up ; capture la PROCHAINE mort puis rend la main.
Sysmon optionnel (config/sysmon_docker_backend.xml). Sans lui, la voie SCM+correlation tient.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime

BACKEND = "com.docker.backend.exe"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox")
LOG_HOST = os.path.expanduser("~/AppData/Local/Docker/log/host")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _ps(cmd: str, timeout: int = 15) -> str:
    """Execute une commande PowerShell (compte owner) et rend stdout+stderr."""
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, errors="replace", timeout=timeout)
        extra = ("\n[stderr] " + p.stderr) if p.stderr.strip() else ""
        return (p.stdout or "") + extra
    except Exception as exc:  # noqa: BLE001
        return f"[ps error] {type(exc).__name__}: {exc}"


def _backend_snapshot() -> list:
    """Rend [(pid, creation_date)] du backend, via CIM (owner-visible)."""
    out = _ps("Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
              "Select-Object ProcessId, CreationDate | ConvertTo-Json" % BACKEND, timeout=8)
    procs = []
    try:
        text = out.strip()
        data = json.loads(text) if text.startswith(("[", "{")) else []
        if isinstance(data, dict):
            data = [data]
        for d in data:
            procs.append((d.get("ProcessId"), str(d.get("CreationDate"))))
    except Exception:  # noqa: BLE001 - muet-ok : snapshot best-effort, l'absence EST le signal
        pass
    return procs


def _harvest(logf, when: str) -> None:
    def emit(src: str, msg: str) -> None:
        line = f"[{_ts()}] [{src}] {msg}"
        print(line)
        logf.write(line + "\n")
        logf.flush()

    emit("HARVEST", f"=== MORT/RESTART DETECTE @ {when} — collecte de la SOURCE ===")
    since = "(Get-Date).AddSeconds(-120)"

    emit("SCM", "Service Control Manager (System) — stop/start docker* :")
    emit("SCM", _ps("Get-WinEvent -FilterHashtable @{LogName='System'; "
                    "ProviderName='Service Control Manager'; StartTime=%s} "
                    "-ErrorAction SilentlyContinue | Where-Object { $_.Message -match 'docker' } | "
                    "Select-Object TimeCreated, Id, Message | Format-List | Out-String" % since))

    emit("SYSMON", "Sysmon ProcessAccess (EID10) ciblant le backend (si Sysmon installe) :")
    emit("SYSMON", _ps("Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Sysmon/Operational'; "
                       "Id=10; StartTime=%s} -ErrorAction SilentlyContinue | "
                       "Where-Object { $_.Message -match 'com.docker.backend.exe' } | "
                       "Select-Object TimeCreated, Message | Format-List | Out-String" % since))

    emit("SECURITY", "Security 4689 (fin process backend, si audit process-termination actif) :")
    emit("SECURITY", _ps("Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4689; StartTime=%s} "
                         "-ErrorAction SilentlyContinue | Where-Object { $_.Message -match 'com.docker.backend' } | "
                         "Select-Object TimeCreated, Message | Format-List | Out-String" % since))

    for name in ("Docker Desktop.exe.log", "monitor.log"):
        path = os.path.join(LOG_HOST, name)
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                tail = fh.readlines()[-25:]
            emit("DDLOG", f"--- tail {name} ---\n" + "".join(tail))
        except Exception as exc:  # noqa: BLE001
            emit("DDLOG", f"{name} illisible: {exc}")

    emit("WSL", _ps("wsl -l -v | Out-String"))
    emit("VERDICT", "Lecture : un stop 'com.docker.service' dans SCM a T = LUI. "
                    "Un SourceImage Sysmon EID10 sur le backend = ce process a TerminateProcess. "
                    "Aucun des deux, et Docker Desktop 'backend process exited' seul = "
                    "shutdown IPC interne a Docker Desktop (settings-apply / engine restart).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture la source du kill du backend Docker.")
    ap.add_argument("--minutes", type=float, default=90.0, help="Duree de veille max.")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "docker_kill_source_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(path, "w", encoding="utf-8") as logf:
        def emit(src: str, msg: str) -> None:
            line = f"[{_ts()}] [{src}] {msg}"
            print(line)
            logf.write(line + "\n")
            logf.flush()

        emit("CTRL", f"capture SOURCE du kill backend — rapport: {path}")
        prev = set(_backend_snapshot())
        emit("CTRL", f"backend au demarrage: {sorted(prev) or 'ABSENT (lancer Docker d abord)'}")
        deadline = time.time() + args.minutes * 60.0
        mort = False
        while time.time() < deadline:
            cur = set(_backend_snapshot())
            if prev and not cur:
                _harvest(logf, _ts())
                emit("CTRL", "mort capturee — fin.")
                mort = True
                break
            if prev and cur and cur != prev:
                emit("CTRL", f"RESTART backend (create_time change): {sorted(prev)} -> {sorted(cur)}")
                _harvest(logf, _ts())
                prev = cur
                time.sleep(1.5)
                continue
            prev = cur or prev
            time.sleep(1.5)
        if not mort:
            emit("CTRL", f"fin de fenetre ({args.minutes}min) sans mort — Docker a TENU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
