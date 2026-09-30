#!/usr/bin/env python3
"""
tools/nokido_watcher.py - Daemon watcher auto-restart.

Tourne en process separe du hub : si le hub crashe, le watcher peut le
detecter et alerter (mais ne peut PAS redemarrer le hub par design :
api_managed=False, chicken-egg).

USAGE :
    python tools/nokido_watcher.py [--poll 5.0] [--max-restarts 5]

L arret est gracieux via Ctrl+C ou SIGTERM. Sortie rc=0.

Ne modifie PAS le comportement du hub (le watcher tournant dans le hub
est independant de celui-ci). On peut tres bien lancer les deux --
l audit JSONL est partage, les locks Python ne pas (process separe).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def run_watcher(poll: float, max_restarts: int, window_s: int) -> int:
    from app.web_hub.watcher import Watcher

    w = Watcher(
        poll_interval_s=poll,
        max_restarts=max_restarts,
        window_s=window_s,
    )
    await w.start()
    print(
        f"[watcher] started poll={poll}s max_restarts={max_restarts}/{window_s}s  (Ctrl+C to stop)"
    )

    stop_event = asyncio.Event()

    def _sigterm(*_):
        stop_event.set()

    # Sous Windows, signal.SIGTERM n est pas catchable par asyncio.
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _sigterm)
            except NotImplementedError:
                pass

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print("[watcher] stopping...")
        await w.stop()
        print("[watcher] stopped")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido watcher daemon")
    ap.add_argument("--poll", type=float, default=5.0, help="Intervalle de polling (s), defaut 5.0")
    ap.add_argument(
        "--max-restarts", type=int, default=5, help="Max restarts dans la fenetre (circuit-breaker)"
    )
    ap.add_argument(
        "--window-s", type=int, default=600, help="Fenetre du circuit-breaker (s), defaut 600"
    )
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        return asyncio.run(run_watcher(args.poll, args.max_restarts, args.window_s))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
