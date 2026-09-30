"""tools/forge_circadian_runner.py - declenche la phase circadienne courante.

A schedluler via Windows schtasks LaForge-Circadian-* (un task par phase)
ou cron Linux. Exemple Windows :

  schtasks /create /tn LaForge-Circadian-Aurore /tr "..." /sc daily /st 06:00
  schtasks /create /tn LaForge-Circadian-Jour /tr "..." /sc daily /st 09:00
  ... etc

Modes :
  --status      : rapport JSON etat circadien courant
  --fire PHASE  : execute manuellement une phase
  --auto        : detecte phase courante + fire si dette
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_circadian import (  # noqa: E402
    Phase,
    current_phase,
    fire_phase,
    load_state,
    report_status,
    save_state,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--fire", choices=[p.value for p in Phase], default=None)
    ap.add_argument(
        "--auto",
        action="store_true",
        help="detecte phase actuelle + fire si non completee depuis 20h",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.status or (not args.fire and not args.auto):
        print(json.dumps(report_status(), indent=2, default=str))
        return 0

    state = load_state()
    if args.fire:
        phase = Phase(args.fire)
        r = fire_phase(phase, state=state, dry_run=args.dry_run)
        save_state(state)
        print(json.dumps(r, indent=2, default=str))
        return 0

    if args.auto:
        phase = current_phase()
        debt = state.debt_hours(phase)
        if debt < 20:
            print(
                json.dumps(
                    {
                        "skipped": phase.value,
                        "debt_hours": debt,
                        "reason": "already completed < 20h ago",
                    },
                    indent=2,
                )
            )
            return 0
        r = fire_phase(phase, state=state, dry_run=args.dry_run)
        save_state(state)
        print(json.dumps(r, indent=2, default=str))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
