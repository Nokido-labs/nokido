#!/usr/bin/env python3
"""
app/forge_loop_sentinel.py — Sentinelle de lag d'event-loop.

Équivalent SOUVERAIN de py-spy, mais IN-PROCESS : zéro attach, zéro élévation,
zéro OpenProcess (le sandbox Nokido ne peut pas s'attacher à un process hôte).

Une coroutine mesure le retard réel de la boucle asyncio. Quand un wrapper
BLOQUANT (requests.post synchrone, time.sleep, appel C sync dans une route
`async def`) gèle la boucle, le lag dépasse le seuil → log WARNING + dump
`faulthandler` de TOUTES les stacks : la stack du thread principal pointe le
coupable. C'est la traque des "rogue wrappers" (cause racine de saturation hub)
en PROD, sans py-spy ni privilège.

Wire (hub) — dans `main()` async, après `_build_app()` :
    from forge_loop_sentinel import start as _ls_start
    _ls_start(threshold_ms=300)

CLI: python forge_loop_sentinel.py --selftest
"""
from __future__ import annotations

import asyncio
import faulthandler
import logging
import os
import threading
import time
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
_LOG = ROOT / "logs" / "loop_lag.log"


def _mark_dump(lag_ms: float) -> None:
    """Écrit un marqueur DATÉ à côté du dump faulthandler.

    Les stacks sont écrites par `faulthandler` en C : on ne peut pas préfixer
    ses lignes. Or ce fichier est le dump le plus utile du corps — MESURE
    2026-07-26 : il nommait `_sample_gpu_win32` bloqué dans
    `subprocess.communicate()` à l'instant d'un gel machine, et il a fallu
    corréler à la main avec l'Observateur Windows faute d'y lire une date.
    22 Mo de stacks non datées.

    On encadre donc chaque dump d'un marqueur daté (le dump précède la détection,
    le marqueur le suit d'une fraction de seconde). Best-effort, jamais fatal :
    une sentinelle qui casse sur son propre journal ne surveille plus rien.
    """
    try:
        import sys as _s

        _app = str(ROOT / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_timecode import now_iso

        ts = now_iso()
    except Exception:  # noqa: BLE001
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        ts = _dt.now(tz=_tz.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("--- [loop-lag] %s lag=%.0fms (dump ci-dessus) ---\n" % (ts, lag_ms))
    except Exception:  # noqa: BLE001
        pass
_DEFAULT_THRESHOLD_MS = 300.0
_MIN_DUMP_INTERVAL = 10.0  # anti-spam : 1 dump faulthandler / 10s max
_MAX_REAL_LAG_S = 30.0     # au-delà = suspend machine / saut horloge monotonic (PAS un blocage wrapper, qui est < ~10s) -> faux positif ignoré

logger = logging.getLogger("Nokido.LoopSentinel")

_last_dump = 0.0
_events = 0
_max_lag_ms = 0.0


def _record_lag(lag_ms: float) -> None:
    global _events, _max_lag_ms
    _events += 1
    _max_lag_ms = max(_max_lag_ms, lag_ms)
    logger.warning("[loop-lag] event loop bloqué %.0fms (stack coupable -> %s)", lag_ms, _LOG.name)
    _mark_dump(lag_ms)


async def _monitor(threshold_ms: float, interval: float) -> None:
    """Watchdog faulthandler : ARME dump_traceback_later avant chaque tick. Si la
    loop ne revient pas à temps (blocage), le timer fire depuis le thread
    faulthandler PENDANT le blocage -> capture la stack du COUPABLE (un dump
    post-hoc, lui, ne verrait que la sentinelle une fois la loop débloquée)."""
    thr = threshold_ms / 1000.0
    fh = None
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        fh = open(_LOG, "a", encoding="utf-8")  # fd persistant requis par faulthandler
    except Exception:
        fh = None
    while True:
        t0 = time.monotonic()
        if fh is not None:
            try:
                faulthandler.dump_traceback_later(interval + thr, repeat=False, file=fh)
            except Exception:
                pass
        await asyncio.sleep(interval)
        if fh is not None:
            try:
                faulthandler.cancel_dump_traceback_later()
            except Exception:
                pass
        lag = (time.monotonic() - t0) - interval
        if lag > _MAX_REAL_LAG_S:
            # >30s = la machine a été suspendue (sleep/hibernate) ou saut d'horloge :
            # faux positif, pas un blocage de wrapper. On ignore (sinon loop_lag.log
            # se pollue de "lags" de plusieurs minutes = bruit, cf enforce_explanation).
            continue
        if lag > thr:
            if fh is not None:
                try:
                    fh.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} lag={lag * 1000:.0f}ms (stack AU-DESSUS = coupable mid-block) ===\n")
                    fh.flush()
                except Exception:
                    pass
            _record_lag(lag * 1000.0)


def start(threshold_ms: float = _DEFAULT_THRESHOLD_MS, interval: float = 0.5):
    """Lance la sentinelle DIAGNOSTIC (lag 300ms) + arme le watchdog KILL wedge
    (self-heal : os._exit si le loop gele >= LAFORGE_LOOP_KILL_S, defaut 60s ;
    opt-out =0) sur la boucle COURANTE. Le hub appelle deja start() -> les deux
    s'arment sans toucher le coeur nokido_hub.py (CRITICAL_FILE). Retourne la
    Task du monitor diagnostic."""
    try:
        _kill_s = float(os.environ.get("LAFORGE_LOOP_KILL_S", "60"))
        start_kill_watchdog(kill_after_s=_kill_s)
    except Exception:
        pass
    return asyncio.ensure_future(_monitor(threshold_ms, interval))


# ── Watchdog KILL wedge (self-heal INTERNE, thread OS independant du loop) ───────
# Le _monitor ci-dessus DIAGNOSTIQUE (dump du coupable) mais ne SOIGNE pas : c'est
# une tache async, si le loop gele elle gele avec (RCA wedge 2026-07-02 : hub fige
# ~2h, aucun self-heal -> reboot manuel). Ce watchdog vit dans un THREAD OS : il
# poke le loop via call_soon_threadsafe ; si le loop ne traite plus le callback
# depuis >= kill_after_s, il dump toutes les stacks + os._exit(1) -> le superviseur
# respawn un hub frais. Borne TOUT wedge a kill_after_s, sans dependre du watchdog
# externe (:8766 HTTP probe). Les deux se completent : interne = rapide (60s) sur
# freeze GIL-releasing ; externe (forge_service_watchdog kill-by-port) = filet sur
# freeze GIL-holding ou meme ce thread ne peut pas tourner.
_last_beat = 0.0  # monotonic ; mis a jour par le loop quand il traite le poke


def _kill_watchdog(loop, kill_after_s: float, check_every: float, fh) -> None:
    global _last_beat

    def _beat() -> None:
        global _last_beat
        _last_beat = time.monotonic()

    prev_tick = time.monotonic()
    while True:
        time.sleep(check_every)
        now = time.monotonic()
        # Grace suspend/resume : si sleep(check_every) a dure BEAUCOUP plus long
        # que demande, la machine etait en VEILLE (monotonic inclut la suspension
        # sous Windows) ; le beat n'a pas pu tourner pendant la veille -> stale
        # geant = FAUX wedge (incident 2026-07-03 : kill "gele 29580s" au resume).
        # On repart a zero : le loop a kill_after_s frais pour prouver qu'il vit ;
        # un vrai wedge pre-veille sera re-tue kill_after_s plus tard.
        if now - prev_tick > check_every * 5 + 10.0:
            _last_beat = now
        prev_tick = now
        try:
            loop.call_soon_threadsafe(_beat)  # ne s'execute QUE si le loop tourne
        except Exception:
            pass
        stale = time.monotonic() - _last_beat
        if stale >= kill_after_s:
            try:
                if fh is not None:
                    fh.write(
                        f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} WEDGE KILL : "
                        f"event-loop gele {stale:.0f}s >= {kill_after_s:.0f}s "
                        f"-> dump + os._exit(1) (superviseur respawn) ===\n"
                    )
                    fh.flush()
                    faulthandler.dump_traceback(file=fh, all_threads=True)
                    fh.flush()
            except Exception:
                pass
            try:
                logger.critical("[loop-kill] event-loop gele %.0fs -> os._exit(1) respawn", stale)
            except Exception:
                pass
            os._exit(1)


def start_kill_watchdog(kill_after_s: float = 60.0, check_every: float = 2.0):
    """Arme le self-heal wedge : thread OS qui os._exit(1) si le loop courant gele
    >= kill_after_s (le superviseur respawn). kill_after_s<=0 -> desactive
    (opt-out LAFORGE_LOOP_KILL_S=0). Retourne le Thread (ou None si off/no-loop)."""
    if kill_after_s <= 0:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    fh = None
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        fh = open(_LOG, "a", encoding="utf-8")
    except Exception:
        fh = None
    global _last_beat
    _last_beat = time.monotonic()  # amorce : evite un kill avant le 1er poke
    th = threading.Thread(
        target=_kill_watchdog,
        args=(loop, kill_after_s, check_every, fh),
        name="LoopKillWatchdog",
        daemon=True,
    )
    th.start()
    return th


def stats() -> dict:
    return {"lag_events": _events, "max_lag_ms": round(_max_lag_ms, 1), "log": str(_LOG)}


def _selftest() -> int:
    global _LOG
    logging.basicConfig(level=logging.WARNING)
    _LOG = Path("loop_lag_selftest.log")  # zone workspace (writable en sandbox)
    try:
        _LOG.unlink()
    except OSError:
        pass

    async def run():
        t = start(threshold_ms=100, interval=0.2)
        await asyncio.sleep(0.3)   # normal
        time.sleep(0.6)            # BLOQUE la loop -> dump_traceback_later fire PENDANT
        await asyncio.sleep(0.3)
        await asyncio.sleep(0.3)
        t.cancel()
        return stats()

    s = asyncio.run(run())
    cap = ""
    try:
        cap = _LOG.read_text(encoding="utf-8")
    except OSError:
        pass
    stack_captured = "File " in cap
    names_blocker = ("_selftest" in cap or "time.sleep" in cap or " in run" in cap)
    ok = s["lag_events"] >= 1 and stack_captured
    print("SELFTEST", "OK" if ok else "FAIL", {**s, "stack_captured": stack_captured, "names_blocker": names_blocker})
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
