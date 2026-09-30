"""forge_suite_pure_valider.py - execute chaque candidat SEUL, ecrit le verdict.

POURQUOI CE FICHIER EXISTE. `forge_suite_pure_triage.py --valider` fait le
travail, mais il depasse le cap de 120 s des appels hub : 39 fichiers lances un
par un ne rentrent pas dans une reponse synchrone. `run_job` ne passe pas
d'arguments, d'ou ce point d'entree sans option -- meme motif que le marqueur de
`forge_push_sovereign`.

Le verdict est ECRIT sur disque plutot que rendu : un job detache dont la sortie
se perd ne prouve rien.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/tests : execute chaque candidat seul et ecrit le verdict"  # organe declare le 2026-09-06 (audit de raccordement)

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SORTIE = ROOT / "sandbox" / "suite_pure_validation.json"


def _triage():
    chemin = ROOT / "tools" / "forge_suite_pure_triage.py"
    spec = importlib.util.spec_from_file_location("forge_suite_pure_triage", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_suite_pure_triage"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    t = _triage()
    r = t.trier()
    if "ARRET" in r:
        print("ARRET :", r["ARRET"], flush=True)
        return 2
    print("[valider] %d candidats a executer un par un" % len(r["candidats"]), flush=True)
    v = t.valider(r["candidats"])
    v["_methode"] = ("chaque fichier lance SEUL, avec --timeout=30. Vert = rc 0. "
                     "Lances ENSEMBLE ces memes fichiers rendaient 45 echecs et "
                     "31 erreurs : la presomption statique ne suffit pas.")
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(v, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    print("[valider] VERTS %d fichiers / %d tests — ROUGES %d — ecrit dans %s"
          % (len(v["verts"]), v["tests_rapatriables"], len(v["rouges"]), SORTIE),
          flush=True)
    for c in v["verts"]:
        print("   VERT  %-50s %3d tests" % (c["fichier"], c["tests"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
