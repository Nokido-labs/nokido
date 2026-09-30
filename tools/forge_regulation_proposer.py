#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_regulation_proposer.py — PREPARE l'ACT, sans jamais agir.

Etapes 1 -> 4 du protocole durci (2026-08-15, feu vert scope owner) :
  1. politiques candidates (DONNEES, pas de code executant)
  2. le learner PROPOSE la meilleure pour l'etat courant -- jamais ne decide
  3. DRY-RUN : impact simule via le world-model, RIEN n'est applique
  4. la proposition attend une VALIDATION HUMAINE

INTERDIT (etapes 5+ non ouvertes) : appliquer une politique, evincer, reveiller,
kill, restart, chainer des actions. Ce module ne contient aucun appel de cycle de
vie -- une garde de test l'impose. La transition « apprendre de l'organisme » ->
« apprendre en intervenant sur soi » est architecturale et reste fermee.

Deux durcissements exiges :
  - ETAT SUFFISAMMENT SIMILAIRE : on ne compare des politiques que sur des
    episodes dont l'etat physiologique est PROCHE de l'etat courant (distance <
    seuil). Sinon « B a gagne » pourrait juste vouloir dire « le 2e stress etait
    plus doux ».
  - COUT : la valeur d'une politique doit se lire NETTE de son cout (un gain de
    recovery paye par une reconstruction massive n'est pas un gain). Le cout
    n'est mesurable qu'en EXPERIMENTANT (moitie ACT) ; ici on le declare dans le
    schema et on le prend en compte des qu'il est present.

Usage :
    forge_regulation_proposer.py                 # propose pour l'etat courant
    forge_regulation_proposer.py --json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1. POLITIQUES CANDIDATES — pure description, aucun effet. `rules_v1` est
# l'incumbent (les seuils 75/65 en vigueur). Les autres n'existeront vraiment
# qu'une fois EXPERIMENTEES (moitie ACT) ; ici elles sont declarees pour que le
# proposeur ait un espace de choix a presenter.
POLITIQUES = {
    "rules_v1": {"desc": "incumbent — seuils evict 75 / wake 65", "evict": 75, "wake": 65},
    "conservative": {"desc": "evince tard, preserve le chaud", "evict": 85, "wake": 70},
    "aggressive": {"desc": "evince tot, libere vite", "evict": 68, "wake": 60},
    "memory_first": {"desc": "cible d'abord les gros modeles", "evict": 75, "wake": 65,
                     "priorite": "memoire"},
}

# Etat « suffisamment similaire » : distance euclidienne normalisee sur (ram, cpu).
# Extensible aux autres canaux vitals. 0.15 ~ 15 % d'ecart cumule.
SEUIL_SIMILARITE = float(os.environ.get("LAFORGE_PROPOSER_SIM", "0.15"))
MIN_EPISODES = 3   # sous ce nombre d'episodes similaires, on n'ose pas comparer


def _distance(a: dict, b: dict) -> float | None:
    """Distance normalisee entre deux etats physiologiques (ram, cpu en %)."""
    ra, ca = a.get("ram"), a.get("cpu")
    rb, cb = b.get("ram"), b.get("cpu")
    if not all(isinstance(x, (int, float)) for x in (ra, ca, rb, cb)):
        return None
    return math.sqrt(((ra - rb) / 100.0) ** 2 + ((ca - cb) / 100.0) ** 2)


def _etat_episode(e: dict) -> dict:
    return {"ram": e.get("ram_at_trigger"), "cpu": e.get("cpu_at_trigger")}


def _valeur_nette(e: dict) -> float:
    """Recompense NETTE du cout. Le cout n'est present que sur les episodes
    EXPERIMENTES (moitie ACT) ; absent, la valeur brute vaut valeur nette."""
    r = e.get("recompense", 0.0)
    cout = e.get("cout") or {}
    penalite = 0.0
    if isinstance(cout, dict):
        # churn memoire 0..1, temps de rechargement normalise ~/30s. Best-effort,
        # ne s'active que si l'experience a rempli ces champs.
        penalite += float(cout.get("memory_churn") or 0.0) * 0.3
        penalite += min(float(cout.get("reload_s") or 0.0) / 30.0, 0.3)
    return round(max(0.0, r - penalite), 3)


def etat_courant() -> dict | None:
    """Dernier etat physiologique connu, depuis la serie vitals."""
    sys.path.insert(0, ROOT)
    from nokido_agent.tools import forge_physiology as P
    rows = P._lire_serie(1)
    if not rows:
        return None
    r = rows[-1]
    return {"ram": r.get("ram_pct"), "cpu": r.get("cpu_pct")}


def proposer(etat: dict) -> dict:
    sys.path.insert(0, ROOT)
    from nokido_agent.tools import forge_regulation_learner as L
    ledger = L.charger_ledger()

    # 2. filtrer sur les episodes d'ETAT SUFFISAMMENT SIMILAIRE
    similaires = []
    for e in ledger:
        d = _distance(_etat_episode(e), etat)
        if d is not None and d < SEUIL_SIMILARITE:
            similaires.append(e)

    par_pol: dict = {}
    for e in similaires:
        pol = e.get("politique", "rules_v1")
        par_pol.setdefault(pol, []).append(_valeur_nette(e))
    candidates = [{"politique": p, "valeur_nette": round(statistics.mean(v), 3),
                   "n_similaires": len(v)}
                  for p, v in par_pol.items() if len(v) >= MIN_EPISODES]
    candidates.sort(key=lambda c: c["valeur_nette"], reverse=True)

    proposition = candidates[0]["politique"] if candidates else None
    # confiance = combien d'episodes similaires soutiennent la proposition
    n = candidates[0]["n_similaires"] if candidates else 0
    confiance = "forte" if n >= 12 else ("moyenne" if n >= 6 else "faible")

    avert = None
    autres = [p for p in POLITIQUES if p != "rules_v1"]
    if not any(c["politique"] in autres for c in candidates):
        avert = ("aucune donnee sur les politiques alternatives (%s) : seule "
                 "l'incumbent a un historique. Les COMPARER exige de les "
                 "EXPERIMENTER — moitie ACT, non ouverte." % ", ".join(autres))

    return {
        "etat_courant": etat,
        "episodes_similaires": len(similaires),
        "seuil_similarite": SEUIL_SIMILARITE,
        "candidates": candidates,
        "proposition": proposition,
        "confiance": confiance,
        "dry_run": _dry_run(proposition or "rules_v1", etat),
        "requires_human_approval": True,   # etape 4 : rien ne s'applique sans l'owner
        "acte": None,                      # etape 5+ FERMEE : aucune action
        "avertissement": avert,
    }


def _dry_run(politique: str, etat: dict) -> dict:
    """3. Simule l'impact SANS l'appliquer. Reutilise le world-model (verdict de
    surete par dependances) sur une cible representative. N'execute RIEN."""
    verdict, note = "inconnu", ""
    try:
        sys.path.insert(0, ROOT)
        from nokido_agent.app.forge_body_world_model import predict_impact
        # cible representative d'une eviction memoire : un backend lourd.
        imp = predict_impact("ollama", "pause")
        verdict = imp.get("verdict", "inconnu")
        note = imp.get("reason", "")
    except Exception as e:  # noqa: BLE001 - dry-run best-effort, jamais bloquant
        note = f"world-model indisponible ({type(e).__name__})"
    return {"politique": politique, "cible_representative": "ollama",
            "verdict_surete": verdict, "note": note,
            "applique": False}   # invariant : un dry-run n'applique jamais


def main() -> int:
    ap = argparse.ArgumentParser(description="Proposeur de regulation (PASSIF, prepare l'ACT)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    etat = etat_courant()
    if etat is None or etat.get("ram") is None:
        print("[proposeur] INDETERMINE — pas d'etat vitals courant")
        return 2
    rap = proposer(etat)
    if a.json:
        print(json.dumps(rap, ensure_ascii=False, indent=2))
        return 0
    print(f"[proposeur] etat ram={etat.get('ram')} cpu={etat.get('cpu')} — "
          f"{rap['episodes_similaires']} episode(s) similaire(s)")
    for c in rap["candidates"]:
        print(f"   {c['politique']:<14} valeur_nette {c['valeur_nette']} (n={c['n_similaires']})")
    print(f"   PROPOSITION : {rap['proposition']} (confiance {rap['confiance']})")
    dr = rap["dry_run"]
    print(f"   DRY-RUN     : surete={dr['verdict_surete']} — {dr['note']} "
          f"[applique={dr['applique']}]")
    print("   -> ATTEND VALIDATION HUMAINE. Aucune action appliquee.")
    if rap.get("avertissement"):
        print(f"   ⚠ {rap['avertissement']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
