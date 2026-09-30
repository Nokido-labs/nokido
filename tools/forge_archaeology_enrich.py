#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_archaeology_enrich.py — Phases 2 & 5 : que faisait chaque vestige,
et lequel vaut d'etre recupere. LECTURE SEULE.

Phase 1 (forge_archaeology) a liste 1021 vestiges. Ici on ENRICHIT chacun par sa
DERNIERE version avant suppression (`git show <sha_suppr>^:<chemin>`) : fonctions,
classes, docstring, LOC. Puis on CLASSE par valeur de recuperation (Phase 5) :
un module DELETED, substantiel, documente, et porteur d'une capacite biomimetique
(regulation/memoire/perception...) vaut mieux qu'un stub oublie.

REGLE owner : aucune suppression, aucune reintegration automatique. On PROPOSE,
avec preuve (ou vivait le code, ce qu'il faisait, pourquoi probablement abandonne,
cout de reintegration). La decision reste owner.

Usage :
    forge_archaeology_enrich.py --repos nom=chemin ... [--max 500] [--top 50]
    (relit sandbox/archaeology.json produit par forge_archaeology)
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

__FORGE_COLOR__ = "observabilite/audit : archeologie, que faisait chaque vestige, phases 2 et 5"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH = os.path.join(ROOT, "sandbox", "archaeology.json")
MD_OUT = os.path.join(ROOT, "sandbox", "forgotten_capabilities.md")

# Source UNIQUE du helper git : Phase 1 (forge_archaeology). On ne le redefinit
# pas ici -- le cliquet de duplication a (a juste titre) attrape la copie.
import sys as _sys
if os.path.join(ROOT, "tools") not in _sys.path:
    _sys.path.insert(0, os.path.join(ROOT, "tools"))
from nokido_agent.tools.forge_archaeology import _git  # noqa: E402

# Mots-cles -> couche biomimetique. Un vestige qui touche l'organisme auto-regule
# prime (owner : renforcer l'organisme, pas ajouter des features).
_BIOMIMETIC = {
    "PERCEPTION": ("sensor", "probe", "perceive", "vitals", "capteur", "scan", "sniff", "snif"),
    "MEMORY": ("memory", "memoire", "rag", "recall", "remember", "hippocamp", "embed"),
    "HOMEOSTASIS": ("homeostas", "regulat", "resource", "evict", "balance", "throttle"),
    "METABOLISM": ("metabol", "energy", "cost", "budget", "allocat"),
    "LEARNING": ("learn", "reward", "policy", "train", "fitness", "evolv", "mutation"),
    "PLANNING": ("plan", "goap", "strateg", "orchestrat", "route", "dispatch"),
    "ACTION": ("execut", "runner", "action", "effector", "apply"),
    "IMMUNITY": ("firewall", "guard", "sanitiz", "integrity", "danger", "opsec", "secur"),
    "SELF_REPAIR": ("repair", "recover", "rescue", "heal", "restore", "retry"),
    "SELF_MODEL": ("world_model", "self", "introspec", "anatomy", "proprio"),
    "UI": ("ui", "dashboard", "web", "widget", "render", "view"),
}


def _contenu_avant_suppr(repo: str, sha: str, chemin: str) -> str | None:
    """Contenu du fichier JUSTE AVANT sa suppression : version au parent du
    commit qui l'a retire (`<sha>^:<chemin>`)."""
    rc, out = _git(repo, "show", f"{sha}^:{chemin}")
    return out if rc == 0 and out else None


def _resume_ast(code: str) -> dict:
    # Le vieux code contient des sequences d'echappement invalides (\d, \{) hors
    # raw-string : ast.parse emet un SyntaxWarning par occurrence. On les tait --
    # c'est du code d'archive, pas du code a corriger.
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arbre = ast.parse(code)
    except SyntaxError:
        return {"parse": False, "loc": code.count("\n") + 1}
    funcs = [n.name for n in ast.walk(arbre)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n.name for n in ast.walk(arbre) if isinstance(n, ast.ClassDef)]
    doc = (ast.get_docstring(arbre) or "").strip().splitlines()
    return {"parse": True, "loc": code.count("\n") + 1,
            "n_func": len(funcs), "n_class": len(classes),
            "doc1": doc[0][:160] if doc else "",
            "symboles": (classes + funcs)[:10]}


def _couches(nom: str, doc: str, symboles: list) -> list[str]:
    hay = (nom + " " + doc + " " + " ".join(symboles)).lower()
    return [c for c, mots in _BIOMIMETIC.items() if any(m in hay for m in mots)]


def _score_recovery(m: dict, ast_: dict, couches: list) -> float:
    """0..1. DELETED (vraiment parti) prime ; substantiel ; documente ; porteur
    d'une capacite biomimetique. Un MOVED/REPLACED survit ailleurs -> moins urgent."""
    s = 0.0
    s += {"DELETED": 0.4, "MOVED": 0.15, "REPLACED": 0.1}.get(m.get("etat"), 0.0)
    n = ast_.get("n_func", 0) + 2 * ast_.get("n_class", 0)
    s += min(0.3, n * 0.02)                    # richesse
    if ast_.get("doc1"):
        s += 0.15                               # documente = intention lisible
    if couches:
        s += min(0.15, 0.08 * len(couches))     # valeur biomimetique
    return round(min(1.0, s), 3)


def enrichir(depots: dict[str, str], maxn: int) -> dict:
    with open(ARCH, encoding="utf-8") as fh:
        arch = json.load(fh)
    reels = [m for m in arch.get("modules", []) if m.get("etat") != "NOISE"]
    traites, capes = 0, 0
    enrichis = []
    for m in reels:
        if traites >= maxn:
            capes += 1
            continue
        repo = depots.get(m.get("depot"))
        if not repo:
            continue
        code = _contenu_avant_suppr(repo, m.get("sha_suppr", ""), m.get("chemin", ""))
        if code is None:
            continue
        a = _resume_ast(code)
        couches = _couches(m.get("chemin", ""), a.get("doc1", ""), a.get("symboles", []))
        m2 = {**m, "ast": a, "couches": couches,
              "score_recovery": _score_recovery(m, a, couches)}
        enrichis.append(m2)
        traites += 1
    enrichis.sort(key=lambda x: x["score_recovery"], reverse=True)
    return {"enrichis": traites, "capes": capes, "total_reels": len(reels),
            "modules": enrichis}


def _ecrire_md(res: dict, top: int) -> None:
    lignes = ["# Capacites oubliees — top candidats a reevaluer",
              "",
              f"_{res['enrichis']} vestiges enrichis"
              + (f" ({res['capes']} au-dela du plafond, NON traites)" if res["capes"] else "")
              + ". Analyse pure — aucune reintegration automatique._", ""]
    for m in res["modules"][:top]:
        a = m.get("ast", {})
        couches = ", ".join(m.get("couches", [])) or "—"
        lignes.append(f"## {m['depot']}:{m['chemin']}  ({m['etat']}, score {m['score_recovery']})")
        lignes.append(f"- supprime le {m.get('date_suppr')} — « {m.get('msg_suppr', '')} »")
        if m.get("vit_dans"):
            lignes.append(f"- vit encore dans : {m['vit_dans']}")
        lignes.append(f"- {a.get('n_class', 0)} classe(s), {a.get('n_func', 0)} fonction(s), "
                      f"{a.get('loc', 0)} LOC — couches : {couches}")
        if a.get("doc1"):
            lignes.append(f"- intention : {a['doc1']}")
        if a.get("symboles"):
            lignes.append(f"- symboles : {', '.join(a['symboles'])}")
        lignes.append("")
    try:
        with open(MD_OUT, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lignes))
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Archeologie Phases 2 & 5 (enrich + recovery)")
    ap.add_argument("--repos", nargs="*", default=[], help="nom=chemin des depots")
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    depots = {"nokido": ROOT}
    for spec in a.repos:
        if "=" in spec:
            n, p = spec.split("=", 1)
            depots[n] = p

    res = enrichir(depots, a.max)
    _ecrire_md(res, a.top)
    if a.json:
        print(json.dumps({k: v for k, v in res.items() if k != "modules"},
                         ensure_ascii=False))
        return 0
    print(f"[enrich] {res['enrichis']} enrichis / {res['total_reels']} reels"
          + (f" ({res['capes']} au-dela du plafond {a.max})" if res["capes"] else ""))
    print(f"[enrich] top {a.top} candidats a recuperer :")
    for m in res["modules"][:a.top]:
        c = ",".join(m.get("couches", [])) or "-"
        print(f"  {m['score_recovery']:<5} [{m['etat']:<8}] {m['depot']}:{m['chemin']}"
              f"  ({c})")
    print(f"[enrich] ecrit : {os.path.relpath(MD_OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
