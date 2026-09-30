#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_dup_detector.py — duplication de code, par STRUCTURE.

Le seul axe que la CI ne couvrait pas (mesure du 2026-08-15 : aucun detecteur
de duplication dans app/ ni tools/, sur cinq motifs cherches). C'est pourtant
la dette qui grossit le plus vite sur un depot long : un correctif applique a
une copie et pas aux trois autres redevient un bug, et personne ne sait qu'il
existait trois autres copies.

Methode : empreinte de la STRUCTURE d'une fonction, variables normalisees. Deux
fonctions identiques au renommage pres portent la meme empreinte -- c'est le
copier-coller qu'on veut voir, pas la ressemblance vague. Aucun modele, aucun
service, aucun binaire externe : cela doit tourner partout, y compris sous le
compte de service ou semgrep refuse de demarrer.

Usage :
    forge_dup_detector.py [chemin ...] [--min-noeuds 25] [--json]
    forge_dup_detector.py --socle | --ecrire-socle    # cliquet anti-nouveau clone
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : duplication de code par structure"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCLE = os.path.join(ROOT, "tests", "nr", "duplication_socle.json")

# `backups/` contient des copies horodatees du MEME fichier (auto_boot_2026...) :
# les compter comme des clones remplit le rapport de 400 groupes qui ne sont pas
# de la duplication mais de l'archivage. `legacy/` reste analyse : un clone entre
# le code vivant et son ancetre est precisement ce qu'on veut voir.
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "_attic", "node_modules",
              "site-packages", ".semgrep_home", "_archive", "shadow_mutation",
              "backups", "_backups"}

# En dessous, on capture des accesseurs et des `return self._x` : du bruit qui
# noierait les vrais blocs recopies.
MIN_NOEUDS = 25

# Plafond du motif << adaptateur d'entree >> ci-dessous. Sans lui, une grosse
# fonction de meme FORME sortirait du radar : mesure du 2026-09-12, le predicat
# sans plafond captait aussi `forge_suite_pure_triage._compte_tests` (58 noeuds).
# Avec le plafond, la portee sur app + tools est de DEUX fonctions, exactement.
PLAFOND_ADAPTATEUR = 30


class _Normaliseur(ast.NodeTransformer):
    """Efface l'identite des variables, garde la forme du code.

    Les attributs (`os.path.join`) sont CONSERVES : deux fonctions qui appellent
    des services differents ne sont pas des clones, meme a structure egale.
    """

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id="V", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return ast.copy_location(ast.arg(arg="A", annotation=None), node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        # Le TYPE distingue encore `0` de `"sql"` ; la valeur, elle, varie trop
        # d'une copie a l'autre pour servir d'identite.
        return ast.copy_location(ast.Constant(value=type(node.value).__name__), node)


def _corps_utile(fn: ast.AST) -> list:
    corps = list(getattr(fn, "body", []))
    if (corps and isinstance(corps[0], ast.Expr)
            and isinstance(getattr(corps[0], "value", None), ast.Constant)
            and isinstance(corps[0].value.value, str)):
        corps = corps[1:]  # docstring : commentaire, pas comportement
    return corps


def empreinte(fn: ast.AST) -> tuple[str, int]:
    """(signature structurelle, nombre de noeuds) du corps d'une fonction."""
    corps = _corps_utile(fn)
    module = ast.Module(body=[ast.fix_missing_locations(n) for n in corps], type_ignores=[])
    module = _Normaliseur().visit(module)
    ast.fix_missing_locations(module)
    dump = ast.dump(module, annotate_fields=False)
    taille = sum(1 for _ in ast.walk(module))
    return hashlib.sha1(dump.encode("utf-8")).hexdigest()[:16], taille


# Racine de reference pour les chemins rapportes. Surchargeable par --racine :
# c'est ce qui permet de rejouer le detecteur sur un etat PASSE du depot (git
# worktree) et d'obtenir des cles comparables au socle actuel. Sans cela, un
# backtest ne produit que des chemins absolus, donc incomparables.
RACINE = ROOT


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, RACINE).replace("\\", "/")
    except ValueError:  # cible sur un autre volume (le RAG vit sur V:)
        return os.path.abspath(path).replace("\\", "/")


def _scratch(nom: str) -> bool:
    return nom.startswith(("_", "tmp_")) and nom != "__init__.py"


def collect(paths: list[str]) -> list[str]:
    files: list[str] = []
    for p in paths:
        target = p if os.path.isabs(p) else os.path.join(ROOT, p)
        if os.path.isfile(target):
            files.append(target)
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            files += [os.path.join(dirpath, f) for f in filenames
                      if f.endswith(".py") and not _scratch(f)]
    return files


_MARQUEURS_GENERE = ("genere par", "généré par", "generated by", "auto-generated",
                     "do not edit", "ne pas editer")


def _est_genere(src: str) -> bool:
    """Fichier produit par une moulinette : sa ressemblance n'est pas de la dette.

    Les 46 formulaires de app/web_hub/forms/ s'annoncent « GENERE par
    forge_ui_sweep (moulinette deterministe) ». Les compter comme des clones
    ferait accuser le generateur de faire son travail -- et un nouveau tool,
    donc un nouveau formulaire, romprait le cliquet sans qu'aucune dette
    n'ait ete creee.
    """
    tete = src[:400].lower()
    return any(m in tete for m in _MARQUEURS_GENERE)


def est_adaptateur_entree(fn, taille: int) -> bool:
    """Une fonction qui PARSE une entree et DELEGUE, sans logique propre.

    Forme reconnue, et rien d'autre :

        try:
            V = appel()
        except ...:
            return CONSTANTE
        return appel(V)

    Ni branche metier, ni boucle, ni calcul. Deux programmes independants
    ecrivent forcement le meme -- c'est un point d'entree, pas de la dette.

    POURQUOI CE CRITERE, et pas une liste de fichiers ni un seuil deplace.
    Decision owner du 2026-09-12 : le cliquet a rompu sur les six lignes de
    `main()` communes a `hook_context_firewall` et `hook_tool_budget_gate`.
    Deux gardes INDEPENDANTS, chacun devant survivre a la panne de l'autre :
    les factoriser dans un helper leur donnerait un failure domain COMMUN.
    Et monter MIN_NOEUDS de 25 a 26 -- le boilerplate pese exactement 25 --
    aurait retire QUATRE groupes de la surveillance, dont trois etrangers au
    probleme : un seuil deplace pour un cas precis est une liste d'exceptions
    qui s'ignore.

    Le cliquet continue de mordre sur tout le reste : cf. NR
    `tests/nr/test_dup_adaptateur_entree_nr.py`, qui verrouille la portee.
    """
    if taille > PLAFOND_ADAPTATEUR:
        return False
    corps = [n for n in fn.body
             if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                     and isinstance(n.value.value, str))]
    if len(corps) != 2:
        return False
    essai, fin = corps
    if not isinstance(essai, ast.Try) or not isinstance(fin, ast.Return):
        return False
    if not isinstance(fin.value, ast.Call):
        return False
    if len(essai.body) != 1 or not isinstance(essai.body[0], ast.Assign):
        return False
    if not isinstance(essai.body[0].value, ast.Call):
        return False
    if len(essai.handlers) != 1 or essai.orelse or essai.finalbody:
        return False
    gestionnaire = essai.handlers[0]
    return (len(gestionnaire.body) == 1
            and isinstance(gestionnaire.body[0], ast.Return)
            and isinstance(gestionnaire.body[0].value, ast.Constant))


def scanner(paths: list[str], min_noeuds: int = MIN_NOEUDS) -> dict:
    par_empreinte: dict[str, list[dict]] = {}
    lus = 0
    for f in collect(paths):
        try:
            src = open(f, encoding="utf-8", errors="replace").read()
            tree = ast.parse(src, filename=f)
        except (OSError, SyntaxError):
            continue  # signale ailleurs (golden_rules_ast) ; ici on compte ce qu'on lit
        if _est_genere(src):
            continue
        lus += 1
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            sig, taille = empreinte(node)
            if taille < min_noeuds:
                continue
            if est_adaptateur_entree(node, taille):
                continue  # boilerplate d'entree : duplication structurelle admise
            par_empreinte.setdefault(sig, []).append(
                {"fichier": _rel(f), "fonction": node.name,
                 "ligne": node.lineno, "noeuds": taille})
    groupes = [{"empreinte": k, "copies": v, "noeuds": v[0]["noeuds"]}
               for k, v in par_empreinte.items() if len(v) > 1]
    groupes.sort(key=lambda g: (-g["noeuds"], -len(g["copies"])))
    return {"fichiers_lus": lus, "groupes": groupes,
            "fonctions_en_double": sum(len(g["copies"]) - 1 for g in groupes)}


def _cle(groupe: dict) -> str:
    """Identite d'un groupe : les fichiers concernes, jamais les lignes."""
    return "|".join(sorted({c["fichier"] for c in groupe["copies"]}))


def groupes_nouveaux(cles: list, gele: set) -> tuple:
    """(nouveaux, retrecis). Un groupe dont les fichiers forment un SOUS-ENSEMBLE STRICT
    d'un groupe gele n'est pas nouveau : c'est un groupe qui a perdu un membre — quelqu'un
    a DE-CLONE une copie. Mesure 2026-08-26 : `_get_conn` de forge_epistemic_retrieve
    retire d'un groupe de 4 -> le cliquet rougissait la CI sur les 3 restants, lus comme
    un groupe neuf. Punir la reduction d'un clone est l'inverse de ce que le cliquet
    protege."""
    geles = [set(k.split("|")) for k in gele]
    nouveaux, retrecis = [], []
    for k in cles:
        fichiers = set(k.split("|"))
        # Le sous-ensemble STRICT se teste AVANT l'identite : ecarter d'abord les
        # cles gelees rendait `<=` indiscernable de `<` (mutant equivalent, releve par
        # le cliquet de mutation le 2026-08-26). Ici un `<=` classerait un groupe
        # identique en « retreci », et le test le voit.
        if any(fichiers < g for g in geles):
            retrecis.append(k)
        elif k in gele:
            continue
        else:
            nouveaux.append(k)
    return nouveaux, retrecis


def main() -> int:
    ap = argparse.ArgumentParser(description="Duplication de code Nokido (AST)")
    ap.add_argument("paths", nargs="*", default=None)
    ap.add_argument("--min-noeuds", type=int, default=MIN_NOEUDS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--socle", action="store_true",
                    help="cliquet : echoue si un groupe de clones NOUVEAU apparait")
    ap.add_argument("--ecrire-socle", action="store_true")
    ap.add_argument("--racine", default=None,
                    help="racine des chemins rapportes (backtest sur un worktree)")
    args = ap.parse_args()

    if args.racine:
        global RACINE
        RACINE = os.path.abspath(args.racine)

    res = scanner(args.paths or ["app", "tools"], args.min_noeuds)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0

    print(f"[dup] fichiers_lus={res['fichiers_lus']} "
          f"groupes={len(res['groupes'])} fonctions_en_double={res['fonctions_en_double']}")
    if not res["fichiers_lus"]:
        print("ABORT: 0 fichier analyse")
        return 3

    cles = sorted({_cle(g) for g in res["groupes"]})
    if args.ecrire_socle:
        os.makedirs(os.path.dirname(SOCLE), exist_ok=True)
        with open(SOCLE, "w", encoding="utf-8") as fh:
            json.dump({"genere_par": "tools/forge_dup_detector.py --ecrire-socle",
                       "min_noeuds": args.min_noeuds, "groupes": cles},
                      fh, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"[dup] socle ecrit : {os.path.relpath(SOCLE, ROOT)} ({len(cles)} groupes geles)")
        return 0

    if args.socle:
        try:
            with open(SOCLE, encoding="utf-8") as fh:
                gele = set(json.load(fh).get("groupes", []))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ABORT: socle illisible ({exc}) — regenerer avec --ecrire-socle")
            return 3
        neuf, retrecis = groupes_nouveaux(cles, gele)
        if retrecis:
            print(f"[dup] {len(retrecis)} groupe(s) RETRECI(s) (un clone de moins, sous-ensemble "
                  f"d'un groupe gele) — pas une regression ; regeler avec --ecrire-socle")
        if not neuf:
            print("[dup] cliquet OK — aucun groupe de clones nouveau")
            return 0
        print(f"[dup] CLIQUET ROMPU — {len(neuf)} groupe(s) de clones nouveau(x) :")
        for k in neuf[:20]:
            print("  + " + k)
        return 1

    for g in res["groupes"][:args.top]:
        lieux = ", ".join(f"{c['fichier']}:{c['ligne']} {c['fonction']}()"
                          for c in g["copies"][:4])
        suite = f" (+{len(g['copies']) - 4})" if len(g["copies"]) > 4 else ""
        print(f"  [{g['noeuds']:4d} noeuds x{len(g['copies'])}] {lieux}{suite}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
