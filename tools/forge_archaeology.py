#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_archaeology.py — archeologie fonctionnelle (Phase 1, LECTURE SEULE).

Reconstruit le patrimoine ENFOUI de l'ecosysteme Nokido : modules/fonctions
supprimes, deplaces vers un autre depot, ou remplaces -- a travers TOUT
l'historique (`git log --all --diff-filter=D`), pas seulement HEAD. Premier etage
de la memoire autobiographique du corps (owner + ChatGPT, 2026-08-15).

REGLE ABSOLUE (owner) : ne JAMAIS declarer une fonctionnalite morte parce qu'elle
n'est plus appelee. On classe sur PREUVE :
  DELETED  : supprimee et son basename n'existe dans le HEAD d'AUCUN depot
  MOVED    : supprimee ici mais son basename VIT dans le HEAD d'un AUTRE depot
             (feature migree — ex. vers netcfg-agent-web)
  REPLACED : supprimee puis RE-AJOUTEE dans le meme depot (reecriture)
  NOISE    : sauvegarde/attic/tmp — signale, jamais confondu avec du patrimoine

Aucune suppression, aucune modification : analyse pure. Sortie : archaeology.json
+ un resume lisible. Le tool prend une liste de (nom, chemin_depot) ; il tourne
sur les depots DISPONIBLES localement et nomme ceux qui manquent.

Usage :
    forge_archaeology.py --repos nokido=/chemin netcfg=/chemin ...
    forge_archaeology.py --json
    forge_archaeology.py --out sandbox/archaeology.json
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

__FORGE_COLOR__ = "observabilite/audit : archeologie fonctionnelle, phase 1 lecture seule"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os

from nokido_agent.tools.forge_archeo_socle import bruit_motifs
from nokido_agent.tools.forge_archeo_socle import git_rc as _git

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Depots de l'ecosysteme et leur emplacement local ATTENDU (siblings du parent).
# Un depot absent est NOMME dans le rapport, jamais silencieusement ignore.
_PARENT = os.path.dirname(ROOT)
DEPOTS_DEFAUT = {
    "nokido": ROOT,
    "nokido-workspace": _PARENT,
    "netcfg-agent": os.path.join(ROOT, "netcfg-agent"),
    "nokido-redteam": os.path.join(_PARENT, "PentestGPT"),  # clone local du silo redteam
}

_BRUIT = ("_attic", "backups", "refacto", "node_modules", ".venv", "site-packages",
          "RAG/", "RAG_plain_bak", "shadow_mutation", "/tmp_", "/_")


def _est_bruit(chemin: str) -> bool:
    return bruit_motifs(chemin, _BRUIT, ("tmp_", "_"))


def head_basenames(repo: str) -> set[str]:
    """Basenames des .py VIVANTS (HEAD) — pour distinguer MOVED de DELETED."""
    rc, out = _git(repo, "ls-files", "*.py")
    if rc != 0:
        return set()
    return {ligne.strip().replace("\\", "/").rsplit("/", 1)[-1]
            for ligne in out.splitlines() if ligne.strip().endswith(".py")}


def deleted(repo: str) -> list[dict]:
    """Chemins .py supprimes dans TOUT l'historique, avec la trace du commit qui
    les a retires (le plus recent). Bruit filtre mais COMPTE a part."""
    rc, out = _git(repo, "log", "--all", "--diff-filter=D", "--name-only",
                   "--date=short", "--pretty=format:__C__%h|%ad|%s")
    if rc != 0:
        return []
    vus: dict[str, dict] = {}
    sha = date = msg = ""
    for ligne in out.splitlines():
        if ligne.startswith("__C__"):
            corps = ligne[5:]
            parts = corps.split("|", 2)
            sha, date, msg = (parts + ["", "", ""])[:3]
        elif ligne.strip().endswith(".py"):
            chemin = ligne.strip().replace("\\", "/")
            # premiere occurrence = suppression la plus RECENTE (log est anti-chrono)
            if chemin not in vus:
                vus[chemin] = {"chemin": chemin, "sha_suppr": sha, "date_suppr": date,
                               "msg_suppr": msg[:120], "bruit": _est_bruit(chemin)}
    return list(vus.values())


def _est_depot(p: str) -> bool:
    """Un vrai depot git — teste par rev-parse, PAS par isdir(.git). Un submodule
    a un .git FICHIER (pas un dossier) : le test naif l'ecartait a tort (netcfg,
    redteam). rev-parse reussit sur un repo normal ET sur un submodule."""
    if not os.path.isdir(p):
        return False
    rc, _ = _git(p, "rev-parse", "--git-dir", timeout=20)
    return rc == 0


def classer(depots: dict[str, str]) -> dict:
    presents = {n: p for n, p in depots.items() if _est_depot(p)}
    absents = [n for n in depots if n not in presents]

    # basenames vivants par depot + union
    head = {n: head_basenames(p) for n, p in presents.items()}
    vivant_ailleurs = {}  # basename -> [depots ou il vit]
    for n, bset in head.items():
        for b in bset:
            vivant_ailleurs.setdefault(b, []).append(n)

    modules = []
    for n, p in presents.items():
        for d in deleted(p):
            base = d["chemin"].rsplit("/", 1)[-1]
            hotes = vivant_ailleurs.get(base, [])
            if d["bruit"]:
                etat = "NOISE"
            elif base in head.get(n, set()):
                etat = "REPLACED"      # re-ajoute dans le meme depot
            elif hotes:
                etat = "MOVED"          # vit dans un AUTRE depot
            else:
                etat = "DELETED"        # introuvable partout
            modules.append({"depot": n, **d, "etat": etat,
                            "vit_dans": [h for h in hotes if h != n]})
    # tri : le patrimoine reel (non-bruit) d'abord, plus recent en tete
    modules.sort(key=lambda m: (m["etat"] == "NOISE", m.get("date_suppr", "")), reverse=False)

    par_etat: dict = {}
    for m in modules:
        par_etat[m["etat"]] = par_etat.get(m["etat"], 0) + 1
    return {"depots_analyses": sorted(presents), "depots_absents": absents,
            "resume": par_etat, "modules": modules}


def main() -> int:
    ap = argparse.ArgumentParser(description="Archeologie fonctionnelle Nokido (Phase 1)")
    ap.add_argument("--repos", nargs="*", default=[],
                    help="nom=chemin supplementaires (sinon depots par defaut)")
    ap.add_argument("--out", default=os.path.join(ROOT, "sandbox", "archaeology.json"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()

    depots = dict(DEPOTS_DEFAUT)
    for spec in a.repos:
        if "=" in spec:
            n, p = spec.split("=", 1)
            depots[n] = p

    res = classer(depots)
    try:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    r = res["resume"]
    print(f"[archeologie] depots: {', '.join(res['depots_analyses'])}"
          + (f" | ABSENTS: {', '.join(res['depots_absents'])}" if res["depots_absents"] else ""))
    print(f"[archeologie] {sum(r.values())} .py supprimes — "
          + ", ".join(f"{k}={v}" for k, v in sorted(r.items())))
    reels = [m for m in res["modules"] if m["etat"] != "NOISE"]
    print(f"[archeologie] patrimoine reel (hors bruit) : {len(reels)} — top {a.top} :")
    for m in reels[:a.top]:
        suff = f" -> vit dans {m['vit_dans']}" if m["vit_dans"] else ""
        print(f"  [{m['etat']:<8}] {m['depot']}:{m['chemin']}  ({m['date_suppr']}){suff}")
    print(f"[archeologie] ecrit : {os.path.relpath(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
