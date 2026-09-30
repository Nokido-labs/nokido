#!/usr/bin/env python3
"""forge_pypi_baseline.py — PHASE 3 : l'etat AVANT, mesure et rejouable.

La migration se juge sur un DELTA. Sans baseline prise avant la premiere
transformation, « on a bien avance » n'est pas une mesure.

ANTI-DUP ASSUME. Ce module ne reconstruit AUCUN analyseur : il appelle
`forge_syspath_cartography` (carte des sys.path par intention, avec sa ventilation
et ses denominateurs) et se contente d'ajouter le comptage des IMPORTS, que la
carte ne fait pas. Meme perimetre, meme enumeration, memes exclusions — deux
cartes du meme corps qui divergeraient seraient pires qu'une seule.

TROIS FAMILLES D'IMPORT, parce qu'elles n'appellent pas le meme geste :

    PLAT_INTERNE    `import forge_secrets`      -> casse une fois installe
    PACKAGE         `from app.forge_x import y` -> deja compatible wheel
    EXTERNE         `import numpy`              -> hors sujet, ne pas toucher

Le premier est la dette. Le deuxieme est la cible. Le troisieme est un piege : il
n'a pas de point et n'est pas stdlib, donc il RESSEMBLE au premier — confusion
payee le 2026-09-10 sur la premiere carte.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : baseline avant/apres de la migration namespace"

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_syspath_cartography as carto  # noqa: E402

SORTIE = ROOT / "sandbox" / "chantier_pypi" / "baseline.json"
# Le namespace CIBLE compte comme PACKAGE : c'est la forme d'arrivee de la
# migration. L'omettre faisait classer `nokido_agent.app.forge_x` en EXTERNE, et
# le delta ressemblait a une explosion de dependances tierces (+2 008) au moment
# meme ou la dette baissait de 1 976. Un instrument qui ne connait pas sa cible
# rend le progres illisible.
PREFIXES_PACKAGE = ("app.", "tools.", "recon_silo.", "nokido_agent.")


def classer_import(nom: str, internes: set[str]) -> str:
    """PLAT_INTERNE / PACKAGE / EXTERNE — l'inconnu va vers EXTERNE.

    Liste BLANCHE : n'est `PLAT_INTERNE` que ce qui est PROUVE porte par le depot.
    """
    if nom.startswith(PREFIXES_PACKAGE):
        return "PACKAGE"
    if "." in nom:
        return "EXTERNE"
    if nom in sys.stdlib_module_names:
        return "EXTERNE"
    return "PLAT_INTERNE" if nom in internes else "EXTERNE"


def compter_imports(sources: dict[str, str], internes: set[str]) -> dict:
    """Compte par famille, avec le nombre de FICHIERS touches et les illisibles."""
    par_famille = {"PLAT_INTERNE": 0, "PACKAGE": 0, "EXTERNE": 0}
    fichiers_par_famille: dict[str, set[str]] = {k: set() for k in par_famille}
    top: dict[str, int] = {}
    illisibles: list[str] = []

    for nom_fichier, src in sources.items():
        try:
            arbre = ast.parse(src, filename=nom_fichier)
        except (SyntaxError, ValueError, RecursionError):
            illisibles.append(nom_fichier)
            continue
        for noeud in ast.walk(arbre):
            cibles: list[str] = []
            if isinstance(noeud, ast.Import):
                cibles = [a.name for a in noeud.names]
            elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
                cibles = [noeud.module]
            for cible in cibles:
                famille = classer_import(cible, internes)
                par_famille[famille] += 1
                fichiers_par_famille[famille].add(nom_fichier)
                if famille == "PLAT_INTERNE":
                    top[cible] = top.get(cible, 0) + 1

    return {
        "occurrences": par_famille,
        "fichiers": {k: len(v) for k, v in fichiers_par_famille.items()},
        "illisibles": len(illisibles),
        "fichiers_illisibles": illisibles,
        "top_plats": sorted(top.items(), key=lambda kv: -kv[1])[:25],
        "modules_plats_distincts": len(top),
    }


def baseline(racine: Path | None = None) -> dict:
    base = racine or ROOT
    sources = carto._fichiers(base)          # meme enumeration que la carte
    internes = carto.modules_depot(base)
    carte = carto.cartographier_textes(sources)
    imports = compter_imports(sources, internes)

    return {
        "racine": str(base),
        "fichiers_lus": carte["fichiers_lus"],
        "modules_du_depot": len(internes),
        "imports": imports,
        "syspath": {
            "sites": carte["sites"],
            "par_portee": carte["par_portee"],
            "par_verdict": carte["par_verdict"],
            "par_motif": carte["par_motif"],
            "ventilation": carte["ventilation"],
        },
        "certifiant": bool(internes) and carte["fichiers_lus"] > 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", default=str(SORTIE))
    ap.add_argument("--etiquette", default="avant", help="avant | apres | <libre>")
    args = ap.parse_args()

    mesure = baseline()
    mesure["etiquette"] = args.etiquette

    if not mesure["certifiant"]:
        print("[baseline] NON_CERTIFIANT — denominateur vide (0 module ou 0 fichier)")
        return 2

    i = mesure["imports"]
    print(f"[baseline:{args.etiquette}] {mesure['fichiers_lus']} fichiers, "
          f"{mesure['modules_du_depot']} modules du depot, {i['illisibles']} illisible(s)")
    print("  imports (occurrences | fichiers)")
    for famille in ("PLAT_INTERNE", "PACKAGE", "EXTERNE"):
        print(f"    {famille:<14} {i['occurrences'][famille]:>6} | {i['fichiers'][famille]:>5}")
    print(f"    modules plats distincts : {i['modules_plats_distincts']}")
    s = mesure["syspath"]
    print(f"  sys.path {s['sites']} sites — " +
          ", ".join(f"{k}={v}" for k, v in s["par_verdict"].items()))

    cible = Path(args.json)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(mesure, indent=2), encoding="utf-8")
    print(f"  -> {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
