#!/usr/bin/env python
"""hook_instructions_loaded.py — capteur `InstructionsLoaded` de Claude Code (observation seule).

POURQUOI (26/09, chantier « leviers Claude Code », accord owner) : le poids des consignes
residentes a ete mesure A LA MAIN, une fois (RULES_SHARED ~7 900 tokens a chaque tour,
Nokido/CLAUDE.md ~4 200 des la premiere lecture sous Nokido/). Claude Code emet
`InstructionsLoaded` a chaque chargement d'un CLAUDE.md ou d'une regle, avec sa raison
(session_start, nested_traversal, path_glob_match, include, compact) : ce capteur les
journalise pour que ce cout se LISE au lieu de se re-mesurer. Aucun outil ne le faisait
(`forge_retrieval_sweep InstructionsLoaded` : surface outils vide, 26/09).

L'evenement n'a AUCUN controle de decision (doc hooks.md : sortie JSON ignoree) : le hook
se cable `async`, sort toujours 0 et n'ecrit rien sur stdout. Un echec se DIT sur stderr.
Une taille illisible est notee ILLISIBLE, jamais 0.

USAGE
  (stdin = JSON du hook)   ajoute une ligne a logs/instructions_loaded.jsonl
  --bilan [--jours N]      par fichier : chargements, raisons, taille, sessions
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

__FORGE_COLOR__ = "sensoriel/capteur des consignes chargees par Claude Code"

RACINE = Path(__file__).resolve().parent.parent
JOURNAL = Path(os.environ.get("NOKIDO_INSTRUCTIONS_JOURNAL") or RACINE / "logs" / "instructions_loaded.jsonl")
COMMUNS = {"session_id", "transcript_path", "cwd", "hook_event_name", "permission_mode"}


def _taille(chemin: str):
    try:
        return os.path.getsize(chemin)
    except OSError as e:
        return "ILLISIBLE: %s" % type(e).__name__


def consigner(evt: dict) -> dict:
    ligne = {
        "ts": round(time.time(), 3),
        "session_id": evt.get("session_id"),
        "file_path": evt.get("file_path"),
        "memory_type": evt.get("memory_type"),
        "load_reason": evt.get("load_reason"),
        "octets": _taille(evt["file_path"]) if evt.get("file_path") else "ILLISIBLE: pas de file_path",
        "autres": {k: v for k, v in evt.items()
                   if k not in COMMUNS and k not in ("file_path", "memory_type", "load_reason")},
    }
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as h:
        h.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def bilan(jours: float = 7.0) -> dict:
    """Par fichier : chargements, raisons, derniere taille, sessions. Lignes illisibles COMPTEES."""
    depuis = time.time() - jours * 86400
    par_fichier: dict = defaultdict(lambda: {"chargements": 0, "raisons": Counter(), "octets": None, "sessions": set()})
    lues, illisibles = 0, 0
    try:
        with open(JOURNAL, encoding="utf-8") as h:
            for brute in h:
                try:
                    ln = json.loads(brute)
                except ValueError:
                    illisibles += 1
                    continue
                lues += 1
                if (ln.get("ts") or 0) < depuis:
                    continue
                f = par_fichier[ln.get("file_path") or "?"]
                f["chargements"] += 1
                f["raisons"][ln.get("load_reason") or "?"] += 1
                f["octets"] = ln.get("octets")
                f["sessions"].add(ln.get("session_id"))
    except FileNotFoundError:
        return {"journal": str(JOURNAL), "etat": "ABSENT : aucun chargement capte (hook non cable ?)"}
    fichiers = sorted(
        ({"fichier": k, "chargements": v["chargements"], "raisons": dict(v["raisons"]),
          "octets": v["octets"], "sessions": len(v["sessions"])} for k, v in par_fichier.items()),
        key=lambda d: -(d["octets"] if isinstance(d["octets"], int) else 0) * d["chargements"])
    return {"journal": str(JOURNAL), "jours": jours, "lignes_lues": lues,
            "lignes_illisibles": illisibles, "fichiers": fichiers}


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Capteur InstructionsLoaded (Claude Code)")
    ap.add_argument("--bilan", action="store_true", help="agrege le journal par fichier")
    ap.add_argument("--jours", type=float, default=7.0)
    args = ap.parse_args(argv)
    if args.bilan:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — muet-ok : sortie non reconfigurable
            pass
        print(json.dumps(bilan(args.jours), indent=2, ensure_ascii=False))
        return 0
    try:
        consigner(json.loads(sys.stdin.read() or "{}"))
    except Exception as e:  # noqa: BLE001 — un capteur ne bloque jamais la session ; il le dit
        print("[hook_instructions_loaded] non consigne : %s: %s" % (type(e).__name__, e), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
