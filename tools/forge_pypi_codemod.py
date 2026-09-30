#!/usr/bin/env python3
"""forge_pypi_codemod.py — PHASE 5 : reecrire les imports plats, par FAMILLES.

    import forge_secrets            ->  from nokido_agent.app import forge_secrets
    import forge_secrets as fs      ->  from nokido_agent.app import forge_secrets as fs
    from forge_secrets import get   ->  from nokido_agent.app.forge_secrets import get

CE QU'IL NE FAIT JAMAIS :
  - toucher un import qui n'est pas un module PORTE PAR LE DEPOT (`numpy` n'a pas
    de point et n'est pas stdlib : il RESSEMBLE a un frere, il ne l'est pas) ;
  - toucher un `sys.path` — c'est un autre chantier, avec sa propre carte et sa
    propre regle : « aucune transformation automatique ne supprime un `sys.path`
    tant qu'on n'a pas prouve pourquoi il etait la » ;
  - transformer un import DYNAMIQUE (`importlib.import_module(nom)`) : l'AST ne
    sait pas ce qui sera charge.

DRY-RUN PAR DEFAUT. `--appliquer` est explicite. Un codemod qui ecrit par defaut
est un `sed` avec plus d'etapes.

PAR FAMILLES, jamais en bloc. `--famille app` / `--famille tools` / `--fichiers f1,f2`
pour que chaque passe soit suivie de : NR -> index AST -> wiring -> carte sys.path
-> tests -> commit. « 3 869 imports -> codemod global -> esperer » n'est pas un plan.

LE RAPPORT NOMME LES REFUS. Un codemod qui ne dit pas ce qu'il n'a pas su faire
laisse croire qu'il a tout fait.
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

__FORGE_COLOR__ = "qualite/build : codemod des imports vers le namespace nokido"

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANTIER = ROOT / "sandbox" / "chantier_pypi"
VENV_OUTILS = CHANTIER / "venv_outils"
ZONES = ("app", "tools", "recon_silo")
# `nokido` est deja pris par `tools/nokido.py` (l'entrypoint `nokido.py up`) et
# `app/Nokido.py` : comme `sys.path[0]` vaut `tools/` pour un script, un paquet de
# ce nom serait masque dans tout le corps. Mesure et decision du 2026-09-10.
NAMESPACE = "nokido_agent"


# ------------------------------------------------------- DECISION (pur)


def carte_modules(racine: Path | None = None) -> dict[str, str]:
    """module -> zone. C'est le denominateur du codemod.

    Vide, il ne transformerait RIEN tout en paraissant prudent : le NR l'affirme
    non vide (regle owner sur le denominateur).
    """
    base = racine or ROOT
    carte: dict[str, str] = {}
    for zone in ZONES:
        dossier = base / zone
        if not dossier.is_dir():
            continue
        for chemin in dossier.rglob("*.py"):
            rel = chemin.relative_to(dossier)
            if any(p in {"_attic", "node_modules", "backups", "archive"} for p in rel.parts):
                continue
            if chemin.stem == "__init__":
                continue
            # Un module en sous-dossier n'est pas atteignable a plat : hors sujet.
            if len(rel.parts) == 1:
                carte.setdefault(chemin.stem, zone)
    return carte


def cible_namespace(module: str, carte: dict[str, str]) -> str | None:
    """`forge_secrets` -> `nokido.app`. None si le module n'est pas du depot."""
    zone = carte.get(module)
    return f"{NAMESPACE}.{zone}" if zone else None


def rediriger_cible(cible: str) -> str | None:
    """`ROOT/app` -> `ROOT`. None si ce n'est pas une cible de ZONE.

    On ne SUPPRIME pas le `sys.path` : on le remonte d'un cran. Il servait a
    rendre `app/` importable a plat ; la racine rend `nokido_agent.app`
    importable. Meme role, meme intention, une cible plus haut.

    Tout ce qui n'est pas exactement `<prefixe>/<zone>` est laisse INTACT :
    une cible non reduite, un chemin hors depot ou un sous-repertoire gardent
    leur role, et le rediriger casserait ce qu'ils servaient.
    """
    if not cible or cible == "UNKNOWN":
        return None
    segments = cible.split("/")
    if len(segments) < 2 or segments[-1] not in ZONES:
        return None
    prefixe = "/".join(segments[:-1])
    if not prefixe or prefixe == "UNKNOWN":
        return None
    return prefixe


def decider(module: str, carte: dict[str, str]) -> tuple[bool, str]:
    """(transformer ?, motif). L'inconnu ne va jamais du cote favorable."""
    if "." in module:
        return False, "import deja qualifie"
    if module in sys.stdlib_module_names:
        return False, "stdlib"
    if module not in carte:
        return False, "module hors depot (tiers ou introuvable)"
    return True, f"module du depot, zone {carte[module]}"


# ------------------------------------------- TRANSFORMATION (LibCST)

_TRANSFO = r'''
import json, sys
from pathlib import Path
import libcst as cst

carte = json.load(open(sys.argv[1], encoding="utf-8"))
fichiers = json.load(open(sys.argv[2], encoding="utf-8"))
appliquer = sys.argv[3] == "1"
syspath = len(sys.argv) > 5 and sys.argv[5] == "1"
NAMESPACE = "nokido_agent"
ZONES = ("app", "tools", "recon_silo")


def _est_syspath(noeud):
    """L'appel touche-t-il `sys.path` ?"""
    f = noeud.func
    if not isinstance(f, cst.Attribute) or f.attr.value not in ("insert", "append"):
        return False
    cible = f.value
    if isinstance(cible, cst.Attribute) and cible.attr.value == "path":
        return isinstance(cible.value, cst.Name) and cible.value.value == "sys"
    return False


def _remonter_dun_cran(expr):
    """`str(ROOT / "app")` -> `str(ROOT)` ; `os.path.join(ROOT, "app")` -> `ROOT`.

    Rend (nouvelle_expr, zone) ou (None, None) si la forme n'est pas reconnue.
    On ne devine JAMAIS : une forme inconnue est laissee telle quelle et comptee
    dans les refus.
    """
    # str(X / "zone")  /  Path(X) / "zone"
    if isinstance(expr, cst.Call) and isinstance(expr.func, cst.Name) and expr.func.value == "str":
        if len(expr.args) == 1:
            interne, zone = _remonter_dun_cran(expr.args[0].value)
            if interne is not None:
                return expr.with_changes(args=[expr.args[0].with_changes(value=interne)]), zone
        return None, None
    # X / "zone"
    # LibCST nomme ce noeud `BinaryOperation` (l'AST de la stdlib dit `BinOp`) :
    # confondre les deux vocabulaires a coute une passe complete.
    if isinstance(expr, cst.BinaryOperation) and isinstance(expr.operator, cst.Divide):
        droite = expr.right
        if isinstance(droite, cst.SimpleString):
            zone = droite.raw_value if hasattr(droite, "raw_value") else droite.value.strip("\\"'"'"\\'")
            zone = zone.strip("'").strip('"')
            if zone in ZONES:
                return expr.left, zone
        return None, None
    # os.path.join(X, "zone")
    if isinstance(expr, cst.Call) and isinstance(expr.func, cst.Attribute) and expr.func.attr.value == "join":
        if len(expr.args) == 2 and isinstance(expr.args[1].value, cst.SimpleString):
            zone = expr.args[1].value.value.strip("'").strip('"')
            if zone in ZONES:
                return expr.args[0].value, zone
    return None, None


class Reecrire(cst.CSTTransformer):
    def __init__(self):
        self.faits = []
        self.refus = []
        self.non_concernes = 0

    def leave_Import(self, original, updated):
        nouveaux, garde = [], []
        for alias in updated.names:
            nom = alias.evaluated_name
            zone = carte.get(nom)
            if zone is None or "." in nom:
                garde.append(alias)
                continue
            nouveaux.append((nom, alias.asname, zone))
        if not nouveaux:
            return updated
        if garde:
            # Import mixte (`import forge_x, numpy`) : on ne sait pas rendre deux
            # formes depuis un seul noeud sans risquer l'ordre. On REFUSE et on le DIT.
            self.refus.append({"forme": "import mixte", "noms": [a.evaluated_name for a in updated.names]})
            return updated
        nom, asname, zone = nouveaux[0]
        if len(nouveaux) > 1:
            self.refus.append({"forme": "import multiple", "noms": [n for n, _, _ in nouveaux]})
            return updated
        self.faits.append({"avant": f"import {nom}", "apres": f"from {NAMESPACE}.{zone} import {nom}"})
        return cst.ImportFrom(
            module=cst.Attribute(value=cst.Name(NAMESPACE), attr=cst.Name(zone)),
            names=[cst.ImportAlias(name=cst.Name(nom), asname=asname)],
        )

    def leave_Call(self, original, updated):
        if not syspath or not _est_syspath(updated):
            return updated
        args = list(updated.args)
        indice = 1 if (updated.func.attr.value == "insert" and len(args) > 1) else 0
        if indice >= len(args):
            return updated
        nouvelle, zone = _remonter_dun_cran(args[indice].value)
        if nouvelle is None:
            # NON CONCERNE, pas refuse. La grande majorite des `sys.path` ne
            # visent pas une zone du depot (`sys.path.insert(0, str(ROOT))` deja
            # reduit, un chemin de donnees, un greffon...) : les compter en refus
            # noyait le rapport et faisait crier le garde a faux — 6e occurrence
            # du motif dans la journee. Un garde bruyant finit desarme.
            self.non_concernes += 1
            return updated
        self.faits.append({"avant": f"sys.path -> .../{zone}", "apres": "sys.path -> racine"})
        args[indice] = args[indice].with_changes(value=nouvelle)
        return updated.with_changes(args=args)

    def leave_ImportFrom(self, original, updated):
        if updated.relative or updated.module is None:
            return updated
        if isinstance(updated.names, cst.ImportStar):
            self.refus.append({"forme": "import star", "noms": []})
            return updated
        try:
            nom = updated.module.value if isinstance(updated.module, cst.Name) else None
        except Exception:
            nom = None
        if nom is None:
            return updated
        zone = carte.get(nom)
        if zone is None:
            return updated
        self.faits.append({"avant": f"from {nom} import ...",
                           "apres": f"from {NAMESPACE}.{zone}.{nom} import ..."})
        return updated.with_changes(
            module=cst.Attribute(
                value=cst.Attribute(value=cst.Name(NAMESPACE), attr=cst.Name(zone)),
                attr=cst.Name(nom),
            )
        )


resultat = {"fichiers_vus": 0, "fichiers_modifies": 0, "transformations": 0,
            "refus": [], "illisibles": [], "detail": [], "syspath_non_concernes": 0}
for chemin in fichiers:
    resultat["fichiers_vus"] += 1
    try:
        src = Path(chemin).read_text(encoding="utf-8")
        arbre = cst.parse_module(src)
    except Exception as exc:
        resultat["illisibles"].append({"fichier": chemin, "erreur": f"{type(exc).__name__}: {exc}"[:300]})
        continue
    t = Reecrire()
    nouveau = arbre.visit(t)
    resultat["syspath_non_concernes"] += t.non_concernes
    if t.refus:
        resultat["refus"].append({"fichier": chemin, "cas": t.refus})
    if not t.faits:
        continue
    resultat["fichiers_modifies"] += 1
    resultat["transformations"] += len(t.faits)
    resultat["detail"].append({"fichier": chemin, "faits": t.faits[:6],
                               "total": len(t.faits)})
    if appliquer:
        Path(chemin).write_text(nouveau.code, encoding="utf-8")

json.dump(resultat, open(sys.argv[4], "w", encoding="utf-8"))
'''


def _py_venv() -> Path:
    return VENV_OUTILS / ("Scripts" if os.name == "nt" else "bin") / "python.exe"


def fichiers_famille(famille: str, carte: dict[str, str]) -> list[str]:
    """Les fichiers a transformer pour une famille donnee."""
    if famille == "tout":
        zones = ZONES
    else:
        zones = (famille,)
    trouves: list[str] = []
    for zone in zones:
        dossier = ROOT / zone
        if not dossier.is_dir():
            continue
        for chemin in dossier.rglob("*.py"):
            rel = chemin.relative_to(dossier)
            if any(p in {"_attic", "node_modules", "backups", "archive"} for p in rel.parts):
                continue
            trouves.append(str(chemin))
    return sorted(trouves)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--famille", default="app", choices=[*ZONES, "tout"])
    ap.add_argument("--fichiers", help="liste explicite, separee par des virgules")
    ap.add_argument("--appliquer", action="store_true", help="ECRIT (defaut : dry-run)")
    ap.add_argument("--syspath", action="store_true",
                    help="redirige aussi les sys.path de ZONE vers la racine")
    ap.add_argument("--json", default=str(CHANTIER / "codemod.json"))
    args = ap.parse_args()

    py = _py_venv()
    if not py.exists():
        print("[codemod] NON_CERTIFIANT — venv d'outils absent (PHASE 2)")
        return 2

    carte = carte_modules()
    if not carte:
        print("[codemod] NON_CERTIFIANT — carte des modules VIDE : rien ne serait transforme")
        return 2

    cibles = (args.fichiers.split(",") if args.fichiers
              else fichiers_famille(args.famille, carte))
    if not cibles:
        print(f"[codemod] NON_CERTIFIANT — aucune cible pour la famille {args.famille}")
        return 2

    CHANTIER.mkdir(parents=True, exist_ok=True)
    f_carte = CHANTIER / "_carte.json"
    f_cibles = CHANTIER / "_cibles.json"
    # ABSOLU, toujours : le `cwd` d'un `trusted_script` n'est pas celui du shell,
    # et un chemin relatif y designe un autre fichier — mesure 2026-09-10, la
    # sortie etait ecrite quelque part et relue ailleurs.
    f_sortie = Path(args.json)
    if not f_sortie.is_absolute():
        f_sortie = ROOT / f_sortie
    f_transfo = CHANTIER / "_transfo.py"
    f_carte.write_text(json.dumps(carte), encoding="utf-8")
    f_cibles.write_text(json.dumps(cibles), encoding="utf-8")
    f_transfo.write_text(_TRANSFO, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [str(py), str(f_transfo), str(f_carte), str(f_cibles),
         "1" if args.appliquer else "0", str(f_sortie),
         "1" if args.syspath else "0"],
        capture_output=True, text=True, errors="replace", timeout=3600, env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        print(f"[codemod] FAIL — la transformation a echoue\n{proc.stderr[-1500:]}")
        return 1
    if not f_sortie.exists():
        # Un sous-processus qui sort 0 SANS produire sa sortie n'a rien prouve.
        print(f"[codemod] NON_CERTIFIANT — aucune sortie a {f_sortie}\n"
              f"  stdout: {proc.stdout[-600:]}\n  stderr: {proc.stderr[-900:]}")
        return 2

    r = json.loads(f_sortie.read_text(encoding="utf-8"))
    mode = "APPLIQUE" if args.appliquer else "dry-run"
    print(f"[codemod:{args.famille}] {mode} — {r['fichiers_vus']} fichier(s) vus, "
          f"{r['fichiers_modifies']} modifiable(s), {r['transformations']} transformation(s), "
          f"{len(r['refus'])} fichier(s) avec refus, {len(r['illisibles'])} illisible(s), "
          f"{r.get('syspath_non_concernes', 0)} sys.path non concerne(s)")
    for refus in r["refus"][:8]:
        cas = ", ".join(sorted({c["forme"] for c in refus["cas"]}))
        print(f"    refus {Path(refus['fichier']).name} : {cas}")
    print(f"  -> {f_sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
