from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_idle_watchdog
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_idle_watchdog.py — Arrêt automatique des services Nokido si inactifs
============================================================================
Si un service ne reçoit pas de requête depuis IDLE_TIMEOUT_SEC secondes,
il s'arrête proprement via NSSM.

Permet la mise en veille Windows sans blocage.

Usage (dans chaque service au démarrage) :
    from forge_idle_watchdog import IdleWatchdog
    watchdog = IdleWatchdog(service_name="NokidoHub", idle_timeout=300)
    watchdog.start()
    # À chaque requête reçue :
    watchdog.ping()

Config Nokido.env :
    LAFORGE_IDLE_TIMEOUT=300   # secondes (0 = désactivé)
    LAFORGE_IDLE_ENABLED=true
"""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("Nokido.IdleWatchdog")

_ROOT = Path(__file__).resolve().parent.parent.parent  # app/hardware/ → LaForge/
_STATE = _ROOT / "sandbox" / "idle_state.json"


def _idle_timeout() -> int:
    """Lit le timeout depuis Nokido.env ou env var."""
    val = os.environ.get("LAFORGE_IDLE_TIMEOUT", "300")
    try:
        return int(val)
    except ValueError:
        return 300


def _idle_enabled() -> bool:
    """Idle enabled."""
    return os.environ.get("LAFORGE_IDLE_ENABLED", "true").lower() == "true"


class IdleWatchdog:
    """
    Watchdog d inactivité — arrête le service NSSM si pas de ping depuis timeout.

    Thread daemon — s'arrête automatiquement avec le process parent.
    Ne bloque pas la mise en veille Windows.
    """

    def __init__(
        self,
        service_name: str,
        idle_timeout: int = 0,
        check_interval: int = 30,
    ):
        """Init.

        Args:
            service_name: Description.
            idle_timeout: Description.
            check_interval: Description.
        """
        self.service_name = service_name
        self.idle_timeout = idle_timeout or _idle_timeout()
        self.check_interval = check_interval
        self._last_ping = time.monotonic()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._enabled = _idle_enabled() and self.idle_timeout > 0
        self._last_retrain_count = 0

    def ping(self) -> None:
        """Signale une activité — réinitialise le compteur d inactivité."""
        with self._lock:
            self._last_ping = time.monotonic()

    def idle_seconds(self) -> float:
        """Retourne le nombre de secondes sans activité."""
        with self._lock:
            return time.monotonic() - self._last_ping

    def start(self) -> None:
        """Lance le thread watchdog en arrière-plan."""
        if not self._enabled:
            logger.info(f"[IdleWatchdog] {self.service_name} — désactivé (LAFORGE_IDLE_ENABLED=false ou timeout=0)")
            return
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"IdleWatchdog-{self.service_name}",
        )
        self._thread.start()
        logger.info(
            f"[IdleWatchdog] {self.service_name} — démarré (timeout={self.idle_timeout}s, check={self.check_interval}s)"
        )

    def stop(self) -> None:
        """Arrête le watchdog proprement."""
        self._stop_event.set()

    def _loop(self) -> None:
        """Loop."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self.check_interval)
            if self._stop_event.is_set():
                break

            idle = self.idle_seconds()
            self._write_state(idle)
            self._check_dt_retrain()
            self._check_auto_evolution(idle)

            if idle >= self.idle_timeout:
                logger.warning(
                    f"[IdleWatchdog] {self.service_name} inactif depuis {idle:.0f}s "
                    f"(seuil={self.idle_timeout}s) → arrêt"
                )
                self._shutdown()
                break

    def _check_dt_retrain(self) -> None:
        """Auto-retrain DT router si 50+ nouvelles décisions depuis dernier retrain."""
        try:
            import json as _json, subprocess as _sp

            log_path = _ROOT / "shadow_mutation" / "rag_index" / "router_decisions.jsonl"
            lock_path = _ROOT / "sandbox" / "dt_retrain.lock"
            state_path = _ROOT / "sandbox" / "dt_last_retrain.json"
            if not log_path.exists() or lock_path.exists():
                return
            last_ts = 0.0
            if state_path.exists():
                try:
                    last_ts = _json.loads(state_path.read_text("utf-8")).get("ts", 0.0)
                except Exception:
                    pass
            new_lines = 0
            for line in log_path.read_text("utf-8", errors="replace").splitlines():
                try:
                    if _json.loads(line).get("ts", 0) > last_ts:
                        new_lines += 1
                except Exception:
                    pass
            if new_lines >= 50:
                script = _ROOT / "tools" / "auto_retrain_dt.py"
                _sp.Popen(
                    [os.environ.get("LAFORGE_PYTHON_BIN", "python"), str(script)],
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                )
                lock_path.touch()
                self._last_retrain_count = new_lines
                logger.info(f"[IdleWatchdog] DT retrain launched ({new_lines} new samples)")
        except Exception as e:
            logger.debug(f"[IdleWatchdog] _check_dt_retrain: {e}")

    def _check_auto_evolution(self, idle_sec: float) -> None:
        """Trigger autonomous evolution when idle >= 120s and resources available."""
        _MIN_IDLE = 120.0
        _LOCK = _ROOT / "sandbox" / "auto_evolution.lock"
        if idle_sec < _MIN_IDLE or _LOCK.exists():
            return
        try:
            import psutil as _pu, urllib.request as _ur, json as _j

            mem = _pu.virtual_memory()
            cpu = _pu.cpu_percent(interval=1)
            if mem.percent > 85 or cpu > 60:
                return
            _LOCK.touch()
            body = _j.dumps(
                {
                    "method": "tools/call",
                    "params": {
                        "name": "trigger_autonomous_evolution",
                        "arguments": {"intent": "auto_idle_evolution", "agents": ["WORKER_0", "GEMINI"]},
                    },
                }
            ).encode()
            req = _ur.Request(
                "http://127.0.0.1:8766/mcp",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {get_secret('FORGE_MCP_TOKEN') or ''}",
                },
                method="POST",
            )
            _ur.urlopen(req, timeout=5).close()
            logger.info(
                f"[IdleWatchdog] auto_evolution triggered (idle={idle_sec:.0f}s cpu={cpu:.0f}% mem={mem.percent:.0f}%)"
            )
            import threading as _th

            _th.Timer(300, lambda: _LOCK.unlink(missing_ok=True)).start()
        except Exception as e:
            logger.debug(f"[IdleWatchdog] _check_auto_evolution: {e}")
            try:
                _LOCK.unlink(missing_ok=True)
            except:
                pass

    def _write_state(self, idle_sec: float) -> None:
        """Écrit l état dans sandbox/idle_state.json pour monitoring."""
        try:
            import json

            state = {}
            if _STATE.exists():
                try:
                    state = json.loads(_STATE.read_text(encoding="utf-8"))
                except Exception:
                    pass
            state[self.service_name] = {
                "idle_sec": round(idle_sec, 1),
                "timeout": self.idle_timeout,
                "pct": round(idle_sec / self.idle_timeout * 100, 1),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            try:
                from nokido_agent.app.forge_hub_storage import atomic_write

                atomic_write(_STATE, json.dumps(state, indent=2))
            except ImportError:
                _STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _shutdown(self) -> None:
        """Arrête le service NSSM proprement."""
        try:
            # 1. Écrire dans le heartbeat
            hb_path = _ROOT / "sandbox" / "heartbeat.json"
            if hb_path.exists():
                import json

                hb = json.loads(hb_path.read_text(encoding="utf-8"))
                hb.setdefault("warnings", []).append(f"{self.service_name} arrêté (inactivité {self.idle_timeout}s)")
                hb_path.write_text(json.dumps(hb, indent=2), encoding="utf-8")

            # 2. Arrêter via NSSM
            logger.info(f"[IdleWatchdog] nssm stop {self.service_name}")
            subprocess.Popen(
                ["nssm", "stop", self.service_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).wait(timeout=10)

        except Exception as e:
            logger.error(f"[IdleWatchdog] shutdown error: {e}")
            # Fallback : sys.exit
            import sys

            sys.exit(0)
