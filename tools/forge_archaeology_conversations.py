#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_archaeology_conversations.py — Phases 3 & 4 : intentions <-> code
<-> archeologie. LECTURE SEULE.

Phase 3 (intentions) : REUTILISE forge_intent_miner.extraire() -- il mine deja les
paroles owner des sessions CLI indexees (Claude/Gemini/AGY), avec leur couverture
git. On ne reconstruit pas.

Phase 4 (crosswalk) : pour chaque intention, on croise trois sources et on TRANCHE :
  IMPLEMENTED : couverture git forte -> le sujet a ete traite
  PARTIAL     : couverture moyenne
  VESTIGE     : jamais trace en commit MAIS un vestige supprime/deplace matche ->
                l'idee fut CODEE puis retiree = RECUPERABLE (on nomme le fichier)
  NOT_FOUND   : discutee, aucune trace, aucun vestige -> jamais construite

C'est la que se referme la boucle : une idee peut avoir plusieurs vies
(discutee -> prototypee -> supprimee -> reecrite ailleurs). Le crosswalk la retrouve.

LIMITE HONNETE : je ne vois PAS les conversations ChatGPT. Ce crosswalk ne couvre
que les sessions CLI INDEXEES. Le matching intention<->vestige est heuristique
(>=2 tokens partages), signale comme tel.

Usage :
    forge_archaeology_conversations.py            # crosswalk lisible
    forge_archaeology_conversations.py --json
    (lit sandbox/archaeology.json + la base RAG via forge_intent_miner)
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "observabilite/audit : archeologie, intentions vers code, phases 3 et 4"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH = os.path.join(ROOT, "sandbox", "archaeology.json")
MD_OUT = os.path.join(ROOT, "sandbox", "conversation_code_crosswalk.md")

_STOP = {"pour", "avec", "dans", "cette", "faire", "quand", "tout", "plus", "sans",
         "mais", "avant", "apres", "leur", "meme", "sont", "chaque", "doit", "code",
         "nokido", "laforge", "fait", "etre", "vers", "sous"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", (s or "").lower())
            if t not in _STOP}


def phase3_intentions() -> dict:
    """Intentions owner minees des sessions indexees (source unique : intent_miner)."""
    if os.path.join(ROOT, "tools") not in sys.path:
        sys.path.insert(0, ROOT)
    from nokido_agent.tools import forge_intent_miner as IM
    return IM.extraire()


def _vestiges_non_bruit() -> list[dict]:
    try:
        with open(ARCH, encoding="utf-8") as fh:
            return [m for m in json.load(fh).get("modules", []) if m.get("etat") != "NOISE"]
    except (OSError, json.JSONDecodeError):
        return []


def _index_vestiges(vestiges: list[dict]) -> list[tuple[set[str], dict]]:
    """(tokens du chemin, vestige) — pour matcher une intention a un fichier."""
    out = []
    for v in vestiges:
        base = v.get("chemin", "").replace("\\", "/").rsplit("/", 1)[-1]
        out.append((_tokens(base.replace("_", " ").replace(".py", "")), v))
    return out


def _meilleur_vestige(intent_tokens: set[str], idx) -> tuple[dict | None, set[str]]:
    best, best_inter = None, set()
    for vtok, v in idx:
        inter = intent_tokens & vtok
        if len(inter) >= 2 and len(inter) > len(best_inter):
            best, best_inter = v, inter
    return best, best_inter


def crosswalk() -> dict:
    p3 = phase3_intentions()
    if not p3.get("ok"):
        return {"ok": False, "raison": p3.get("raison", "intent_miner KO")}
    idx = _index_vestiges(_vestiges_non_bruit())

    resultats = []
    for it in p3.get("intentions", []):
        cov = it.get("couverture_git", 0.0)
        toks = _tokens(it.get("signature", "")) | _tokens(" ".join(it.get("exemples", [])))
        if cov >= 0.8:
            etat, vest, inter = "IMPLEMENTED", None, set()
        elif cov >= 0.5:
            etat, vest, inter = "PARTIAL", None, set()
        else:
            vest, inter = _meilleur_vestige(toks, idx)
            etat = "VESTIGE" if vest else "NOT_FOUND"
        resultats.append({
            "signature": it.get("signature"), "occurrences": it.get("occurrences"),
            "couverture_git": cov, "portee": it.get("portee"),
            "exemple": (it.get("exemples") or [""])[0],
            "etat": etat,
            "vestige": (f"{vest['depot']}:{vest['chemin']}" if vest else None),
            "vestige_etat": (vest.get("etat") if vest else None),
            "preuve_tokens": sorted(inter),
        })
    ordre = {"VESTIGE": 0, "NOT_FOUND": 1, "PARTIAL": 2, "IMPLEMENTED": 3}
    resultats.sort(key=lambda r: (ordre.get(r["etat"], 9), -(r["occurrences"] or 0)))
    par_etat: dict = {}
    for r in resultats:
        par_etat[r["etat"]] = par_etat.get(r["etat"], 0) + 1
    return {"ok": True, "tours_owner": p3.get("tours_owner"),
            "intentions": len(resultats), "resume": par_etat, "crosswalk": resultats}


def _ecrire_md(res: dict) -> None:
    if not res.get("ok"):
        return
    r = res["resume"]
    lignes = ["# Crosswalk conversation <-> code <-> archeologie (Phases 3 & 4)",
              "",
              "_Sessions CLI indexees uniquement (les conversations ChatGPT me sont "
              "invisibles). Matching intention<->vestige heuristique (>=2 tokens)._",
              "",
              f"- IMPLEMENTED {r.get('IMPLEMENTED', 0)} | PARTIAL {r.get('PARTIAL', 0)} | "
              f"VESTIGE {r.get('VESTIGE', 0)} | NOT_FOUND {r.get('NOT_FOUND', 0)}",
              "",
              "## VESTIGE — idees CODEES puis retirees (recuperables)", ""]
    for c in [x for x in res["crosswalk"] if x["etat"] == "VESTIGE"]:
        lignes.append(f"- **{c['signature']}** (dit {c['occurrences']}x) -> "
                      f"{c['vestige']} ({c['vestige_etat']}) ; preuve {c['preuve_tokens']}")
        lignes.append(f"  - « {c['exemple']} »")
    lignes += ["", "## NOT_FOUND — discutees, jamais construites", ""]
    for c in [x for x in res["crosswalk"] if x["etat"] == "NOT_FOUND"][:40]:
        lignes.append(f"- **{c['signature']}** (dit {c['occurrences']}x) — « {c['exemple']} »")
    try:
        with open(MD_OUT, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lignes))
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Archeologie Phases 3 & 4 (crosswalk)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    res = crosswalk()
    if not res.get("ok"):
        print(f"[crosswalk] INDETERMINE — {res.get('raison')}")
        return 2
    _ecrire_md(res)
    if a.json:
        print(json.dumps({k: v for k, v in res.items() if k != "crosswalk"},
                         ensure_ascii=False))
        return 0
    r = res["resume"]
    print(f"[crosswalk] {res['intentions']} intentions — "
          + " | ".join(f"{k}={v}" for k, v in sorted(r.items())))
    print(f"[crosswalk] VESTIGE (idees codees puis retirees) et NOT_FOUND, top {a.top} :")
    for c in res["crosswalk"][:a.top]:
        v = f" -> {c['vestige']} ({c['vestige_etat']})" if c["vestige"] else ""
        print(f"  [{c['etat']:<11}] {c['signature']} (x{c['occurrences']}){v}")
    print(f"[crosswalk] ecrit : {os.path.relpath(MD_OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
