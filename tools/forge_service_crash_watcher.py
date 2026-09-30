"""forge_service_crash_watcher.py — Subscribe Windows Service Control Manager events
+ log critical_events kind=service_crash quand un service Nokido* crashe.

Lit Event Log System (sources : Service Control Manager) via wevtutil query.
Polling 60s. Si nouvel event ID 7031 (crashed) ou 7034 (terminated unexpectedly)
sur un service Nokido*, persist critical_event.

Daemon : ecrit heartbeat sandbox/service_crash_watcher.heartbeat.
Restart via NSSM LaForge-ServiceCrashWatcher.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
HEARTBEAT = SANDBOX / "service_crash_watcher.heartbeat"
INTERVAL_S = 60

logger = logging.getLogger("svc_crash_watcher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_STOP = False
_LAST_RECORD_ID = 0  # only events after this are new

# --- crash-loop detection (ferme la boucle log->action) ---
# service_crash etait ecrit mais jamais consomme -> crashes silencieux (285 en 1j).
# On compte les crashes d'un meme service dans une fenetre glissante (event-time,
# donc robuste au rescan EventLog apres restart du watcher) et on emet un event
# CRITIQUE + signal hormonal des qu'un seuil est franchi. On NE tue PAS le service
# (admin requis, conflit de port = decision humaine) : on signale fort.
CRASH_LOOP_THRESHOLD = 4      # crashes d'un meme service...
CRASH_LOOP_WINDOW_S = 600     # ...dans cette fenetre => crash-loop
ALERT_COOLDOWN_S = 600        # au plus une alerte par service par fenetre
_crash_times: dict[str, list[float]] = {}  # service -> [epochs crashes recents]
_last_alert: dict[str, float] = {}         # service -> ts derniere alerte


def _ts():
    return datetime.now(UTC).isoformat()


def _heartbeat(state: dict):
    SANDBOX.mkdir(exist_ok=True)
    HEARTBEAT.write_text(
        json.dumps({"ts": _ts(), "pid": os.getpid(), **state}, indent=2),
        encoding="utf-8",
    )


def _signal_handler(sig, frame):
    global _STOP
    _STOP = True
    logger.info(f"signal {sig} received")


def _query_crash_events(last_record_id: int = 0) -> list[dict]:
    """Query Windows Event Log for SCM crash events (7031/7034) on Nokido*.

    Use PowerShell Get-WinEvent (more reliable XML output than wevtutil).
    """
    ps_script = f"""
$ErrorActionPreference='SilentlyContinue'
Get-WinEvent -LogName System -MaxEvents 500 |
  Where-Object {{ ($_.Id -eq 7031 -or $_.Id -eq 7034) -and $_.RecordId -gt {last_record_id} }} |
  ForEach-Object {{
    $svc = if ($_.Properties.Count -gt 0) {{ $_.Properties[0].Value }} else {{ '' }}
    if ($svc -like '*Nokido*' -or $svc -like '*nokido*') {{
      [PSCustomObject]@{{
        record_id = $_.RecordId
        service = $svc
        event_id = $_.Id
        time = $_.TimeCreated.ToString('o')
      }} | ConvertTo-Json -Compress
    }}
  }}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30,
        errors="replace")
        if result.returncode != 0:
            logger.warning(f"powershell err: {result.stderr[:200]}")
            return []
        import json as _j

        events = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                evt = _j.loads(line)
                if "record_id" in evt and "service" in evt:
                    evt["record_id"] = int(evt["record_id"])
                    events.append(evt)
            except Exception:
                pass
        return events
    except Exception as e:
        logger.warning(f"query crash events fail: {e}")
        return []


def _evt_epoch(evt: dict) -> float:
    """Epoch du crash depuis le champ ISO 'time' de l'event (fallback now)."""
    t = evt.get("time")
    if t:
        try:
            return datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    return time.time()


def _check_crash_loop(service: str, crash_epoch: float, persist_fn) -> None:
    """N crashes d'un meme service dans la fenetre -> event critique + cortisol.

    Ferme la boucle: avant, service_crash etait ecrit mais jamais consomme.
    Ne tue PAS le service (admin requis) : signale fort pour que l'humain et
    l'autonomic (homeostasis/coagulation via hormones) reagissent.
    """
    now = time.time()
    hist = _crash_times.setdefault(service, [])
    hist.append(crash_epoch)
    hist[:] = [t for t in hist if now - t <= CRASH_LOOP_WINDOW_S]  # purge hors fenetre
    if len(hist) < CRASH_LOOP_THRESHOLD:
        return
    if now - _last_alert.get(service, 0.0) < ALERT_COOLDOWN_S:  # throttle
        return
    _last_alert[service] = now
    count = len(hist)
    logger.error(
        "CRASH-LOOP: %s a crashe %dx en %ds -- alerte critique emise",
        service, count, CRASH_LOOP_WINDOW_S,
    )
    # 1) event CRITIQUE distinct (surface via unprocessed()/observatory/sentinel boot)
    try:
        persist_fn(
            "crash_loop_detected",
            "critical",
            {
                "service": service,
                "crash_count": count,
                "window_s": CRASH_LOOP_WINDOW_S,
                "hint": "service hors superviseur ou conflit de port -- verifier NSSM / services.toml",
            },
        )
    except Exception as e:
        logger.error("persist crash_loop_detected fail: %s", e)
    # 2) signal autonomic (cortisol) best-effort -- ne jamais casser le watcher
    try:
        from nokido_agent.app.forge_hormones import release  # type: ignore

        release("cortisol", 0.85, {"reason": "crash_loop", "service": service, "count": count})
    except Exception:
        pass


def _log_crash(events: list[dict]):
    """Persist critical_event kind=service_crash for each event + detect crash-loop."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_critical_events import persist

        for evt in events:
            persist("service_crash", "error", evt)
            logger.warning(f"service_crash: {evt['service']} (rid={evt['record_id']})")
            try:
                _check_crash_loop(evt.get("service", "?"), _evt_epoch(evt), persist)
            except Exception as e:
                logger.error(f"crash-loop check fail: {e}")
        return True
    except Exception as e:
        logger.error(f"persist fail: {e}")
        return False


def main():
    global _LAST_RECORD_ID
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info(f"service_crash_watcher UP, interval={INTERVAL_S}s")
    iter_count = 0
    total_events = 0

    while not _STOP:
        iter_count += 1
        events = _query_crash_events(_LAST_RECORD_ID)
        if events:
            _log_crash(events)
            total_events += len(events)
            max_rid = max(e["record_id"] for e in events)
            if max_rid > _LAST_RECORD_ID:
                _LAST_RECORD_ID = max_rid
        _heartbeat(
            {
                "iter": iter_count,
                "total_events_logged": total_events,
                "last_record_id": _LAST_RECORD_ID,
                "health": "ok",
            }
        )
        for _ in range(INTERVAL_S):
            if _STOP:
                break
            time.sleep(1)

    logger.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
