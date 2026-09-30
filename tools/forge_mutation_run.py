#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_mutation_run.py — lanceur de la boucle d'auto-amelioration.

Remise en service de `LocalMutationManager` + `ParallelMutationWorker`, perdus
le 2026-03-26 (`chore: clean hackathon branch`). La logique vit dans
`app/forge_self_mutation.py` ; ce module ne fait que la lancer.

GARDES RESPECTES :
  - dry_run par DEFAUT : `--apply` est explicite, jamais implicite
  - `fichier_protege` interdit toute mutation de ce qui surveille le systeme
  - l'ecriture passe par `governed_write` (AST + secrets + fichiers critiques)
  - le parallelisme est borne (--workers, defaut 3) : un fichier par agent,
    jamais deux mutations sur le meme fichier
  - aucun commit, aucun push : la mise en service reste une decision owner

Usage :
    forge_mutation_run.py --cible app/forge_novelty_search.py --tache "clarifier"
    forge_mutation_run.py --batch app/a.py app/b.py --workers 3
    forge_mutation_run.py --cible app/a.py --tache "..." --apply
"""
from __future__ import annotations

__FORGE_COLOR__ = "locomoteur/orchestr : lanceur de la boucle d'auto-amelioration"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import concurrent.futures
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nokido_agent.app.forge_self_mutation import MutationCycle, fichier_protege  # noqa: E402

SORTIE = os.path.join(ROOT, "sandbox", "mutation")


def _un_cycle(cible: str, tache: str, applique: bool) -> dict:
    debut = time.time()
    try:
        res = MutationCycle().run_cycle(cible, tache, dry_run=not applique)
    except Exception as exc:  # un cycle qui casse ne doit pas tuer le lot
        res = {"ok": False, "etape": "exception", "motif": str(exc), "cible": cible}
    res["secondes"] = round(time.time() - debut, 1)
    res.setdefault("cible", cible)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Boucle d'auto-amelioration gouvernee")
    ap.add_argument("--cible", default=None)
    ap.add_argument("--batch", nargs="*", default=[])
    ap.add_argument("--tache", default="ameliore la lisibilite sans changer le comportement")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--apply", action="store_true",
                    help="applique la mutation (defaut : dry-run, rien n'est ecrit)")
    ap.add_argument("--forcer", action="store_true",
                    help="tenter meme sans modele local resident (ira au cloud)")
    a = ap.parse_args()

    cibles = list(a.batch) + ([a.cible] if a.cible else [])
    cibles = list(dict.fromkeys(cibles))
    if not cibles:
        print("[mutation] aucune cible ; --cible ou --batch")
        return 2

    refusees = [c for c in cibles if fichier_protege(c)]
    for c in refusees:
        print("[mutation] REFUS %s : ce fichier surveille le systeme" % c)
    cibles = [c for c in cibles if c not in refusees]
    if not cibles:
        return 1

    # Le routeur juge un slot local disponible sur la presence d'un modele
    # RESIDENT, et rend "RPM limit" quand il n'y en a pas -- un motif qui ne
    # decrit pas la cause. On la nomme ici, avant de perdre un cycle.
    try:
        from nokido_agent.tools.forge_warm_code_model import MODELE, residents
        vivants = residents()
    except Exception as exc:
        vivants, MODELE = None, "?"
        print("[mutation] residence non verifiable : %s" % exc)
    if vivants is not None and not vivants:
        print("[mutation] AUCUN modele resident : la cascade locale sortira "
              "'RPM limit', qui signifie ici 'aucun modele charge'.")
        print("[mutation] charger d'abord (detache) : run_job "
              "tools/forge_warm_code_model.py  [%s]" % MODELE)
        if not a.forcer:
            return 3

    mode = "APPLIQUE" if a.apply else "dry-run"
    print("[mutation] %s | %s cible(s) | %s worker(s)" % (mode, len(cibles), a.workers))

    resultats = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        futurs = {pool.submit(_un_cycle, c, a.tache, a.apply): c for c in cibles}
        for fut in concurrent.futures.as_completed(futurs):
            res = fut.result()
            resultats.append(res)
            etat = "OK " if res.get("ok") else "NON"
            print("  [%s] %-46s %-10s %s"
                  % (etat, res["cible"], res.get("etape"), res.get("motif", "")[:70]))
            for regle in res.get("rapport", []):
                if regle["etat"] != "PASS":
                    print("        %-20s %s %s"
                          % (regle["regle"], regle["etat"], regle.get("detail", "")))

    os.makedirs(SORTIE, exist_ok=True)
    horodate = time.strftime("%Y%m%d_%H%M%S")
    rapport = os.path.join(SORTIE, "cycle_%s.json" % horodate)
    with open(rapport, "w", encoding="utf-8") as fh:
        json.dump(resultats, fh, ensure_ascii=False, indent=1)

    retenus = sum(1 for r in resultats if r.get("ok"))
    print("[mutation] %s/%s propositions retenues par le garde"
          % (retenus, len(resultats)))
    if not a.apply and retenus:
        print("[mutation] rien n'a ete ecrit (dry-run). Relire le diff dans %s"
              % os.path.relpath(rapport, ROOT))
    print("[mutation] rapport : %s" % os.path.relpath(rapport, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
