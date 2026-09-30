#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_job_liveness.py — un job deporte TRAVAILLE-t-il vraiment ?

Consigne owner du 2026-08-17 : « assure-toi systematiquement que tu ne lances pas
des jobs morts ». Un `run_job` rend `{"ok": true, "job_id": ...}` des que le
process est SPAWNE — cela ne dit rien de ce qu'il fait ensuite. Le 2026-08-17,
quatre campagnes de rattrapage ont ete annoncees comme lancees alors qu'elles
mouraient dans les secondes suivantes (verrou SQLite, garde interne, rate-limit
lu comme un echec). Le `ok:true` du lancement etait vrai, et sans valeur.

Ce controle juge le job de L'EXTERIEUR — il n'exige aucune cooperation de sa part
(contrairement a `forge_job_watch_notify`, qui lit un `progress.json` que le job
doit ecrire). Il observe trois choses :
  1. le process vit-il encore ?
  2. son journal PROGRESSE-t-il entre deux relevés ?
  3. a-t-il deja rendu un code retour ?

Verdicts (et code de sortie) :
  0  PRODUCTIF   — vivant et son journal avance
  0  TERMINE_OK  — fini, rc=0
  0  SILENCIEUX  — vivant, journal immobile, mais SOUS le seuil de figement
  3  FIGE        — vivant et journal immobile AU-DELA du seuil
  4  MORT_PRECOCE— plus de process et aucun code retour
  5  TERMINE_KO  — fini avec rc != 0

⚠️ SILENCIEUX n'est pas une panne. Un job legitime peut se taire longtemps :
`forge_fts_backfill` lit les identifiants pendant ~50 s sans rien ecrire, et
`forge_veille_gap_run` observe 90 s de repos entre deux passes. Un detecteur qui
crie « fige » sur ces silences est aussi trompeur que le `ok:true` qu'il est cense
corriger — c'est pourquoi le figement n'est prononce qu'au-dela de `--seuil-fige`
(180 s par defaut), et jamais sur une simple fenetre d'observation.

Usage :
  LAFORGE_PYTHON tools/forge_job_liveness.py --job-id job_abc123
  LAFORGE_PYTHON tools/forge_job_liveness.py --job-id job_abc123 --fenetre 45
"""
from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/monitor : un job deporte travaille-t-il vraiment"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "sandbox" / "jobs"


def _fiche(job_id: str) -> dict:
    f = JOBS / ("%s.json" % job_id)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return {}


def _taille_log(job_id: str) -> int:
    f = JOBS / ("%s.log" % job_id)
    return f.stat().st_size if f.exists() else -1


def _rc(job_id: str):
    f = JOBS / ("%s.rc" % job_id)
    if not f.exists():
        return None
    txt = f.read_text(encoding="utf-8", errors="replace").strip()
    try:
        return int(txt)
    except ValueError:
        return None


def _vivant(pid: int) -> bool:
    """Presence du PID, sans droit particulier (tasklist, jamais wmic)."""
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
            capture_output=True, text=True, errors="replace", timeout=15,
        ).stdout
    except Exception as exc:  # noqa: BLE001 — on le DIT plutot que de supposer vivant
        print("  ! tasklist indisponible (%s) : vitalite INDETERMINEE" % type(exc).__name__)
        return False
    return str(pid) in out


def controler(job_id: str, fenetre: float = 30.0, pas: float = 5.0,
              seuil_fige: float = 180.0) -> tuple:
    """Rend (verdict, detail). Observe le journal sur `fenetre` secondes.

    Le figement se juge sur l'AGE de la derniere ecriture (`seuil_fige`), pas sur
    la duree de l'observation : sinon tout job en phase longue ou en repos serait
    declare mort.
    """
    fiche = _fiche(job_id)
    if not fiche:
        return "INCONNU", "aucune fiche pour %s dans %s" % (job_id, JOBS)
    pid = int(fiche.get("pid") or 0)

    rc = _rc(job_id)
    if rc is not None:
        return ("TERMINE_OK" if rc == 0 else "TERMINE_KO"), "rc=%s" % rc

    t0 = _taille_log(job_id)
    fin = time.time() + fenetre
    while time.time() < fin:
        time.sleep(pas)
        if _taille_log(job_id) > t0:
            return "PRODUCTIF", "journal +%d octets" % (_taille_log(job_id) - t0)
        rc = _rc(job_id)
        if rc is not None:
            return ("TERMINE_OK" if rc == 0 else "TERMINE_KO"), "rc=%s" % rc
        if not _vivant(pid):
            return "MORT_PRECOCE", "pid %s absent, aucun code retour" % pid

    if not _vivant(pid):
        return "MORT_PRECOCE", "pid %s absent, aucun code retour" % pid

    f = JOBS / ("%s.log" % job_id)
    age = time.time() - f.stat().st_mtime if f.exists() else fenetre
    if age >= seuil_fige:
        return "FIGE", "journal muet depuis %ss (pid %s vivant)" % (int(age), pid)
    return ("SILENCIEUX",
            "vivant, journal muet depuis %ss — sous le seuil de %ss "
            "(phase longue ou repos entre passes)" % (int(age), int(seuil_fige)))


_SORTIE = {"PRODUCTIF": 0, "TERMINE_OK": 0, "SILENCIEUX": 0, "FIGE": 3,
           "MORT_PRECOCE": 4, "TERMINE_KO": 5, "INCONNU": 6}


def main() -> int:
    ap = argparse.ArgumentParser(description="Un job deporte travaille-t-il vraiment ?")
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--fenetre", type=float, default=30.0,
                    help="duree d'observation du journal, en secondes")
    ap.add_argument("--pas", type=float, default=5.0)
    ap.add_argument("--seuil-fige", type=float, default=180.0,
                    help="age du journal au-dela duquel le job est declare FIGE")
    a = ap.parse_args()

    verdict, detail = controler(a.job_id, a.fenetre, a.pas, a.seuil_fige)
    print("%s : %s — %s" % (a.job_id, verdict, detail))
    if verdict in ("FIGE", "MORT_PRECOCE", "TERMINE_KO"):
        print("  -> NE PAS annoncer ce job comme lance : il ne produit rien.")
    return _SORTIE.get(verdict, 6)


if __name__ == "__main__":
    sys.exit(main())
