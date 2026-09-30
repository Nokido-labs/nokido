#!/usr/bin/env python3
"""progress_watch — fait DEFILER l'avancement d'un job detache, une ligne par etape.

__FORGE_COLOR__ = "sn-vegetatif/interoception-jobs"

LE MAILLON QUI MANQUAIT
=======================
La norme owner dit : « barre de run — `Monitor progress_watch.py <job_id>` pour tout
run long ». Mesure du 2026-09-03 : ce fichier N'EXISTAIT PAS. La chaine avait donc un
emetteur (depuis aujourd'hui : `forge_job_progress` + `ci_local`), un lecteur
(`read_job` qui joint `progress`), et AUCUN visualiseur — l'owner ne voyait rien
defiler, et l'agent rapportait le resultat a la fin au lieu de l'avancement.

C'est la troisieme forme du meme defaut rencontree ce jour : une norme ecrite, des
consommateurs en place, et une piece absente qui rend l'ensemble muet sans que rien
ne le signale.

CONTRAT AVEC `Monitor`
======================
Chaque ligne de stdout devient une notification. On imprime donc UNIQUEMENT sur
CHANGEMENT d'etape — un tick silencieux n'est pas un evenement — et on sort des que
le job est termine, pour que la surveillance s'arrete d'elle-meme.

SILENCE N'EST PAS SUCCES. Le script emet sur TOUS les etats terminaux, pas seulement
sur la fin heureuse : rc non nul, job mort sans rc (tue, borne externe), progression
GELEE au-dela du seuil. Un visualiseur qui ne parle que quand tout va bien laisse une
panne ressembler a un travail en cours.

Usage :
    LAFORGE_PYTHON tools/progress_watch.py <job_id> [--gel 300] [--max 7200]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = Path(os.environ.get("LAFORGE_JOBS_DIR", str(ROOT / "sandbox" / "jobs")))


def _lire(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def suivre(job_id: str, gel_s: float = 300.0, max_s: float = 7200.0) -> int:
    prog = JOBS / ("%s.progress.json" % job_id)
    rc_f = JOBS / ("%s.rc" % job_id)
    fiche = JOBS / ("%s.json" % job_id)
    if not fiche.is_file():
        print("[watch] job %s INCONNU (aucune fiche dans %s)" % (job_id, JOBS))
        return 2

    debut = time.monotonic()
    vue = None
    dernier_mouvement = time.monotonic()
    gel_signale = False
    print("[watch] %s — suivi demarre" % job_id, flush=True)

    while True:
        if rc_f.is_file():
            try:
                rc = rc_f.read_text(encoding="utf-8").strip()
            except OSError:
                rc = "?"
            verdict = "OK" if rc == "0" else "ECHEC"
            print("[watch] %s — TERMINE rc=%s (%s)" % (job_id, rc, verdict), flush=True)
            return 0

        etat = _lire(prog)
        if etat:
            cle = (etat.get("etape"), etat.get("index"))
            if cle != vue:
                vue = cle
                dernier_mouvement = time.monotonic()
                gel_signale = False
                pct = etat.get("pct")
                print("[watch] %s — %s%s" % (
                    job_id, etat.get("etape") or "?",
                    "  (%s/%s, %s%%)" % (etat.get("index"), etat.get("total"), pct)
                    if etat.get("total") else "  (#%s)" % etat.get("index")), flush=True)

        # Fiche passee a `dead` : le job est mort SANS rc. Sans cette branche, la
        # surveillance resterait muette jusqu'au timeout et l'absence de nouvelle
        # se lirait comme « ca travaille ».
        f = _lire(fiche)
        if f and f.get("status") in ("dead", "killed"):
            print("[watch] %s — job %s SANS code de retour (tue ou borne externe)"
                  % (job_id, f["status"]), flush=True)
            return 1

        immobile = time.monotonic() - dernier_mouvement
        if immobile > gel_s and not gel_signale:
            gel_signale = True
            print("[watch] %s — AUCUN MOUVEMENT depuis %d s (etape « %s ») : gele, "
                  "ou etape longue sans emission" % (
                      job_id, int(immobile), (vue or ("?",))[0]), flush=True)

        if time.monotonic() - debut > max_s:
            print("[watch] %s — surveillance ARRETEE apres %d s ; le job, lui, "
                  "continue peut-etre" % (job_id, int(max_s)), flush=True)
            return 1
        time.sleep(3.0)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: progress_watch.py <job_id> [--gel N] [--max N]")
        return 2
    job_id = argv[0]
    gel, mx = 300.0, 7200.0
    for opt, cible in (("--gel", "gel"), ("--max", "max")):
        if opt in argv:
            try:
                v = float(argv[argv.index(opt) + 1])
                if cible == "gel":
                    gel = v
                else:
                    mx = v
            except (ValueError, IndexError):
                pass
    return suivre(job_id, gel_s=gel, max_s=mx)


if __name__ == "__main__":
    sys.exit(main())
