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


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
sys.path.insert(0, str(ROOT))
# 31/10 : lance par la tache planifiee Nokido-Circadian-Auto sous pythonw (aucune console) -- chaque decision --auto
# s'ecrit ici, sinon un tick qui differe ne laisse aucune trace et le declenchement est improuvable.
JOURNAL_AUTO = _RACINE_DONNEES / "logs" / "circadian_auto.jsonl"


def _tracer(decision: str, phase, raison: str, inactivite: str) -> None:
    import time as _t
    try:
        JOURNAL_AUTO.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL_AUTO, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _t.strftime("%Y-%m-%dT%H:%M:%S"), "decision": decision,
                                "phase": getattr(phase, "value", phase), "raison": raison,
                                "inactivite": inactivite}, ensure_ascii=False) + "\n")
    except OSError as e:
        print("[circadian] trace non ecrite (%s)" % type(e).__name__, file=sys.stderr)

from nokido_agent.app.forge_circadian import (  # noqa: E402
    Phase,
    current_phase,
    fire_phase,
    inactivite_mesuree,
    load_state,
    phase_a_tirer,
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
        # 31/10 (owner) : la consolidation suit l'INACTIVITE mesuree (tasks.db + RAM/CPU + homeostat), plus l'heure seule ;
        # un creneau de sommeil sous charge est differe (sauf dette > 48 h).
        from datetime import datetime as _dt
        inactif, motif_inactivite = inactivite_mesuree()
        phase, raison = phase_a_tirer(_dt.now(), state, inactif)
        if phase is None:
            _tracer("differe", current_phase(), raison, motif_inactivite)
            print(json.dumps({"skipped": current_phase().value, "reason": raison,
                              "inactivite": motif_inactivite}, indent=2))
            return 0
        _tracer("tire", phase, raison, motif_inactivite)
        print(json.dumps({"tire": phase.value, "reason": raison, "inactivite": motif_inactivite}))
        r = fire_phase(phase, state=state, dry_run=args.dry_run)
        save_state(state)
        # 31/10 : la decision seule ne prouvait rien -- NREM1 « tiree » a 19 h 21, son producteur pip-audit avait
        # rendu « hors phase » sur une stdout que personne ne lit. Le RESULTAT de chaque action s'ecrit aussi.
        _tracer("resultat", phase, _resume_resultat(r), motif_inactivite)
        print(json.dumps(r, indent=2, default=str))
        return 0

    return 0


def _resume_resultat(r: dict) -> str:
    """Une ligne par tir : soldee ou non, differees, et le premier etat lisible de chaque action (borne DITE)."""
    actions = []
    for x in r.get("results") or []:
        etat = x.get("error") or next((v for k, v in x.items() if k not in ("action", "organ")
                                       and isinstance(v, (str, bool))), "?")
        actions.append("%s=%s" % (x.get("action"), str(etat)[:80]))
    texte = "soldee=%s ; differees=%s ; %s" % (r.get("completed"), r.get("differees") or [], ", ".join(actions))
    return texte if len(texte) <= 1500 else texte[:1500] + " [... %d car. coupes]" % (len(texte) - 1500)


if __name__ == "__main__":
    raise SystemExit(main())
