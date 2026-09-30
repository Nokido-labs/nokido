#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_capability_recovery.py — remonter les capacites perdues.

POURQUOI. Le census (Phase 7) etablit que les capacites les plus couteuses ne
sont pas mortes pour elles-memes mais par balayage collateral : un nettoyage de
651 fichiers "non-essentiels" le 2026-03-26 a emporte le sous-systeme de
mutation parallele (`ParallelMutationWorker.py` : 140 reprises pour 4 jours de
vie), un `untrack standalone modules` le 2026-05-21 a emporte l'application
desktop. Ce code n'est pas detruit : il vit dans l'historique git.

Cet outil extrait la DERNIERE version connue de chaque capacite perdue, juste
avant sa suppression, et decrit ce qu'elle faisait (AST : classes, fonctions,
docstring, LOC).

REGLE OWNER : on PROPOSE, on ne reintegre RIEN automatiquement. L'outil ecrit
exclusivement sous sandbox/recovery/ et ne touche aucun depot.

Usage :
    forge_capability_recovery.py                    # top 20 par cout investi
    forge_capability_recovery.py --min-churn 10
    forge_capability_recovery.py --chemins ParallelMutationWorker.py
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

__FORGE_COLOR__ = "observabilite/audit : remonter les capacites perdues"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENSUS = os.path.join(ROOT, "sandbox", "history_census.json")
SORTIE = os.path.join(ROOT, "sandbox", "recovery")


def _git(depot, *args, texte=True):
    cmd = ["git", "-c", "safe.directory=*", "-C", depot] + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, text=texte,
                           encoding="utf-8" if texte else None,
                           errors="replace" if texte else None, timeout=120)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def sha_suppression(depot, chemin):
    """Le commit qui a supprime ce fichier (le plus recent s'il y en a eu plusieurs)."""
    out = _git(depot, "log", "--all", "--diff-filter=D", "--format=%H", "-1",
               "--", chemin)
    return out.strip().splitlines()[0] if out.strip() else ""


def decrire(source):
    """Ce que faisait la capacite, lu dans son code : AST seul, aucune execution."""
    infos = {"loc": source.count("\n") + 1, "classes": [], "fonctions": [],
             "docstring": "", "imports": []}
    try:
        arbre = ast.parse(source)
    except SyntaxError as exc:
        infos["erreur_ast"] = "non parsable : %s" % exc
        return infos
    doc = ast.get_docstring(arbre)
    if doc:
        infos["docstring"] = " ".join(doc.split())[:400]
    for noeud in arbre.body:
        if isinstance(noeud, ast.ClassDef):
            methodes = [n.name for n in noeud.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            infos["classes"].append({"nom": noeud.name, "methodes": methodes[:20]})
        elif isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            infos["fonctions"].append(noeud.name)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            infos["imports"].append(noeud.module)
        elif isinstance(noeud, ast.Import):
            infos["imports"].extend(a.name for a in noeud.names)
    infos["imports"] = sorted(set(infos["imports"]))[:25]
    return infos


def recuperer(depot_nom, depot_chemin, perdu):
    chemin = perdu["chemin"]
    sha = sha_suppression(depot_chemin, chemin)
    fiche = {"depot": depot_nom, "chemin": chemin, "churn": perdu.get("churn"),
             "ne": perdu.get("ne"), "mort": perdu.get("mort"),
             "motif": perdu.get("motif", ""), "sha_suppression": sha}
    if not sha:
        fiche["etat"] = "INTROUVABLE : aucun commit de suppression"
        return fiche, None
    source = _git(depot_chemin, "show", "%s^:%s" % (sha, chemin))
    if not source:
        fiche["etat"] = "VIDE : le parent du commit de suppression n'a pas ce chemin"
        return fiche, None
    fiche["etat"] = "RECUPERE"
    fiche.update(decrire(source) if chemin.endswith(".py") else {"loc": source.count("\n") + 1})
    return fiche, source


def main():
    ap = argparse.ArgumentParser(description="Remonte les capacites perdues")
    ap.add_argument("--min-churn", type=int, default=10)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--chemins", nargs="*", default=[],
                    help="cibler des chemins precis au lieu du classement par cout")
    a = ap.parse_args()

    if not os.path.isfile(CENSUS):
        raise SystemExit("[recovery] lance d'abord forge_history_census.py")
    census = json.load(open(CENSUS, encoding="utf-8"))

    candidats = []
    for nom, d in census["depots"].items():
        if "erreur" in d:
            continue
        for perdu in d.get("morts_reelles", []):
            if a.chemins:
                if not any(c in perdu["chemin"] for c in a.chemins):
                    continue
            elif perdu.get("churn", 0) < a.min_churn:
                continue
            candidats.append((perdu.get("churn", 0), nom, d["chemin"], perdu))

    # OFFENSIF EXCLU (decision owner) : le domaine offensif est deporte en depot
    # prive et ne doit JAMAIS etre remonte a la reintegration. Filtre UNIQUE
    # reutilise de forge_capability_consolidation (anti-dup) ; exclut par chemin
    # ET par nom de depot (ex: PentestGPT). Fail-safe : si le filtre manque, ARRET
    # plutot que rapatrier de l'offensif.
    try:
        from nokido_agent.tools.forge_capability_consolidation import est_offensif
    except Exception as _e:
        raise SystemExit("[recovery] filtre offensif absent, ARRET par surete: %s" % _e)
    _avant = len(candidats)
    candidats = [c for c in candidats
                 if not (est_offensif(c[3]["chemin"]) or est_offensif(c[1]))]
    _exclus = _avant - len(candidats)
    if _exclus:
        print("[recovery] %d capacite(s) offensive(s) exclue(s) (owner, depot prive)"
              % _exclus)
    candidats.sort(key=lambda x: -x[0])
    candidats = candidats[:a.top]
    if not candidats:
        print("[recovery] aucun candidat")
        return 0

    os.makedirs(SORTIE, exist_ok=True)
    fiches = []
    vus = set()
    for _churn, nom, depot_chemin, perdu in candidats:
        # Un meme fichier vit dans plusieurs depots (super-repo + submodule,
        # fork + lignee importee) : on ne le recupere qu'une fois.
        cle = perdu["chemin"]
        if cle in vus:
            continue
        vus.add(cle)
        fiche, source = recuperer(nom, depot_chemin, perdu)
        if source is not None:
            cible = os.path.join(SORTIE, nom, perdu["chemin"].replace("/", os.sep))
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            with open(cible, "w", encoding="utf-8") as fh:
                fh.write(source)
            fiche["fichier"] = os.path.relpath(cible, ROOT)
        fiches.append(fiche)
        print("  [%s] %sx %s:%s" % (fiche["etat"][:10], fiche["churn"], nom,
                                    perdu["chemin"]))

    rapport = os.path.join(SORTIE, "RAPPORT.md")
    with open(rapport, "w", encoding="utf-8") as fh:
        fh.write("# Capacites perdues remontees\n\n")
        fh.write("Genere le %s. Extraction LECTURE SEULE : aucun depot modifie,\n"
                 "aucune reintegration. La decision de remettre en service reste owner.\n\n"
                 % time.strftime("%Y-%m-%d %H:%M"))
        for f in fiches:
            fh.write("## %s:%s\n\n" % (f["depot"], f["chemin"]))
            fh.write("- etat : **%s**, %s reprises, vie %s -> %s\n"
                     % (f["etat"], f.get("churn"), f.get("ne"), f.get("mort")))
            if f.get("motif"):
                fh.write("- tue par : `%s`\n" % f["motif"])
            if f.get("fichier"):
                fh.write("- code remonte : `%s` (%s lignes)\n"
                         % (f["fichier"], f.get("loc")))
            if f.get("docstring"):
                fh.write("- intention declaree : %s\n" % f["docstring"])
            if f.get("classes"):
                fh.write("- classes : %s\n" % ", ".join(
                    "%s(%s)" % (c["nom"], len(c["methodes"])) for c in f["classes"]))
            if f.get("fonctions"):
                fh.write("- fonctions : %s\n" % ", ".join(f["fonctions"][:20]))
            if f.get("imports"):
                fh.write("- dependances : %s\n" % ", ".join(f["imports"][:15]))
            fh.write("\n")
    with open(os.path.join(SORTIE, "recovery.json"), "w", encoding="utf-8") as fh:
        json.dump(fiches, fh, ensure_ascii=False, indent=1)

    ok = sum(1 for f in fiches if f["etat"] == "RECUPERE")
    print("[recovery] %s/%s capacites remontees sous %s"
          % (ok, len(fiches), os.path.relpath(SORTIE, ROOT)))
    print("[recovery] rapport : %s" % os.path.relpath(rapport, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
