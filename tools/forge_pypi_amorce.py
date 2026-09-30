#!/usr/bin/env python3
"""forge_pypi_amorce.py — le namespace doit etre atteignable DES LE DEMARRAGE.

DEFAUT MESURE le 2026-09-10, apres la migration des imports.

`ci_local.py` porte bien `sys.path.insert(0, str(ROOT))` — mais AUX LIGNES 1263 ET
3133, a l'interieur de fonctions. L'import migre, lui, vit dans
`_mesure_pip_audit_deportee()`, qui n'en a pas :

    from nokido_agent.tools.forge_deps_reconcilier import rapport_courant
    -> ModuleNotFoundError
    -> gate pip-audit : « selection du rapport indisponible »

Un import migre place dans une fonction depend d'une redirection faite dans UNE
AUTRE fonction, peut-etre jamais appelee. Le `sys.path` d'un processus n'est pas
un contrat entre fonctions.

OU L'AMORCE DOIT VIVRE. Au POINT D'ENTREE du processus, une fois pour toutes :

    entry points console  -> le paquet est INSTALLE, rien a faire (mesure PHASE 8)
    pytest                -> le rootdir est deja dans `sys.path`
    `python tools/x.py`   -> `sys.path[0]` vaut `tools/` : LA racine manque

Ce module ne traite QUE le troisieme cas : les fichiers qui portent un
`if __name__ == "__main__"` ET qui utilisent le namespace.

CE QU'IL NE FAIT PAS. Il n'ajoute rien a un fichier qui n'en a pas besoin — un
module de bibliotheque tient son `sys.path` de son appelant, et lui poser une
amorce serait du bruit dans 900 fichiers. Il ne touche pas non plus a un fichier
qui a DEJA une amorce au niveau module : deux amorces ne valent pas mieux qu'une.

DRY-RUN PAR DEFAUT. `--appliquer` est explicite.
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

__FORGE_COLOR__ = "qualite/build : amorce du namespace aux points d entree"

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZONES = ("app", "tools")
NAMESPACE = "nokido_agent"
IGNORES = {"_attic", "node_modules", "backups", "archive"}

# Posee juste apres les imports de tete. Idempotente, silencieuse, sans
# dependance : elle doit fonctionner AVANT que quoi que ce soit du corps ne soit
# importable.
AMORCE = (
    "# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du\n"
    "# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`\n"
    "# leve ModuleNotFoundError quand ce fichier est lance par chemin.\n"
    "import sys as _sys_amorce\n"
    "from pathlib import Path as _Path_amorce\n"
    "_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)\n"
    "if _RACINE_AMORCE not in _sys_amorce.path:\n"
    "    _sys_amorce.path.insert(0, _RACINE_AMORCE)\n"
)


def _touche_par_ignores(chemin: Path, base: Path) -> bool:
    return any(p in IGNORES for p in chemin.relative_to(base).parts)


def _importe_le_namespace(noeud: ast.AST) -> bool:
    if isinstance(noeud, ast.ImportFrom):
        return (noeud.module or "").split(".")[0] == NAMESPACE and not noeud.level
    if isinstance(noeud, ast.Import):
        return any(a.name.split(".")[0] == NAMESPACE for a in noeud.names)
    return False


def _premier_import_du_namespace(arbre: ast.Module):
    """Ligne du 1er import `nokido_agent` execute A L'IMPORT (niveau module), ou None."""
    for noeud in arbre.body:
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for interne in ast.walk(noeud):
            if _importe_le_namespace(interne):
                return interne.lineno
    return None


def _boucle_sur_zones(noeud: ast.AST) -> bool:
    """`for sub in ("app", "tools"): ...` : n'insere que des ZONES, quelle que soit la variable."""
    if not isinstance(noeud, ast.For) or not isinstance(noeud.iter, (ast.Tuple, ast.List)):
        return False
    valeurs = [e.value for e in noeud.iter.elts if isinstance(e, ast.Constant)]
    return bool(valeurs) and len(valeurs) == len(noeud.iter.elts) and all(v in ZONES for v in valeurs)


def a_une_amorce_racine(arbre: ast.Module) -> bool:
    """Le module met-il la RACINE dans `sys.path` au niveau MODULE ?

    On ne cherche pas n'importe quel `sys.path` : une insertion de `app/` ou
    `tools/` ne rend pas le namespace atteignable. C'est la distinction qui a
    coute le defaut : `ci_local.py` avait deux insertions de racine, mais dans
    des fonctions.
    """
    # L'ORDRE compte (2026-09-25) : une amorce qui s'execute APRES l'import du namespace ne
    # repare rien. L'instrument l'ignorait et declarait « deja amorces » 42 fichiers qui
    # mouraient a l'import quand on les lancait par chemin -- dont deux producteurs d'examens
    # du corps, figes 15 et 28 jours.
    limite = _premier_import_du_namespace(arbre)
    for noeud in arbre.body:                    # niveau MODULE uniquement
        # NE PAS descendre dans les fonctions : c'est precisement le defaut que
        # ce module corrige. `ci_local.py` a DEUX `sys.path.insert(0, str(ROOT))`
        # — dans des fonctions — et le namespace y reste introuvable tant que
        # ces fonctions ne sont pas appelees. `ast.walk` les aurait comptees, et
        # l'instrument aurait declare « deja amorce » 513 fichiers a tort.
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if limite is not None and noeud.lineno >= limite:
            break
        if _boucle_sur_zones(noeud):
            continue
        for interne in ast.walk(noeud):
            if not isinstance(interne, ast.Call):
                continue
            f = interne.func
            if not (isinstance(f, ast.Attribute) and f.attr in ("insert", "append")):
                continue
            cible = ast.unparse(f.value) if hasattr(ast, "unparse") else ""
            if "sys.path" not in cible and "path" not in cible:
                continue
            arg = ast.unparse(interne.args[-1]) if interne.args else ""
            # Une insertion qui se termine par une ZONE ne suffit pas.
            if any(arg.rstrip(")\"' ").endswith(z) for z in ZONES):
                continue
            return True
    return False


def candidats() -> list[Path]:
    """Points d'entree utilisant le namespace. Denominateur du traitement."""
    trouves: list[Path] = []
    for zone in ZONES:
        base = ROOT / zone
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            if _touche_par_ignores(chemin, base):
                continue
            src = chemin.read_text(encoding="utf-8", errors="replace")
            if NAMESPACE not in src or "__main__" not in src:
                continue
            trouves.append(chemin)
    return sorted(trouves)


def _point_d_insertion(arbre: ast.Module, lignes: list[str]) -> int:
    """Apres le docstring et les imports de tete — jamais avant `from __future__`, et
    toujours AVANT le premier import du namespace (2026-09-25 : posee apres, elle ne
    reparait rien -- cause de la mort de forge_memory_compactor le 2026-09-11)."""
    ligne = 0
    for noeud in arbre.body:
        if isinstance(noeud, ast.Expr) and isinstance(noeud.value, ast.Constant):
            ligne = noeud.end_lineno or ligne
            continue
        if _importe_le_namespace(noeud):
            break
        if isinstance(noeud, (ast.Import, ast.ImportFrom)):
            ligne = noeud.end_lineno or ligne
            continue
        break
    return ligne


def traiter(appliquer: bool = False) -> dict:
    rapport = {"candidats": 0, "deja_amorces": 0, "traites": 0,
               "illisibles": [], "detail": []}
    for chemin in candidats():
        rapport["candidats"] += 1
        src = chemin.read_text(encoding="utf-8", errors="replace")
        try:
            arbre = ast.parse(src, filename=str(chemin))
        except (SyntaxError, ValueError):
            rapport["illisibles"].append(str(chemin))
            continue
        if a_une_amorce_racine(arbre):
            rapport["deja_amorces"] += 1
            continue
        lignes = src.splitlines(keepends=True)
        pos = _point_d_insertion(arbre, lignes)
        nouveau = "".join(lignes[:pos]) + "\n" + AMORCE + "".join(lignes[pos:])
        try:
            ast.parse(nouveau, filename=str(chemin))   # jamais ecrire du non-parsable
        except SyntaxError as exc:
            rapport["illisibles"].append(f"{chemin} (apres amorce: {exc})")
            continue
        rapport["traites"] += 1
        rapport["detail"].append(str(chemin.relative_to(ROOT)).replace("\\", "/"))
        if appliquer:
            chemin.write_text(nouveau, encoding="utf-8")
    return rapport


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--appliquer", action="store_true", help="ECRIT (defaut : dry-run)")
    ap.add_argument("--json", default=str(ROOT / "sandbox" / "chantier_pypi" / "amorce.json"))
    args = ap.parse_args()

    rapport = traiter(args.appliquer)
    if rapport["candidats"] == 0:
        print("[amorce] NON_CERTIFIANT — aucun candidat : denominateur vide")
        return 2

    mode = "APPLIQUE" if args.appliquer else "dry-run"
    print(f"[amorce] {mode} — {rapport['candidats']} point(s) d'entree utilisant le "
          f"namespace, {rapport['deja_amorces']} deja amorce(s), "
          f"{rapport['traites']} a traiter, {len(rapport['illisibles'])} illisible(s)")
    for f in rapport["detail"][:12]:
        print(f"    {f}")
    cible = Path(args.json)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
    print(f"  -> {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
