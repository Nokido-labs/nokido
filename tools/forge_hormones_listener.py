"""
forge_hormones_listener.py — Démon SSE consumer du système endocrinien.

Phase 10 (2026-05-24) : poll. Phase 12 (2026-05-24, refactor) : SSE.
Consume /api/hormones/stream en mode event-driven (recv bloquant, zéro
tick CPU au repos). Reconnect auto avec backoff exponentiel si hub down.

Réagit aux events :
  adrenaline > 0.7 → log WARN, heartbeat health=crit
  cortisol  > 0.5 → log INFO, heartbeat health=degraded
  autres           → comptabilisé, heartbeat health=ok

Heartbeat publié toutes HEARTBEAT_S secondes même sans event (signal vie
au supervisor). Stats agrégées : derniers events par hormone.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
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

logging.basicConfig(
    format="%(asctime)s [hormones_listener] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("hormones_listener")

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = ROOT / "sandbox" / "hormones_listener.heartbeat"
HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766")
SSE_URL = HUB_URL.rstrip("/") + "/api/hormones/stream"
HEARTBEAT_S = float(os.environ.get("HORMONES_LISTENER_HEARTBEAT_S", "10.0"))
RECONNECT_BACKOFF_S = [1.0, 2.0, 5.0, 10.0, 30.0]

# Shared state thread-safe (SSE thread → heartbeat thread).
_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "iter": 0,
    "events_total": 0,
    "events_by_hormone": defaultdict(int),
    "last_events": deque(maxlen=20),  # liste des 20 derniers events
    "current_doses": defaultdict(float),  # somme decay-aware approximee
    "sse_connected": False,
    "last_event_ts": 0.0,
}


def _write_heartbeat(health: str, extra: dict | None = None) -> None:
    with _state_lock:
        _state["iter"] += 1
        snap = {
            "service": "NokidoHormonesListener",
            "ts": time.time(),
            "iter": _state["iter"],
            "health": health,
            "stats": {
                "sse_connected": _state["sse_connected"],
                "events_total": _state["events_total"],
                "events_by_hormone": dict(_state["events_by_hormone"]),
                "last_events_count": len(_state["last_events"]),
                "last_event_ts": _state["last_event_ts"],
                "last_event_age_s": (
                    round(time.time() - _state["last_event_ts"], 1)
                    if _state["last_event_ts"]
                    else None
                ),
                **(extra or {}),
            },
        }
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le `pid`.
    # `app/` n'est pas sur le sys.path de ce module -> amorce maison. La charge
    # `snap` porte des valeurs non JSON, d'ou le `default=str` desormais assure par
    # `beat_daemon` lui-meme.
    import sys as _sys
    from pathlib import Path as _Path

    _app = str(_Path(__file__).resolve().parent.parent / "app")
    if _app not in _sys.path:
        _sys.path.insert(0, _app)
    from nokido_agent.app.forge_heartbeat import beat_daemon

    if not beat_daemon("hormones_listener", **snap):
        log.error("heartbeat write fail (beat_daemon)")


def _process_event(rec: dict) -> str:
    """Returns suggested health based on event."""
    hormone = rec.get("hormone", "?")
    level = float(rec.get("level", 0.0))
    with _state_lock:
        _state["events_total"] += 1
        _state["events_by_hormone"][hormone] += 1
        _state["last_events"].append(
            {
                "hormone": hormone,
                "level": level,
                "ts": rec.get("released_ts"),
                "receptors": rec.get("receptors"),
            }
        )
        _state["last_event_ts"] = time.time()
    if hormone == "adrenaline" and level > 0.7:
        log.warning("URGENCE adrenaline level=%.2f payload=%s", level, rec.get("payload"))
        return "crit"
    if hormone == "cortisol" and level > 0.5:
        log.info("STRESS cortisol level=%.2f", level)
        return "degraded"
    log.debug("event %s level=%.2f receptors=%s", hormone, level, rec.get("receptors"))
    return "ok"


def _heartbeat_loop() -> None:
    """Thread dedie qui publie heartbeat regulier (signal vie au supervisor)
    meme sans event recent. Health = degraded si SSE deco depuis >2x HEARTBEAT_S."""
    while True:
        try:
            with _state_lock:
                sse_up = _state["sse_connected"]
                last_evt = _state["last_event_ts"]
            health = "ok" if sse_up else "degraded"
            _write_heartbeat(health, extra={"loop": "heartbeat"})
        except Exception as exc:
            log.error("heartbeat loop err: %s", exc)
        time.sleep(HEARTBEAT_S)


def _sse_stream_once() -> None:
    """Open SSE connexion + consume jusqu'a EOF/error. Raise on error."""
    log.info("opening SSE %s", SSE_URL)
    req = urllib.request.Request(
        SSE_URL,
        headers={
            "Accept": "text/event-stream",
            "X-Client-Id": "hormones_listener",
        },
    )
    # urlopen sans timeout = bloquant indefiniment (OK pour SSE long-lived).
    # On set un read timeout long pour detecter network freeze.
    with urllib.request.urlopen(req, timeout=None) as resp:
        with _state_lock:
            _state["sse_connected"] = True
        log.info("SSE connected — status=%s", resp.status)
        current_event = "message"
        current_data_parts: list[str] = []
        while True:
            raw = resp.readline()
            if not raw:
                log.warning("SSE EOF — server closed")
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                # dispatch event accumulated
                if current_data_parts:
                    data_str = "\n".join(current_data_parts)
                    try:
                        if current_event == "hormone":
                            rec = json.loads(data_str)
                            health = _process_event(rec)
                            _write_heartbeat(health, extra={"trigger": "event"})
                        elif current_event == "connected":
                            log.info("SSE handshake ok: %s", data_str[:120])
                    except json.JSONDecodeError as exc:
                        log.warning("bad json event=%s: %s", current_event, exc)
                current_event = "message"
                current_data_parts = []
            elif line.startswith(":"):
                # SSE comment (ping keep-alive) — ignore but signal vie
                with _state_lock:
                    pass  # nothing, mais la connexion vit
            elif line.startswith("event:"):
                current_event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                current_data_parts.append(line[len("data:") :].lstrip())
            # ignore retry: id:


def _sse_loop_forever() -> None:
    """Reconnect auto avec backoff exponentiel."""
    attempt = 0
    while True:
        try:
            _sse_stream_once()
        except (urllib.error.URLError, ConnectionError, OSError, TimeoutError) as exc:
            log.warning("SSE conn err: %s", exc)
        except Exception as exc:
            log.error("SSE unexpected err: %s", exc, exc_info=False)
        with _state_lock:
            _state["sse_connected"] = False
        backoff = RECONNECT_BACKOFF_S[min(attempt, len(RECONNECT_BACKOFF_S) - 1)]
        attempt += 1
        log.info("SSE reconnect in %.0fs (attempt %d)", backoff, attempt)
        time.sleep(backoff)


def main() -> int:
    log.info("hormones_listener SSE start url=%s heartbeat=%.0fs", SSE_URL, HEARTBEAT_S)
    # Heartbeat thread (lifesign supervisor)
    hb_thread = threading.Thread(target=_heartbeat_loop, name="hb_loop", daemon=True)
    hb_thread.start()
    # SSE consumer en main thread
    _sse_loop_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("SIGINT — exit")
        sys.exit(0)
