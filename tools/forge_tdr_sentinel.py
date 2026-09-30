"""
forge_tdr_sentinel.py — TDR sentinel event-driven Win32 (Phase 12 refactor).

Avant (Phase 7a) : polling wevtutil toutes 2s.
Maintenant (Phase 12) : pywin32 win32evtlog.EvtSubscribe push natif.
Reaction immediate (~50ms latence) au lieu de 2s.

Pattern :
  - Subscription Win32 EventLog System filtre EventID 4101 OR 4099
    (Display driver recovery, TDR).
  - Callback s'execute dans thread Win32 worker (NON-Python). On y enqueue
    juste l'event dans queue.Queue (thread-safe). Aucun log/HTTP dans
    le callback (risque GIL/asyncio deadlock).
  - Main thread consume la queue avec timeout court (= keep-alive heartbeat).
  - Sur event nouveau : SIGSTOP services GPU-touching via POST hub.

Fallback automatique vers polling wevtutil si pywin32 absent ou
EvtSubscribe fail. Best of both worlds.

Heartbeat conforme schema Phase 3, tier=fast.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logging.basicConfig(
    format="%(asctime)s [tdr_sentinel] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("tdr_sentinel")

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = ROOT / "sandbox" / "tdr_sentinel.heartbeat"

HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766")
QUIESCE_S = float(os.environ.get("TDR_SENTINEL_QUIESCE_S", "60.0"))
HEARTBEAT_S = float(os.environ.get("TDR_SENTINEL_HEARTBEAT_S", "10.0"))
HTTP_TIMEOUT_S = 5.0
POLL_FALLBACK_TICK_S = 2.0  # si EvtSubscribe indisponible

GPU_TOUCHING_SERVICES = [
    "NokidoOllama",
    "NokidoBrainWorkerRust",
    "NokidoLlamaNative",
    "NokidoLlamaEmbed",
    "NokidoLlamaReranker",
    "NokidoLlamaRouter",
]

# Queue partagée entre thread callback Win32 et main consumer thread.
_event_queue: queue.Queue = queue.Queue(maxsize=500)
# Garder reference au subscription handle pour eviter GC qui tue le callback.
_subscription_handle = None
_callback_ref = None

# Shared state main thread
_state_lock = threading.Lock()
_state = {
    "iter": 0,
    "tdrs_seen": 0,
    "last_tdr_ts": 0.0,
    "paused_services": [],
    "resume_at": 0.0,
    "mode": "init",  # "evtsub" | "poll_fallback"
    "last_event_handle_ts": 0.0,
}


def _hub_post(path: str) -> bool:
    url = HUB_URL.rstrip("/") + path
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        log.warning("hub POST %s failed: %s", path, exc)
        return False


def _sleep_all_gpu() -> list[str]:
    paused: list[str] = []
    for svc in GPU_TOUCHING_SERVICES:
        if _hub_post(f"/api/services/stop/{svc}"):
            paused.append(svc)
            log.info("paused %s", svc)
    return paused


def _start_all_gpu(paused: list[str]) -> list[str]:
    restored: list[str] = []
    for svc in paused:
        if _hub_post(f"/api/services/start/{svc}"):
            restored.append(svc)
            log.info("restored %s", svc)
    return restored


def _write_heartbeat(health: str, extra: dict | None = None) -> None:
    with _state_lock:
        _state["iter"] += 1
        snap = {
            "service": "NokidoTdrSentinel",
            "ts": time.time(),
            "iter": _state["iter"],
            "health": health,
            "stats": {
                "mode": _state["mode"],
                "tdrs_seen": _state["tdrs_seen"],
                "last_tdr_ts": _state["last_tdr_ts"],
                "services_paused": list(_state["paused_services"]),
                "resume_pending_until": _state["resume_at"],
                "last_event_handle_age_s": (
                    round(time.time() - _state["last_event_handle_ts"], 1)
                    if _state["last_event_handle_ts"]
                    else None
                ),
                **(extra or {}),
            },
        }
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le `pid`
    # absent ici. La charge `snap` est passee telle quelle — elle porte deja son
    # propre `ts` NUMERIQUE, que le superviseur prefere (`supervisor.ts` ne lit `ts`
    # que s'il est un nombre, sinon il retombe sur le mtime).
    # `app/` n'est PAS sur le sys.path de ce module. La seule insertion presente
    # vit dans `_handle_tdr_event`, qui ne s'execute QUE lors d'un TDR — evenement
    # rare, donc jamais atteinte avant le premier pouls. Sans cette amorce, le
    # sentinelle mourait en `ModuleNotFoundError` des le boot (mesure 2026-09-05,
    # pouls fige a 02:59, service « DEGRADE » au demarrage suivant). C'est le
    # reflexe anti-cascade TDR -> BSOD 0x119 : sa mort silencieuse coute cher.
    _app = str(Path(__file__).resolve().parent.parent / "app")
    if _app not in sys.path:
        sys.path.insert(0, _app)
    from nokido_agent.app.forge_heartbeat import beat_daemon

    if not beat_daemon("tdr_sentinel", **snap):
        log.error("hb write fail (beat_daemon)")


def _handle_tdr_event(source: str) -> None:
    """Process 1 TDR event detection. Called by main consumer thread."""
    now = time.time()
    with _state_lock:
        _state["tdrs_seen"] += 1
        _state["last_tdr_ts"] = now
        already_paused = bool(_state["paused_services"])
        _state["resume_at"] = now + QUIESCE_S
        _state["last_event_handle_ts"] = now
    log.warning(
        "TDR detected via %s (total=%d) — pausing GPU services", source, _state["tdrs_seen"]
    )
    if not already_paused:
        paused = _sleep_all_gpu()
        with _state_lock:
            _state["paused_services"] = paused
    _write_heartbeat("crit", extra={"trigger": f"event_{source}"})

    # Persiste l'event en SQLite append-only — survit restart hub/supervisor.
    # Cable 2026-05-25 suite a investigation : forge_critical_events.db etait
    # vide car aucun writer ne call persist(). TDR = signal critique
    # (driver Radeon crash, peut precipiter BSOD 0x119) qui doit survivre.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_critical_events import persist as _ce_persist  # type: ignore

        _ce_persist(
            "tdr_triggered",
            "critical",
            {
                "source": source,
                "tdrs_seen_total": _state["tdrs_seen"],
                "services_paused": list(_state["paused_services"]),
                "quiesce_until": _state["resume_at"],
            },
        )
    except Exception as _ce_exc:
        log.warning("persist critical_event failed (non-fatal): %s", _ce_exc)


# ──────────────────────────────────────────────────────────────────────────
# EvtSubscribe path (event-driven)
# ──────────────────────────────────────────────────────────────────────────


def _try_setup_evtsubscribe() -> bool:
    global _subscription_handle, _callback_ref
    try:
        import win32evtlog  # type: ignore
    except ImportError:
        log.warning("pywin32 win32evtlog absent — fallback polling wevtutil")
        return False

    # Callback s'execute dans thread Win32 worker. JAMAIS de log/HTTP ici.
    # On enqueue juste un marker. Le consumer main thread gere la suite.
    def _evt_callback(action, context, event_handle):
        try:
            if action == win32evtlog.EvtSubscribeActionDeliver:
                # Push minimal payload (l'event suffit, on parsera pas le XML
                # ici car ca demande WIN32 EvtRender qui peut bloquer).
                try:
                    _event_queue.put_nowait({"src": "evtsub", "ts": time.time()})
                except queue.Full:
                    pass  # drop event, on est sature
        except Exception:
            pass  # callback NE DOIT JAMAIS lever
        return 0

    _callback_ref = _evt_callback  # garde reference, sinon GC tue callback
    query = "*[System[(EventID=4101 or EventID=4099)]]"
    try:
        _subscription_handle = win32evtlog.EvtSubscribe(
            "System",
            win32evtlog.EvtSubscribeToFutureEvents,
            None,  # SignalEvent = None (callback mode)
            Callback=_evt_callback,
            Context=None,
            Query=query,
        )
        log.info("EvtSubscribe OK — event-driven mode active")
        with _state_lock:
            _state["mode"] = "evtsub"
        return True
    except Exception as exc:
        log.warning("EvtSubscribe failed (%s) — fallback polling", exc)
        return False


# ──────────────────────────────────────────────────────────────────────────
# Polling fallback (Phase 7a comportement)
# ──────────────────────────────────────────────────────────────────────────


def _wevtutil_count_recent(window_s: float) -> int:
    window_ms = int(window_s * 1000)
    xpath = (
        "*[System["
        f"(EventID=4101 or EventID=4099) and "
        f"TimeCreated[timediff(@SystemTime) <= {window_ms}]"
        "]]"
    )
    try:
        r = subprocess.run(
            ["wevtutil", "qe", "System", f"/q:{xpath}", "/c:50", "/f:xml"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4.0,
        errors="replace")
        if r.returncode != 0:
            return 0
        return r.stdout.count("<Event ")
    except Exception:
        return 0


def _poll_fallback_loop() -> None:
    last_count = 0
    while True:
        try:
            window = POLL_FALLBACK_TICK_S * 3
            count = _wevtutil_count_recent(window)
            new = max(0, count - last_count)
            last_count = count
            if new > 0:
                for _ in range(new):
                    _event_queue.put_nowait({"src": "poll", "ts": time.time()})
        except Exception:
            pass
        time.sleep(POLL_FALLBACK_TICK_S)


# ──────────────────────────────────────────────────────────────────────────
# Main consumer + quiesce timer
# ──────────────────────────────────────────────────────────────────────────


def main() -> int:
    log.info("tdr_sentinel start quiesce=%.0fs hub=%s", QUIESCE_S, HUB_URL)

    use_evtsub = _try_setup_evtsubscribe()
    if not use_evtsub:
        with _state_lock:
            _state["mode"] = "poll_fallback"
        threading.Thread(
            target=_poll_fallback_loop,
            name="tdr_poll_fb",
            daemon=True,
        ).start()
        log.info("polling fallback thread started (tick %.1fs)", POLL_FALLBACK_TICK_S)

    # Heartbeat ok initial
    _write_heartbeat("ok", extra={"boot": True})

    while True:
        try:
            try:
                evt = _event_queue.get(timeout=HEARTBEAT_S)
                _handle_tdr_event(evt.get("src", "?"))
            except queue.Empty:
                # No event in HEARTBEAT_S — emit lifesign + check quiesce
                with _state_lock:
                    paused = list(_state["paused_services"])
                    resume_at = _state["resume_at"]
                if paused and time.time() >= resume_at:
                    restored = _start_all_gpu(paused)
                    with _state_lock:
                        _state["paused_services"] = []
                        _state["resume_at"] = 0.0
                    log.info("quiesce ended — restored %d services", len(restored))
                    _write_heartbeat("degraded", extra={"post_quiesce_restored": restored})
                else:
                    health = "degraded" if paused else "ok"
                    _write_heartbeat(health, extra={"keepalive": True})
        except Exception as exc:
            log.error("main loop err: %s", exc)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("SIGINT — exit")
        sys.exit(0)
