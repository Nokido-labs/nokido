"""
forge_service_watchdog.py — Watchdog HTTP pour les services NSSM Nokido
=========================================================================
Détecte les services silencieusement DOWN (timeout HTTP) et les redémarre.

Stratégie sans admin permanent :
  - Si PID récupérable via /health → taskkill /F (user peut tuer ses propres procs)
  - NSSM AppRestartDelay prend le relai pour relancer
  - Pour restart direct (nssm restart) : doit tourner en LocalSystem ou admin
    → Installer comme service NSSM avec `tools/install_watchdog_nssm.ps1`

Usage standalone :
    LAFORGE_PYTHON app/forge_service_watchdog.py [--interval 30] [--dry-run]

Usage import :
    from forge_service_watchdog import ServiceWatchdog
    wd = ServiceWatchdog()
    wd.start()   # daemon thread
    wd.stop()
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import time
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Prevent console windows when spawning processes from a windowless NSSM service
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

logger = logging.getLogger("Nokido.ServiceWatchdog")

# ── Carte des services HTTP surveillés ────────────────────────────────────────
# Seuls les services avec endpoint HTTP. Daemons sans port = exclus (pas de health check possible).
SERVICE_MAP: list[dict] = [
    # Supervisor itself — closes the "who watches the supervisor" blind spot.
    {"name": "LaForge-Master", "url": "http://127.0.0.1:8765/supervisor/status", "nssm": "LaForge-Master"},
    {"name": "NokidoMCP", "url": "http://127.0.0.1:8766/health", "nssm": "NokidoMCP"},
    {"name": "NokidoWebHub", "url": "http://127.0.0.1:7400/health", "nssm": "NokidoWebHub"},
    {"name": "NokidoDenoProxy", "url": "http://127.0.0.1:8000/health", "nssm": "NokidoDenoProxy"},
    {"name": "NokidoDenoWebHub", "url": "http://127.0.0.1:7401/health", "nssm": "NokidoDenoWebHub"},
    {"name": "NokidoOpenAIProxy", "url": "http://127.0.0.1:7777/v1/models", "nssm": "NokidoOpenAIProxy"},
    {"name": "NokidoDenoHubMCP", "url": "http://127.0.0.1:8769/health", "nssm": "NokidoDenoHubMCP"},
    # LlamaNative est Manual (désactivé RAM) — omis volontairement
    # NokidoLlamaRouter (8092) RETIRE du watchdog : llmPool ON-DEMAND (spawn par le pool
    # a la demande, mlock ~7GB). Le relancer de force toutes les 60s immobilisait la RAM
    # inutilement (constate 2026-07-01 : restart repete d'un service on-demand). Le pool LLM
    # gere son cycle ; le watchdog ne surveille que les services CENSES etre toujours up.
]

NSSM_PATH = os.environ.get(
    "LAFORGE_NSSM",
    r"C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe",
)

_DEFAULT_INTERVAL = int(os.environ.get("LAFORGE_WATCHDOG_INTERVAL", "30"))
_FAIL_THRESHOLD = int(os.environ.get("LAFORGE_WATCHDOG_FAIL_THRESHOLD", "2"))
_PING_TIMEOUT = float(os.environ.get("LAFORGE_WATCHDOG_PING_TIMEOUT", "8"))


def _supervisor_token() -> str:
    """Bearer token attendu par l'API de contrôle du superviseur (:8765).

    Miroir EXACT de supervisor.ts: _SUPERVISOR_TOKEN = LAFORGE_SUPERVISOR_TOKEN
    ?? FORGE_MCP_TOKEN. Le watchdog est un service NSSM SÉPARÉ (n'hérite PAS de
    l'env chargé par le superviseur) → on lit d'abord l'env, puis le coffre DPAPI
    machine-wide (forge_secrets, accessible en LocalSystem). Sans ce token, le
    POST /supervisor/restart renvoyait 401 = auto-recovery MORTE (incident hub
    wedge 2026-07-01). L'ordre LAFORGE_SUPERVISOR_TOKEN d'abord respecte la
    précédence côté superviseur (sinon mismatch si les deux diffèrent)."""
    for k in ("LAFORGE_SUPERVISOR_TOKEN", "FORGE_MCP_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v
    try:
        from nokido_agent.app.forge_secrets import get_secret

        for k in ("LAFORGE_SUPERVISOR_TOKEN", "FORGE_MCP_TOKEN"):
            v = get_secret(k)
            if v:
                return v
    except Exception as exc:
        logger.warning(f"[watchdog] token superviseur indisponible (env+vault): {exc}")
    return ""


class ServiceWatchdog:
    def __init__(
        self,
        interval_s: int = _DEFAULT_INTERVAL,
        fail_threshold: int = _FAIL_THRESHOLD,
        dry_run: bool = False,
    ) -> None:
        self.interval_s = interval_s
        self.fail_threshold = fail_threshold
        self.dry_run = dry_run
        self._fail_counts: dict[str, int] = {s["name"]: 0 for s in SERVICE_MAP}
        self._restarting: set[str] = set()  # guards concurrent restart attempts
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ServiceWatchdog")
        self._thread.start()
        logger.info(f"ServiceWatchdog started (interval={self.interval_s}s, threshold={self.fail_threshold})")

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=5)

    def check_once(self) -> dict[str, str]:
        """Synchronous one-shot check. Returns {svc_name: 'ok'|'fail'|'restarted'}."""
        return asyncio.run(self._check_all())

    # ── Internal ───────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                asyncio.run(self._check_all())
            except Exception as exc:
                logger.error(f"[watchdog] loop error: {exc}")
            self._stop_evt.wait(self.interval_s)

    async def _check_all(self) -> dict[str, str]:
        from nokido_agent.app.forge_ping_monitor import ping_all_providers  # lazy import

        results = await ping_all_providers(SERVICE_MAP, timeout=_PING_TIMEOUT)
        status: dict[str, str] = {}

        for svc in SERVICE_MAP:
            name = svc["name"]
            ok = results.get(name, {}).get("ok", False)

            if ok:
                self._fail_counts[name] = 0
                status[name] = "ok"
            else:
                self._fail_counts[name] += 1
                err = results.get(name, {}).get("error", "timeout")
                logger.warning(f"[watchdog] {name} DOWN ({self._fail_counts[name]}×) — {err}")

                if self._fail_counts[name] >= self.fail_threshold:
                    if name in self._restarting:
                        status[name] = "restarting"
                        continue
                    self._restarting.add(name)
                    try:
                        action = self._restart(svc)
                    finally:
                        self._restarting.discard(name)
                    status[name] = action
                    if action == "restarted":
                        self._fail_counts[name] = 0
                else:
                    status[name] = "fail"

        return status

    def _restart(self, svc: dict) -> str:
        nssm_name = svc["nssm"]
        name = svc["name"]

        # Corrigibility (off-switch d'EXECUTION) : le kill-switch humain DOMINE le
        # self-heal. Si human_locked, NE PAS ressusciter le service tue — sinon le
        # watchdog annule la decision d'arret de l'humain (= anti-corrigibilite).
        # Complete A#1 (firewall network_kill). Fail-open: si le check echoue, on
        # relance (comportement actuel) pour ne pas figer une recup sur erreur DB.
        try:
            from nokido_agent.app.forge_opsec import is_human_locked

            if is_human_locked():
                logger.warning(f"[watchdog] human-lock actif — relance de {name} SUPPRIMEE (off-switch)")
                return "halted-by-kill-switch"
        except Exception as exc:
            logger.warning(f"[watchdog] human-lock check indisponible (fail-open): {exc}")

        if self.dry_run:
            logger.info(f"[watchdog] DRY-RUN restart {name}")
            return "dry-run"

        # Strategy 0: supervisor API — primary path post-NSSM-migration.
        # Services are children of LaForge-Master (supervisor.ts :8765); their
        # NSSM names may be deleted. The supervisor owns child restarts.
        # Skipped for LaForge-Master itself (can't self-restart via its own
        # API when down — strategies A/B handle its NSSM service, which stays).
        if name != "LaForge-Master":
            try:
                import urllib.request

                req = urllib.request.Request(
                    f"http://127.0.0.1:8765/supervisor/restart/{name}",
                    method="POST",
                )
                # Auth Bearer OBLIGATOIRE : les mutations de contrôle sont gated
                # (supervisor.ts requireAuth). Sans header -> 401 -> restart raté
                # = wedge qui dure (incident 2026-07-01). Fail-loud si pas de token.
                _tok = _supervisor_token()
                if _tok:
                    req.add_header("Authorization", f"Bearer {_tok}")
                else:
                    logger.error(
                        f"[watchdog] AUCUN token superviseur — restart {name} sera 401 "
                        "(set LAFORGE_SUPERVISOR_TOKEN/FORGE_MCP_TOKEN ou vault DPAPI)"
                    )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if resp.status == 200:
                        logger.info(f"[watchdog] ✓ supervisor restart {name}")
                        return "restarted"
            except Exception as exc:
                logger.warning(f"[watchdog] supervisor restart {name} failed: {exc}")

        # Strategy A: nssm restart (needs admin / LocalSystem)
        if os.path.exists(NSSM_PATH):
            try:
                r = subprocess.run(
                    [NSSM_PATH, "restart", nssm_name],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=15,
                    creationflags=_NO_WINDOW,
                )
                if r.returncode == 0:
                    logger.info(f"[watchdog] ✓ nssm restart {name}")
                    return "restarted"
                logger.warning(f"[watchdog] nssm restart {name} rc={r.returncode}: {(r.stderr or '')[:120]}")
            except Exception as exc:
                logger.warning(f"[watchdog] nssm restart failed: {exc}")

        # Strategy B: Restart-Service via PowerShell (needs admin)
        try:
            r = subprocess.run(
                ["powershell", "-NonInteractive", "-Command", f"Restart-Service -Name '{nssm_name}' -Force"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=20,
                creationflags=_NO_WINDOW,
            )
            if r.returncode == 0:
                logger.info(f"[watchdog] ✓ Restart-Service {name}")
                return "restarted"
            logger.warning(f"[watchdog] Restart-Service {name} rc={r.returncode}: {(r.stderr or '')[:120]}")
        except Exception as exc:
            logger.warning(f"[watchdog] Restart-Service failed: {exc}")

        # Strategy C: kill PID → NSSM auto-restarts (works if process owned by current user)
        pid = self._get_pid(nssm_name)
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10, creationflags=_NO_WINDOW
                )
                logger.info(f"[watchdog] ✓ taskkill PID={pid} for {name} (NSSM will restart)")
                return "restarted"
            except Exception as exc:
                logger.warning(f"[watchdog] taskkill failed: {exc}")

        # Strategy D: last-resort kill-by-listening-port — INDEPENDANT du superviseur.
        # Un service enfant-superviseur n'a pas de vrai service NSSM -> strategies
        # A/B/C echouent ("le service ne peut pas etre demarre") et strategy 0
        # timeout si le superviseur est lui-meme sature (RCA hub wedge 2026-07-02 :
        # supervisor restart failed timed out -> flotte morte -> reboot manuel).
        # Tuer le PID qui detient le port en ecoute libere un event-loop wedge ; le
        # child-monitor du superviseur (ou NSSM AppExit=Restart) respawn frais.
        # Mirroir de l'idiome psutil-listener forge_lifecycle_tool.find_pid /
        # forge_inspector._check_ports (anti-dup : meme approche prouvee).
        port_pid = self._get_pid_by_port(svc)
        if port_pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(port_pid)],
                    capture_output=True,
                    timeout=10,
                    creationflags=_NO_WINDOW,
                )
                logger.info(f"[watchdog] ✓ taskkill PID={port_pid} by-port for {name} (superviseur respawn)")
                return "restarted"
            except Exception as exc:
                logger.warning(f"[watchdog] taskkill by-port {name} failed: {exc}")

        # Strategy D-bis: boot-hang — process VIVANT mais port JAMAIS binde.
        # (Incident 2026-07-03 : respawn 1s apres resume de veille -> _build_app
        # pendu avant uvicorn bind :8766 -> kill-by-port aveugle (aucun listener),
        # superviseur muet -> down des heures.) On retrouve le process par CMDLINE
        # (script identitaire du service) et on le tue ; le child-monitor du
        # superviseur respawn dans un systeme desormais reveille. Le cycle 30s du
        # watchdog re-tue si le boot pend a nouveau -> converge quand le systeme
        # est pret.
        cmd_pid = self._get_pid_by_cmdline(svc)
        if cmd_pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(cmd_pid)],
                    capture_output=True,
                    timeout=10,
                    creationflags=_NO_WINDOW,
                )
                logger.info(f"[watchdog] ✓ taskkill PID={cmd_pid} by-cmdline for {name} (boot-hang, superviseur respawn)")
                return "restarted"
            except Exception as exc:
                logger.warning(f"[watchdog] taskkill by-cmdline {name} failed: {exc}")

        logger.error(f"[watchdog] ✗ Could not restart {name} — needs admin or service migration")
        return "fail-no-admin"

    def _get_pid(self, nssm_name: str) -> Optional[int]:
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NonInteractive",
                    "-Command",
                    f"(Get-Service '{nssm_name}').Id",
                ],  # not standard, use WMI
                capture_output=True,
                text=True,
                errors="replace",
                timeout=8,
                creationflags=_NO_WINDOW,
            )
            if r.returncode == 0 and r.stdout.strip().isdigit():
                return int(r.stdout.strip())
            # Fallback: query via tasklist
            r2 = subprocess.run(
                [
                    "powershell",
                    "-NonInteractive",
                    "-Command",
                    f"Get-WmiObject Win32_Service | Where-Object {{$_.Name -eq '{nssm_name}'}} | Select-Object -Expand ProcessId",
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=8,
                creationflags=_NO_WINDOW,
            )
            val = r2.stdout.strip()
            return int(val) if val.isdigit() else None
        except Exception:
            return None

    def _get_pid_by_port(self, svc: dict) -> Optional[int]:
        """PID du process qui ECOUTE le port du service (etat LISTENING).

        Dernier recours INDEPENDANT du superviseur : pour un service enfant-
        superviseur (sans vrai service NSSM), c'est le seul PID recuperable quand
        strategies A/B/C ont echoue. psutil d'abord (rapide, exact) ; fallback
        netstat -ano (colonne PID des lignes LISTENING). Port derive de svc['url'].
        Mirroir de forge_lifecycle_tool.find_pid / forge_inspector._check_ports."""
        port: Optional[int] = None
        try:
            import re as _re

            m = _re.search(r":(\d+)", svc.get("url", ""))
            if m:
                port = int(m.group(1))
        except Exception:
            port = None
        if not port:
            return None

        # Primary: psutil (exact, cross-platform)
        try:
            import psutil  # type: ignore

            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN" and conn.pid:
                    return int(conn.pid)
        except Exception:
            pass

        # Fallback: netstat -ano (Windows) — derniere colonne = PID des LISTENING
        try:
            r = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=_NO_WINDOW,
            )
            for line in (r.stdout or "").splitlines():
                if "LISTENING" not in line:
                    continue
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}"):
                    pid_s = parts[-1]
                    if pid_s.isdigit() and int(pid_s) > 0:
                        return int(pid_s)
        except Exception:
            pass
        return None

    # Script identitaire par service — match STRICT de cmdline pour retrouver un
    # process pendu AVANT le bind de son port (boot-hang pre-bind). Map volontairement
    # CONSERVATRICE : uniquement les services dont le script est non-ambigu.
    _SVC_SCRIPT = {
        "NokidoMCP": "nokido_hub.py",
    }

    def _get_pid_by_cmdline(self, svc: dict) -> Optional[int]:
        """PID du process python dont la cmdline contient le script du service.

        Complement de _get_pid_by_port pour le boot-hang (incident 2026-07-03) :
        process vivant mais pendu avant uvicorn bind -> invisible cote connexions.
        Garde-fous : jamais soi-meme ; process python uniquement ; script mappe
        explicitement (sinon None = pas de kill)."""
        script = self._SVC_SCRIPT.get(svc.get("name", ""))
        if not script:
            return None
        try:
            import psutil  # type: ignore

            me = os.getpid()
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if proc.info["pid"] == me:
                        continue
                    pname = (proc.info.get("name") or "").lower()
                    if "python" not in pname:
                        continue
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if script in cmd:
                        return int(proc.info["pid"])
                except Exception:
                    continue
        except Exception:
            pass
        return None


# ── CLI entrypoint ─────────────────────────────────────────────────────────────


def _main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Nokido service watchdog")
    p.add_argument("--interval", type=int, default=_DEFAULT_INTERVAL, help="Check interval (seconds)")
    p.add_argument("--dry-run", action="store_true", help="Log only, don't restart")
    p.add_argument("--once", action="store_true", help="Run one check then exit")
    args = p.parse_args()

    wd = ServiceWatchdog(interval_s=args.interval, dry_run=args.dry_run)
    if args.once:
        import json

        print(json.dumps(wd.check_once(), indent=2))
        return

    wd.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        wd.stop()


if __name__ == "__main__":
    _main()
