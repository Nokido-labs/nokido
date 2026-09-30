"""
app/web_hub/watcher.py - Auto-restart watcher pour les modules Nokido.

PRINCIPE : verifie periodiquement chaque module opt-in ; si status != running
ET si health_url configuree renvoie KO, relance via launcher.start().

GARDE-FOUS :
  - Backoff exponentiel (1, 2, 4, 8, 16, 32, 60s cap)
  - Circuit-breaker : ≥ MAX_RESTARTS dans WINDOW_S -> giving-up, audit
  - Opt-in strict (ModuleSpec.watch=True)
  - Respecte api_managed=False (hub jamais touche)
  - Feature flag global enable_watcher (config backend)
  - Graceful shutdown sur stop_event
  - Audit JSONL : sandbox/audit/watcher.log
  - Thread-safe : instance unique (Watcher.is_running()).

USAGE :
    # Dans un process :
    w = Watcher(poll_interval_s=5.0)
    await w.start()   # demarre la boucle (lance en task)
    await w.stop()    # arret gracieux

    # Standalone (daemon) :
    python tools/nokido_watcher.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("nokido.hub.watcher")

ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_DIR = ROOT / "sandbox" / "audit"
AUDIT_LOG = AUDIT_DIR / "watcher.log"


# Defaults (surchargeables via __init__)
DEFAULT_POLL_INTERVAL_S = 5.0
DEFAULT_BACKOFF_START_S = 1.0
DEFAULT_BACKOFF_MAX_S = 60.0
DEFAULT_MAX_RESTARTS = 5  # dans WINDOW_S -> circuit-breaker
DEFAULT_WINDOW_S = 600  # 10 min
DEFAULT_HEALTH_TIMEOUT_S = 2.0


@dataclass
class ModuleState:
    """Etat runtime du watcher pour un module donne."""

    key: str
    # Historique des timestamps de restart (pour le circuit-breaker)
    restart_history: deque = field(default_factory=lambda: deque(maxlen=50))
    # Temps a attendre avant le prochain restart (backoff en cours)
    current_backoff_s: float = DEFAULT_BACKOFF_START_S
    # Dernier timestamp ou un restart a ete tente
    last_restart_attempt: float = 0.0
    # Circuit-breaker : si True, on ne redemarre plus jusqu a un reset manuel
    circuit_open: bool = False
    # Pour debug
    total_restarts: int = 0


def _ensure_dirs() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _audit(action: str, module: str, extra: Optional[dict] = None) -> None:
    try:
        _ensure_dirs()
        line = json.dumps(
            {
                "ts": int(time.time()),
                "action": action,
                "module": module,
                "extra": extra or {},
            },
            ensure_ascii=False,
        )
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        log.warning("watcher audit failed: %s", e)


class Watcher:
    """Watcher singleton avec boucle async."""

    _instance: "Optional[Watcher]" = None

    def __init__(
        self,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        backoff_start_s: float = DEFAULT_BACKOFF_START_S,
        backoff_max_s: float = DEFAULT_BACKOFF_MAX_S,
        max_restarts: int = DEFAULT_MAX_RESTARTS,
        window_s: int = DEFAULT_WINDOW_S,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
    ) -> None:
        self.poll_interval_s = poll_interval_s
        self.backoff_start_s = backoff_start_s
        self.backoff_max_s = backoff_max_s
        self.max_restarts = max_restarts
        self.window_s = window_s
        self.health_timeout_s = health_timeout_s
        self._states: dict[str, ModuleState] = {}
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------
    @classmethod
    def instance(cls) -> "Watcher":
        if cls._instance is None:
            cls._instance = Watcher()
        return cls._instance

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())
        _audit(
            "watcher.start",
            "_self_",
            {
                "poll_interval_s": self.poll_interval_s,
                "max_restarts": self.max_restarts,
                "window_s": self.window_s,
            },
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=self.poll_interval_s + 2)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None
        _audit("watcher.stop", "_self_")

    # ----------------------------------------------------------------
    # Circuit-breaker helpers
    # ----------------------------------------------------------------
    def _get_state(self, mod: str) -> ModuleState:
        if mod not in self._states:
            self._states[mod] = ModuleState(key=mod)
        return self._states[mod]

    def _prune_history(self, st: ModuleState) -> None:
        """Retire les timestamps hors-fenetre."""
        cutoff = time.time() - self.window_s
        while st.restart_history and st.restart_history[0] < cutoff:
            st.restart_history.popleft()

    def _check_circuit(self, st: ModuleState) -> bool:
        """Retourne True si le circuit est OK (on peut restart)."""
        if st.circuit_open:
            return False
        self._prune_history(st)
        if len(st.restart_history) >= self.max_restarts:
            st.circuit_open = True
            _audit(
                "watcher.circuit_open",
                st.key,
                {
                    "total_in_window": len(st.restart_history),
                    "window_s": self.window_s,
                    "total_restarts_ever": st.total_restarts,
                },
            )
            log.warning(
                "circuit open for module %s (%d restarts in %ds)", st.key, len(st.restart_history), self.window_s
            )
            return False
        return True

    def reset_circuit(self, mod: str) -> bool:
        """Re-arme le circuit-breaker (appelable par API admin)."""
        st = self._states.get(mod)
        if not st or not st.circuit_open:
            return False
        st.circuit_open = False
        st.restart_history.clear()
        st.current_backoff_s = self.backoff_start_s
        _audit("watcher.circuit_reset", mod)
        return True

    def _should_skip_by_backoff(self, st: ModuleState) -> bool:
        """Si le backoff courant n est pas encore ecoule, on skip ce tour."""
        if st.last_restart_attempt == 0.0:
            return False
        elapsed = time.time() - st.last_restart_attempt
        return elapsed < st.current_backoff_s

    # ----------------------------------------------------------------
    # Health check HTTP (optionnel)
    # ----------------------------------------------------------------
    async def _health_ok(self, url: str) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self.health_timeout_s) as c:
                r = await c.get(url, follow_redirects=False)
                # >=500 = down, <500 = up (y compris 401/403/404)
                return r.status_code < 500
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
        except Exception:
            return False

    # ----------------------------------------------------------------
    # Core decision : un module a-t-il besoin d etre relance ?
    # ----------------------------------------------------------------
    async def _needs_restart(self, spec, status_info: dict) -> tuple[bool, str]:
        """Retourne (needs_restart, raison)."""
        st = status_info.get("status")
        if st != "running":
            return True, f"status={st}"
        # Si running, on peut quand meme tester le health endpoint
        hu = getattr(spec, "health_url", None)
        if hu:
            ok = await self._health_ok(hu)
            if not ok:
                return True, f"health KO ({hu})"
        return False, ""

    # ----------------------------------------------------------------
    # Loop
    # ----------------------------------------------------------------
    async def _loop(self) -> None:
        # LAZY import pour eviter circulaire
        from app.web_hub.launcher import MODULES, status, start
        from app.web_hub.config import load as cfg_load

        log.info("watcher loop started (poll=%.1fs)", self.poll_interval_s)
        try:
            while not self._stop_event.is_set():
                # Feature flag global : enable_watcher
                try:
                    cfg = await cfg_load()
                    if not cfg.get("enable_watcher", False):
                        # Off -> poll quand meme mais ne fait rien
                        await self._sleep_or_stop(self.poll_interval_s)
                        continue
                except Exception:
                    pass

                for key, spec in MODULES.items():
                    if self._stop_event.is_set():
                        break
                    if not getattr(spec, "watch", False):
                        continue
                    if not spec.api_managed:
                        # Securite : on ne restart JAMAIS un module cli-only (hub)
                        continue

                    st_obj = self._get_state(key)
                    if not self._check_circuit(st_obj):
                        continue
                    if self._should_skip_by_backoff(st_obj):
                        continue

                    try:
                        st_info = status(key)
                        needs, reason = await self._needs_restart(spec, st_info)
                    except Exception as e:  # noqa: BLE001
                        log.warning("watcher status failed for %s: %s", key, e)
                        continue

                    if not needs:
                        # tout va bien -> reset backoff (decay lineaire)
                        if st_obj.current_backoff_s > self.backoff_start_s:
                            st_obj.current_backoff_s = max(
                                self.backoff_start_s,
                                st_obj.current_backoff_s / 2,
                            )
                        continue

                    # Restart
                    st_obj.last_restart_attempt = time.time()
                    st_obj.restart_history.append(st_obj.last_restart_attempt)
                    st_obj.total_restarts += 1
                    _audit(
                        "watcher.restart_attempt",
                        key,
                        {
                            "reason": reason,
                            "backoff_s": st_obj.current_backoff_s,
                            "in_window": len(st_obj.restart_history),
                        },
                    )
                    log.info("watcher: restarting %s (%s, backoff=%.1fs)", key, reason, st_obj.current_backoff_s)
                    try:
                        r = await start(key, subject="watcher")
                        ok = r.get("status") == "running"
                        _audit(
                            "watcher.restart_result",
                            key,
                            {
                                "ok": ok,
                                "action": r.get("action"),
                            },
                        )
                        if not ok:
                            # double le backoff
                            st_obj.current_backoff_s = min(
                                self.backoff_max_s,
                                st_obj.current_backoff_s * 2,
                            )
                        else:
                            # reset progressif
                            st_obj.current_backoff_s = self.backoff_start_s
                    except Exception as e:  # noqa: BLE001
                        log.warning("watcher restart exception for %s: %s", key, e)
                        st_obj.current_backoff_s = min(
                            self.backoff_max_s,
                            st_obj.current_backoff_s * 2,
                        )

                    # Cap circuit
                    self._check_circuit(st_obj)

                await self._sleep_or_stop(self.poll_interval_s)
        except asyncio.CancelledError:
            pass
        finally:
            log.info("watcher loop stopped")

    async def _sleep_or_stop(self, seconds: float) -> None:
        """Sleep interruptible : rend la main vite sur stop()."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # ----------------------------------------------------------------
    # Introspection (pour API)
    # ----------------------------------------------------------------
    def snapshot(self) -> dict:
        """Etat courant pour introspection."""
        return {
            "running": self.is_running(),
            "poll_interval_s": self.poll_interval_s,
            "max_restarts": self.max_restarts,
            "window_s": self.window_s,
            "states": [
                {
                    "module": s.key,
                    "circuit_open": s.circuit_open,
                    "current_backoff_s": s.current_backoff_s,
                    "last_restart_attempt": s.last_restart_attempt,
                    "total_restarts": s.total_restarts,
                    "restarts_in_window": len(s.restart_history),
                }
                for s in self._states.values()
            ],
        }


# -------- Helpers NR --------
def _reset_for_tests() -> None:
    Watcher._instance = None


__all__ = [
    "Watcher",
    "ModuleState",
    "AUDIT_LOG",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_MAX_RESTARTS",
    "DEFAULT_WINDOW_S",
    "_reset_for_tests",
]
