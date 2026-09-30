#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_secret_migration.py — migre les lectures de secret vers le COFFRE.

DIRECTIVE OWNER 2026-08-19 : « les clients doivent passer par le vault ! TOUS ! »

Mesure du jour : 117 fichiers, 191 lectures de secret directement dans
`os.environ`, 74 cles distinctes. La garde `laforge-cloud-secret-from-env`
interdit desormais la NOUVEAUTE (cf. le socle des Golden Rules), mais la dette
existante doit etre migree — et 191 remplacements a la main, sur le coeur du
hub, sans pouvoir redemarrer pour tester, se solderaient par un systeme qui ne
reimporte plus.

POURQUOI UN OUTIL PLUTOT QU'UN SED
-----------------------------------
Les trois formes n'ont PAS le meme contrat, et les confondre change le
comportement en silence :

    os.environ.get("X")          -> get_secret("X")            # None si absent
    os.environ.get("X", D)       -> get_secret("X") or D       # defaut preserve
    os.environ["X"]              -> get_secret("X")            # !! levait KeyError

La troisieme forme est la seule qui CHANGE la semantique : elle levait
`KeyError` sur secret absent, elle rendra `None`. On ne la migre donc jamais en
automatique — on la SIGNALE, pour que la decision soit prise en la regardant.

De meme, un `os.environ.get(...)` etale sur plusieurs lignes n'est pas touche :
une reecriture ligne a ligne y produirait du code casse. Il est compte comme
`complexe` et reste a faire a la main. Un migrateur qui pretend avoir tout
converti alors qu'il a saute les cas durs est pire qu'un migrateur absent : il
fait croire la dette soldee.

SURETE
------
* `--dry-run` est le DEFAUT. Ecrire demande `--appliquer` explicitement.
* On ne touche qu'un fichier qui importe DEJA le coffre : ajouter un import
  dans 99 modules de plus risquerait des cycles d'import, et un cycle ne se
  voit qu'au redemarrage — trop tard.
* Chaque fichier reecrit est reparse (`ast.parse`) AVANT ecriture : un fichier
  qui ne parse plus n'est jamais ecrit.
* Les octets sont preserves (lecture/ecriture binaire) : reecrire en mode texte
  convertirait les fins de ligne et salirait tout le depot — defaut deja paye
  le meme jour par le cliquet de mutation.

Usage :
    forge_secret_migration.py                 # mesure, n'ecrit rien
    forge_secret_migration.py --appliquer     # migre le lot sur
    forge_secret_migration.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
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

# Meme motif que la garde `laforge-cloud-secret-from-env` : les deux doivent
# nommer le MEME ensemble, sinon l'outil migre ce que le garde ne surveille pas
# (ou l'inverse), et le compteur du socle cesse de mesurer le recul.
_SECRET = re.compile(
    r"(?i)^(?!.*(?:_PATH|_DIR|_FILE)$).*(API_KEY|_SECRET|SECRET_KEY|_TOKEN|PASSWORD|_KEY)")

def _forme_appel(src: str) -> str | None:
    """Comment ce fichier peut-il appeler le coffre ? None = il ne peut pas.

    ⚠️ Verifier « le fichier mentionne forge_secrets » ne suffit PAS. Un module
    qui fait `import forge_secrets` n'a pas le nom `get_secret` dans sa portee :
    y ecrire `get_secret("X")` produit un fichier qui PARSE parfaitement et qui
    leve `NameError` a l'execution. L'AST ne voit pas un NameError — c'est
    exactement la forme de faux-vert qu'un migrateur doit refuser de produire.
    On regarde donc les imports REELS, et on adapte l'appel a ce qui est lie.
    """
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return None
    # ⚠️ `arbre.body` et NON `ast.walk` : walk descend dans les fonctions, donc
    # il trouve aussi un `from forge_secrets import get_secret` LOCAL a une
    # fonction. On concluait alors « l'appel est lie » et on reecrivait des
    # appels ailleurs dans le fichier, ou le nom n'existe pas -> NameError a
    # l'execution. MESURE 2026-08-19 : trois services sont tombes ainsi
    # (forge_anthropic_ingress, forge_gemini_ingress, forge_graph_explorer),
    # attrapes par forge_service_import_check. C'est la portee qui compte, pas
    # la presence : un import est un LIEN, et un lien a une portee.
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "forge_secrets":
            for a in n.names:
                if a.name == "get_secret":
                    return a.asname or "get_secret"
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "forge_secrets":
                    return (a.asname or "forge_secrets") + ".get_secret"
    return None


def _deja_importe_ailleurs(src: str) -> bool:
    """Le module importe-t-il forge_secrets HORS du niveau module (dans une
    fonction, un `try`) ? Alors n'y ajoutons pas un second import : le fichier
    a une raison de le faire tardivement (dependance lourde, import optionnel),
    et le doubler au niveau module la contredirait."""
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return False
    haut = {id(n) for n in arbre.body}
    for n in ast.walk(arbre):
        if id(n) in haut:
            continue
        if isinstance(n, ast.ImportFrom) and n.module == "forge_secrets":
            return True
        if isinstance(n, ast.Import) and any(a.name == "forge_secrets" for a in n.names):
            return True
    return False

# ⚠️ `(?<![\w.])` est INDISPENSABLE : sans lui, `os\.` mord sur la FIN de
# `_os.environ.get(...)` (module importe via `import os as _os`). Le prefixe `_`
# reste alors hors du match et se recolle devant le remplacement, produisant
# `_get_secret(...)` -- un nom qui n'existe nulle part. MESURE 2026-08-19 : trois
# services sont tombes ainsi. Les appels passant par un ALIAS ne sont plus
# migres du tout : ils seront reportes, ce qui est le bon defaut.
_PREFIXE = r"(?<![\w.])"
# Forme simple, sur UNE ligne, sans defaut.
_SANS_DEFAUT = re.compile(_PREFIXE + r"os\.(?:environ\.get|getenv)\(\s*([\"'])([A-Za-z0-9_]+)\1\s*\)")
# Forme simple, sur UNE ligne, avec un defaut litteral sans virgule interne.
_AVEC_DEFAUT = re.compile(
    _PREFIXE + r"os\.(?:environ\.get|getenv)\(\s*([\"'])([A-Za-z0-9_]+)\1\s*,\s*([^,()]+?)\s*\)")
# Forme indexee : signalee, jamais migree (elle levait KeyError).
_INDEXEE = re.compile(_PREFIXE + r"os\.environ\[\s*([\"'])([A-Za-z0-9_]+)\1\s*\]")


def _est_secret(cle: str) -> bool:
    return bool(_SECRET.search(cle))


def _migrer_source(src: str, appel: str = "get_secret") -> tuple[str, int, list[str]]:
    """Rend (source_migree, nb_remplacements, signalements).

    `appel` est le nom REELLEMENT lie dans le fichier (cf. `_forme_appel`).
    """
    signale: list[str] = []
    n = 0

    def _rempl_defaut(m: re.Match) -> str:
        nonlocal n
        if not _est_secret(m.group(2)):
            return m.group(0)
        n += 1
        # Le guillemet d'ORIGINE est conserve (m.group(1)). En imposer un autre
        # casse le cas ou l'appel vit dans une f-string delimitee par le meme
        # caractere : `f"...{os.environ.get('X')}..."` deviendrait
        # `f"...{get_secret("X")}..."`, tolere seulement depuis Python 3.12.
        q = m.group(1)
        return f"{appel}({q}{m.group(2)}{q}) or {m.group(3)}"

    def _rempl_simple(m: re.Match) -> str:
        nonlocal n
        if not _est_secret(m.group(2)):
            return m.group(0)
        n += 1
        q = m.group(1)
        return f"{appel}({q}{m.group(2)}{q})"

    # L'ordre compte : la forme AVEC defaut doit passer en premier, sinon la
    # forme sans defaut mordrait sur son prefixe et laisserait un defaut orphelin.
    src = _AVEC_DEFAUT.sub(_rempl_defaut, src)
    src = _SANS_DEFAUT.sub(_rempl_simple, src)

    for m in _INDEXEE.finditer(src):
        if _est_secret(m.group(2)):
            signale.append(f'os.environ["{m.group(2)}"] — levait KeyError, '
                           "decision a prendre a la main")
    return src, n, signale


def _peut_importer(rel: str, src: str) -> bool:
    """Ce module peut-il importer `forge_secrets` sans autre changement ?

    `app/` : oui, meme dossier. `tools/` : seulement s'il a DEJA mis `app/`
    dans son `sys.path` -- sinon l'import leverait `ImportError` a l'execution,
    et l'AST ne verrait rien (le fichier parse tres bien). Ajouter le chemin en
    plus de l'import serait une seconde modification, d'une autre nature : elle
    reste a faire a la main, fichier par fichier.
    """
    if rel.startswith("app/"):
        return True
    for ligne in src.splitlines():
        if "sys.path" in ligne and ('"app"' in ligne or "'app'" in ligne):
            return True
    return False


def _inserer_import(src: str) -> str | None:
    """Insere l'import du coffre APRES le dernier import de niveau module.

    Jamais en tete : `from __future__ import ...` doit rester la premiere
    instruction du fichier, et un docstring de module aussi. Se placer apres le
    dernier import existant respecte les deux sans avoir a les reconnaitre, et
    evite d'atterrir au milieu d'un bloc `try:` d'import conditionnel.
    Rend None si le fichier n'a aucun import : on ne devine pas une position.
    """
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return None
    # ⚠️ Le dernier import du PREAMBULE, pas le dernier import du FICHIER.
    # MESURE 2026-08-19 : `app/forge_llm_format_bridge.py` porte un
    # `import httpx` APRES `_TOKEN = load_token()`. Inserer apres le dernier
    # import du fichier plaçait donc l'import du coffre APRES l'appel qui s'en
    # sert, et `get_secret` n'existait pas encore au chargement du module --
    # deux services ingress sont tombes ainsi. Un import doit preceder son
    # premier USAGE, pas seulement figurer dans le fichier.
    # On s'arrete donc a la premiere instruction EXECUTABLE : docstring,
    # `from __future__` et imports forment le preambule ; tout le reste peut
    # deja appeler.
    dernier = 0
    for i, n in enumerate(arbre.body):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            dernier = max(dernier, getattr(n, "end_lineno", None) or n.lineno)
            continue
        if i == 0 and isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            continue  # docstring de module
        break
    if not dernier:
        return None
    lignes = src.splitlines(keepends=True)
    lignes.insert(dernier, "from forge_secrets import get_secret\n")
    return "".join(lignes)


# Dossiers JAMAIS migres. MESURE 2026-08-19 : la premiere campagne a reecrit 14
# fichiers de `app/_attic/shadow_mutation_2026-04/`, un dossier d'ARCHIVE
# gitignore et non suivi. Aucun commit n'aurait pu les emporter -- et git ne
# pouvait donc pas non plus les restaurer. Migrer des copies mortes n'apporte
# rien, ajoute du bruit, et fausse les outils d'archeologie qui les lisent comme
# des temoins d'epoque. Meme esprit que `_SKIP_DIRS` du scanner Golden Rules.
_EXCLUS = ("__pycache__", "_attic", "_archive", "archive", "_backups", "backups",
           "sandbox", "node_modules", "versions", ".git", "dist_laforge", "dist_test")


def _verdict_garde(rel: str, src: str) -> str:
    """Message du garde si cette source violerait une regle de nom, sinon "".

    Fail-open assume : si le module de regles est introuvable, on ne bloque pas
    la migration -- mais on ne pretend pas non plus l'avoir verifiee.
    """
    try:
        sys.path.insert(0, ROOT)
        from nokido_agent.tools import forge_golden_rules_ast as _g

        mordantes = ("laforge-usage-avant-liaison", "laforge-appel-nom-non-lie")
        for f in _g.scan_source(rel, src):
            if f.get("rule") in mordantes:
                return "%s ligne %s" % (f["rule"], f.get("line"))
    except Exception:  # noqa: BLE001 - garde indisponible : on ne bloque pas
        return ""
    return ""


def _fichiers() -> list[str]:
    out = []
    for sous in ("app", "tools"):
        for r, _, fs in os.walk(os.path.join(ROOT, sous)):
            parties = set(r.replace("\\", "/").split("/"))
            if parties & set(_EXCLUS):
                continue
            for f in fs:
                if f.endswith(".py") and f not in ("forge_secrets.py",
                                                   os.path.basename(__file__)):
                    out.append(os.path.join(r, f))
    return sorted(out)


def executer(appliquer: bool = False, ajouter_import: bool = False) -> dict:
    migres, ignores, complexes, casses = [], [], [], []
    total = 0
    for chemin in _fichiers():
        try:
            octets = open(chemin, "rb").read()
            src = octets.decode("utf-8")
        except Exception:  # noqa: BLE001 - binaire ou encodage exotique
            continue
        rel = os.path.relpath(chemin, ROOT).replace("\\", "/")
        appel = _forme_appel(src)
        if (appel is None and ajouter_import and _peut_importer(rel, src)
                and not _deja_importe_ailleurs(src)):
            # MESURE 2026-08-19 : le risque de CYCLE qui justifiait de reporter
            # ce lot est LEVE. La chaine est <module> -> forge_secrets ->
            # forge_machine_vault -> stdlib, et forge_machine_vault n'a AUCUNE
            # dependance interne : aucun cycle n'est atteignable.
            avec = _inserer_import(src)
            if avec is not None:
                src, appel = avec, "get_secret"
        if appel is None:
            # Lot 2 : demanderait un nouvel import. Un cycle d'import ne se voit
            # qu'au redemarrage du service — on ne le decouvre pas en migrant.
            _, n_potentiel, signale = _migrer_source(src)
            if signale:
                complexes.append({"fichier": rel, "motifs": signale})
            if n_potentiel:
                ignores.append({"fichier": rel, "occurrences": n_potentiel,
                                "raison": "get_secret non lie et app/ hors sys.path"})
            continue
        neuf, n, signale = _migrer_source(src, appel)
        if signale:
            complexes.append({"fichier": rel, "motifs": signale})
        if n == 0:
            continue
        try:
            ast.parse(neuf, filename=chemin)
        except SyntaxError as exc:
            casses.append({"fichier": rel, "erreur": f"{type(exc).__name__}: {exc}"})
            continue
        # Le migrateur se soumet au GARDE. Parser ne suffit pas : le 2026-08-19,
        # une reecriture parfaitement valide a fait appeler `_gs()` ligne 160
        # alors que l'import qui lie ce nom vit ligne 166 -> NameError au
        # chargement, hub mort, crash loop. `ast.parse` disait OK.
        # On refuse donc toute reecriture qui declencherait
        # `laforge-usage-avant-liaison` ou `laforge-appel-nom-non-lie` : le
        # migrateur ne doit pas pouvoir produire ce qu'un garde interdit.
        alerte = _verdict_garde(rel, neuf)
        if alerte:
            casses.append({"fichier": rel, "erreur": "refuse par le garde : " + alerte})
            continue
        total += n
        migres.append({"fichier": rel, "occurrences": n})
        if appliquer:
            with open(chemin, "wb") as fh:
                fh.write(neuf.encode("utf-8"))
    return {"applique": appliquer, "migres": migres, "occurrences_migrees": total,
            "reportes": ignores, "formes_indexees": complexes, "non_parsables": casses}


def main() -> int:
    ap = argparse.ArgumentParser(description="Migration des secrets vers le coffre")
    ap.add_argument("--appliquer", action="store_true",
                    help="ecrit reellement (defaut : mesure seule)")
    ap.add_argument("--ajouter-import", action="store_true",
                    help="insere l'import du coffre quand le module peut le resoudre")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    r = executer(a.appliquer, a.ajouter_import)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    verbe = "MIGRES" if r["applique"] else "MIGRABLES (essai a blanc)"
    print(f"[secrets] {verbe} : {r['occurrences_migrees']} occurrences "
          f"dans {len(r['migres'])} fichiers")
    for m in r["migres"][:30]:
        print(f"   {m['fichier']:<50} {m['occurrences']}")
    print(f"[secrets] REPORTES (import du coffre absent) : "
          f"{sum(x['occurrences'] for x in r['reportes'])} occurrences dans "
          f"{len(r['reportes'])} fichiers")
    if r["formes_indexees"]:
        print(f"[secrets] A LA MAIN — forme os.environ[...] qui levait KeyError : "
              f"{len(r['formes_indexees'])} fichiers")
    if r["non_parsables"]:
        print("[secrets] NON ECRITS — la reecriture ne parsait plus :")
        for c in r["non_parsables"]:
            print(f"   {c['fichier']} — {c['erreur']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
