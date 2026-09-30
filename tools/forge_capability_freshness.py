#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fraicheur des observateurs de capacite -- rejoue les instruments EXISTANTS.

__FORGE_COLOR__ = "interoception/observateurs-de-capacite"

Pourquoi ce fichier (2026-09-02, tour 0). Quatre instruments d'atteignabilite
existent et rendent des verdicts honnetes -- crosswalk, execution_trace,
reachability_ledger, ratchet -- mais AUCUN cycle ne les rejouait : matrices
figees depuis le 16/08 (17 jours), ratchet INDETERMINE par peremption (423 h
pour une norme de 72 h). Un observateur qui ne tourne pas est une dette de
cablage, pas une securite. Ce wrapper est lance en NREM1 par le superviseur
Deno (proxy_deno/core/supervisor.ts), sur le patron du proprioception audit.

CE QUE CE FICHIER N'EST PAS. Il n'invente aucun instrument et ne juge rien :
il execute, date, et conserve. Un rc != 0 ou une sortie vide est CONSERVE tel
quel. INDETERMINE reste INDETERMINE : ni PASS ni FAIL, jamais un echec de phase.
Le circadien observe, il ne devient pas un gatekeeper. Sortie unique :
sandbox/capability_freshness.json (etat par instrument + age des matrices).

Rejeu manuel (compte sandbox, lane recommandee) :
  run action=run_job script=tools/forge_capability_freshness.py lane=audit_capacites
"""
from __future__ import annotations

import json
import os
import subprocess as sp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SORTIE = ROOT / "sandbox" / "capability_freshness.json"
TIMEOUT_S = 900

# (nom, script, args, fichier produit attendu ou None, {rc: etat})
# Les chemins de sortie sont ceux que les CONSOMMATEURS lisent deja :
#   crosswalk  -> sandbox/workspace/capability_crosswalk.json (lu par les cartes)
#   ledger     -> sandbox/reachability.json (defaut du script, lu par
#                 forge_capability_consolidation._noms_historiquement_prouves)
#   trace      -> sandbox/execution_trace.json (ecrit par le script lui-meme)
#   regression -> sandbox/regression_matrix.json (forge_regression_matrix
#                 --extract) : c'est LA matrice que lit le ratchet ; sans ce
#                 rejeu le ratchet reste INDETERMINE par construction (424 h)
#   ratchet    -> aucun fichier ; --check rend 0 conforme / 1 regression /
#                 3 INDETERMINE (matrice perimee ou socle absent)
INSTRUMENTS = (
    ("crosswalk", "tools/forge_capability_crosswalk.py",
     ["--out", str(ROOT / "sandbox" / "workspace" / "capability_crosswalk.json")],
     ROOT / "sandbox" / "workspace" / "capability_crosswalk.json", {0: "PASS"}),
    ("execution_trace", "tools/forge_capability_execution_trace.py", [],
     ROOT / "sandbox" / "execution_trace.json", {0: "PASS"}),
    ("reachability_ledger", "tools/forge_reachability_ledger.py", [],
     ROOT / "sandbox" / "reachability.json", {0: "PASS"}),
    ("regression_matrix", "tools/forge_regression_matrix.py", ["--extract"],
     ROOT / "sandbox" / "regression_matrix.json", {0: "PASS"}),
    ("ratchet_check", "tools/forge_capability_ratchet.py", ["--check"],
     None, {0: "PASS", 1: "REGRESSION", 3: "INDETERMINE"}),
)


def _age_h(p: Path | None):
    """Age du fichier produit, en heures. None = pas de fichier attendu ;
    'illisible:...' = on n'a pas pu regarder (jamais 0, jamais absent)."""
    if p is None:
        return None
    try:
        return round((time.time() - p.stat().st_mtime) / 3600.0, 2)
    except FileNotFoundError:
        return "absent"
    except Exception as exc:  # noqa: BLE001 - muet-ok : le motif est conserve
        return "illisible:" + type(exc).__name__


def lancer(nom: str, rel: str, args: list, produit: Path | None, etats: dict) -> dict:
    script = ROOT / rel
    if not script.is_file():
        return {"instrument": nom, "script": rel, "etat": "OUTIL_ABSENT"}
    t0 = time.time()
    try:
        r = sp.run([PY, str(script), *args], cwd=str(ROOT), stdout=sp.PIPE, stderr=sp.PIPE,
                   text=True, errors="replace", timeout=TIMEOUT_S)
        etat = etats.get(r.returncode, "ERREUR_OUTIL")
        return {"instrument": nom, "script": rel, "args": args, "rc": r.returncode,
                "etat": etat, "duree_s": round(time.time() - t0, 1),
                "stdout_tail": r.stdout[-1500:], "stderr_tail": r.stderr[-1500:],
                "produit": str(produit) if produit else None, "age_h_apres": _age_h(produit)}
    except sp.TimeoutExpired:
        return {"instrument": nom, "script": rel, "args": args, "etat": "TIMEOUT",
                "duree_s": round(time.time() - t0, 1)}
    except Exception as exc:  # noqa: BLE001 - muet-ok : l'exception est le resultat
        return {"instrument": nom, "script": rel, "args": args,
                "etat": "illisible:" + type(exc).__name__, "detail": str(exc)[:300]}


def main() -> int:
    res = {"debut": time.strftime("%Y-%m-%d %H:%M:%S"), "compte": os.environ.get("USERNAME", "?"),
           "avant": {nom: _age_h(p) for nom, _, _, p, _ in INSTRUMENTS},
           "instruments": [], "note": "observation seule : INDETERMINE n'est ni PASS ni FAIL"}
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for nom, rel, args, produit, etats in INSTRUMENTS:
        res["instruments"].append(lancer(nom, rel, args, produit, etats))
        SORTIE.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    res["fin"] = time.strftime("%Y-%m-%d %H:%M:%S")
    res["resume"] = {i["instrument"]: i.get("etat") for i in res["instruments"]}
    SORTIE.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["resume"], ensure_ascii=False))
    return 0  # observation : le rejeu a eu lieu, quels que soient les verdicts


if __name__ == "__main__":
    sys.exit(main())
