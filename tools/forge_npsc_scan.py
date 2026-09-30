#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NPSC — inventaire des SURFACES par preuve en cascade (niveaux 0 a 3).

Separe du moteur de verdict (`forge_npsc.py`) : ici on MESURE ce que le depot
expose, la-bas on en tire des verdicts de conformite. Un capteur et un juge ne
se melangent pas.

Cascade (owner, 2026-09-04) :

    NIVEAU 0 : chemin git ls-files      (aucun contenu lu)
    NIVEAU 1 : signature lexicale       (commentaires retires)
    NIVEAU 2 : AST / config             (elimine les faux positifs)
    NIVEAU 3 : sonde runtime            (a brancher)
    NIVEAU 4 : arbitrage LLM            (cas ambigus SEULEMENT — non branche)

INVARIANT : un fichier non versionne, ou classe DATA, ne peut JAMAIS constituer
a lui seul une preuve de surface protocolaire.

Ce que cet invariant a coute quand il manquait, mesure le 2026-09-04 : un
`os.walk` naif lisait 32 173 fichiers / 871 Mo dont un dataset JSON de 277 Mo ;
une blacklist de repertoires laissait encore passer 2 958 fichiers de `data/`.
Un corpus de benchmark citant un protocole aurait FABRIQUE la surface, donc
rendu une RFC applicable a tort.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/conformite-normative"

import ast
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _horodatage():
    return datetime.now(timezone.utc).isoformat()

ROOT = Path(__file__).resolve().parent.parent

# Trois etats de DECOUVERTE (owner, 2026-09-04) : un mot vu dans un dataset ou
# un commentaire rend SUSPECT, une signature structurelle rend PROVEN, rien du
# tout rend ABSENT. Le quatrieme, UNREADABLE, est orthogonal aux trois autres :
# il dit « je n'ai pas pu regarder », ce qu'aucun des trois ne peut exprimer.
PROVEN = "PROVEN"
SUSPECT = "SUSPECT"
ABSENT = "ABSENT"
UNREADABLE = "UNREADABLE"

# Aliases retrogrades — un etat lu depuis un artefact ancien reste interpretable.
_ANCIENS_ETATS = {"PROUVEE": PROVEN, "INDICE_SEUL": SUSPECT,
                  "ABSENTE": ABSENT, "ILLISIBLE": UNREADABLE}

CODE = "CODE"
CONFIG = "CONFIG"
TEST = "TEST"
DOC = "DOC"
DATA = "DATA"
VENDOR = "VENDOR"
META = "META"
PORTENT_PREUVE = (CODE, CONFIG)

# Le moteur NPSC lui-meme. Il PARLE de toutes les surfaces sans en exposer
# aucune : son registre nomme les protocoles, ses detecteurs citent les
# litteraux qu'ils cherchent, ses tests fabriquent des cas temoins.
#
# Mesure 2026-09-04 : la surface `webauthn`, correctement classee ABSENT, est
# repassee SUSPECT sitot le registre committe — parce que le registre contient
# le mot « webauthn » dans la definition de la surface webauthn. Un moteur qui
# se mesure lui-meme finit par prouver tout ce qu'il sait nommer.
#
# Troisieme incarnation du meme defaut dans la meme journee : le garde LIKE
# criait sur ses propres commentaires, et le test « ce motif n'existe nulle
# part » est devenu faux des qu'il a ete committe avec son motif en clair.
_FICHIERS_META = (
    "standards/registry.json",
    "tools/forge_npsc.py",
    "tools/forge_npsc_scan.py",
    "tools/forge_npsc_decouverte.py",
    "tests/nr/test_npsc_nr.py",
    "tests/nr/test_npsc_decouverte_nr.py",
)

# Dependances TIERCES embarquees dans le depot. Elles sont versionnees et ont
# une extension de code, donc `git ls-files` ne les distingue pas — mais leur
# contenu n'est pas notre implementation.
#
# Mesure 2026-09-04 : `app/web_hub/static/swagger-ui-bundle.js` etait le SEUL
# fichier du depot citant « webauthn / passkey / fido ». Classe CODE, il faisait
# sortir la surface WebAuthn en INDICE_SEUL, donc W3C-WEBAUTHN-L3 en « a
# instruire » — pour du code que nous n'ecrivons pas. Meme famille que les
# datasets, une couche plus loin : ni preuve, ni indice.
_MARQUEURS_VENDOR = ("/static/", "/vendor/", "/node_modules/", "/third_party/",
                     ".min.js", ".min.css", "-bundle.js", ".bundle.js")

_RACINES_TEST = ("tests/", "test/")
_RACINES_DOC = ("docs/", "doc/")
_RACINES_DATA = ("data/", "models/", "datasets/", "rag_plain_bak/", "shadow_mutation/",
                 "archive/", "workspace/", "sandbox/", "rag/")
_EXT_CODE = (".py", ".ts", ".tsx", ".js", ".mjs")
_EXT_CONFIG = (".toml", ".yaml", ".yml", ".ini", ".cfg")
_EXT_DOC = (".md", ".rst", ".txt")

MAX_OCTETS = 2000000
PLANCHER_FICHIERS = 200
PLAFOND_ILLISIBLES = 0.05
PLAFOND_AST_ECHECS = 0.05
SANITE_ATTENDUE = ("hub.mcp", "http.serveur", "json")


def fichiers_versionnes(racine):
    """Fichiers SUIVIS par git. Rend (liste, erreur).

    Frontiere primaire : exclut par CONSTRUCTION datasets, modeles, caches et
    artefacts, la ou une blacklist doit etre rallongee sans fin.

    `safe.directory=*` est obligatoire (le compte sandbox n'est pas proprietaire
    du depot), et on NOMME le depot par -C sans changer de repertoire courant.
    """
    cmd = ["git", "-c", "safe.directory=*", "-C", str(racine), "ls-files", "-z"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception as exc:
        return None, "git indisponible : %s" % exc
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace")[:200]
        return None, "git ls-files rc=%s : %s" % (proc.returncode, detail)
    sortie = (proc.stdout or b"").decode("utf-8", "replace")
    fichiers = [f for f in sortie.split("\0") if f]
    if not fichiers:
        # Sortie VIDE avec rc=0 : piege deja paye sur `ls-tree`. Ce n'est pas
        # « depot vide », c'est « je n'ai pas pu voir ».
        return None, "git ls-files rend une liste VIDE avec rc=0 - depot non lu"
    return fichiers, None


def classer(rel):
    """Population d'un chemin. La classification precede toute mesure."""
    bas = rel.replace("\\", "/").lower()
    for meta in _FICHIERS_META:
        if bas == meta.lower():
            return META
    sonde = "/" + bas
    for marqueur in _MARQUEURS_VENDOR:
        if marqueur in sonde:
            return VENDOR
    for prefixe in _RACINES_DATA:
        if bas.startswith(prefixe):
            return DATA
    for prefixe in _RACINES_TEST:
        if bas.startswith(prefixe):
            return TEST
    for prefixe in _RACINES_DOC:
        if bas.startswith(prefixe):
            return DOC
    if bas.endswith(_EXT_DOC):
        return DOC
    if bas.endswith(_EXT_CONFIG):
        return CONFIG
    if bas.endswith(_EXT_CODE):
        return CODE
    return DATA


def signaux_python(texte):
    """NIVEAU 2 — signaux structurels par AST. Rend (signaux, erreur).

    L'AST elimine nativement les commentaires : un protocole cite en commentaire
    ne peut plus fabriquer une surface. Les docstrings sont retirees a part —
    chaines pour le parseur, prose pour nous.
    """
    try:
        arbre = ast.parse(texte)
    except Exception as exc:
        return None, type(exc).__name__
    porteurs = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, porteurs):
            doc = ast.get_docstring(noeud, clean=False)
            if doc:
                docstrings.add(doc)
    imports = set()
    chaines = set()
    attributs = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                imports.add(alias.name)
                imports.add(alias.name.split(".")[0])
        elif isinstance(noeud, ast.ImportFrom):
            if noeud.module:
                imports.add(noeud.module)
                imports.add(noeud.module.split(".")[0])
        elif isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            if noeud.value not in docstrings and len(noeud.value) <= 400:
                chaines.add(noeud.value)
        elif isinstance(noeud, ast.Attribute):
            attributs.add(noeud.attr)
        elif isinstance(noeud, ast.Name):
            attributs.add(noeud.id)
        elif isinstance(noeud, ast.keyword) and noeud.arg:
            # Un mot-cle d'appel est une signature STRUCTURELLE de premier ordre.
            # Mesure 2026-09-04 : `QdrantClient(..., prefer_grpc=True)` prouve que
            # Nokido parle gRPC, alors qu'aucun `import grpc` n'existe — la
            # surface est DELEGUEE a la dependance. Sans collecter les keywords,
            # gRPC sortait INDICE_SEUL a tort.
            attributs.add(noeud.arg)
    return {"imports": imports, "chaines": chaines, "attributs": attributs}, None


_COMMENTAIRE_BLOC = re.compile(r"/\*.*?\*/", re.S)
_COMMENTAIRE_LIGNE = re.compile(r"(^|\s)//.*$|^\s*#.*$", re.M)
_RX_IMPORT_JS = re.compile(r'''(?:import|require|from)\s*\(?\s*['"]([^'"]+)['"]''')
_RX_CHAINE = re.compile(r'''['"]([^'"\n]{1,200})['"]''')
_RX_APPEL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")


def signaux_lexicaux(texte):
    """NIVEAU 1 — repli pour ce qui n'a pas d'AST ici (.ts/.js/.toml/.yaml).

    Les commentaires sont retires avant analyse, sinon un fichier DOCUMENTANT un
    protocole le declarerait present. Plus faible qu'un AST, et le rapport le DIT :
    un repli qui se tait se lit comme une mesure.
    """
    net = _COMMENTAIRE_BLOC.sub(" ", texte)
    net = _COMMENTAIRE_LIGNE.sub(" ", net)
    return {
        "imports": set(_RX_IMPORT_JS.findall(net)),
        "chaines": set(_RX_CHAINE.findall(net)),
        "attributs": set(_RX_APPEL.findall(net)),
    }


def sceller(signaux):
    """Prepare les signaux pour une comparaison en temps constant.

    Sans ce scellement, chaque litteral du registre etait compare a CHAQUE
    chaine du fichier : ~30 litteraux x ~2 000 chaines x ~5 000 fichiers, soit
    des centaines de millions de comparaisons Python. Le scan expirait au cap de
    70 s sans jamais rendre un verdict — un instrument qui n'aboutit pas ne
    mesure rien. Un seul `in` sur un blob delegue la recherche au C.
    """
    signaux["blob"] = "\n".join(signaux["chaines"]).lower()
    return signaux


def correspond(spec_preuve, signaux):
    """Compte les signatures distinctes satisfaites. Rend (score, temoins)."""
    score = 0
    temoins = []
    for mod in spec_preuve.get("imports") or []:
        prefixe = mod + "."
        for vu in signaux["imports"]:
            if vu == mod or vu.startswith(prefixe):
                score += 1
                temoins.append("import:" + mod)
                break
    blob = signaux.get("blob")
    if blob is None:
        blob = "\n".join(signaux["chaines"]).lower()
    for lit in spec_preuve.get("chaines") or []:
        if lit.lower() in blob:
            score += 1
            temoins.append("chaine:" + lit)
    for att in spec_preuve.get("attributs") or []:
        if att in signaux["attributs"]:
            score += 1
            temoins.append("appel:" + att)
    return score, temoins


def _toutes_illisibles(reg, motif):
    """Toutes les surfaces en UNREADABLE : l'instrument n'a pas pu regarder."""
    sortie = {}
    for nom, spec in reg["surfaces"].items():
        sortie[nom] = {
            "etat": UNREADABLE, "score_preuve": None, "score_indice": None,
            "priorite": spec.get("priorite"), "libelle": spec.get("libelle"),
            "pourquoi": motif, "temoins": [], "fichiers": [],
            "sans_autorite": spec.get("sans_autorite"),
        }
    return sortie


def inventorier(reg, racine=ROOT):
    """Mesure les surfaces reellement exposees. Rend (surfaces, diagnostic)."""
    racine = Path(racine)
    fichiers, err_git = fichiers_versionnes(racine)
    diag = {
        "source": "git ls-files", "racine": str(racine), "erreur_index": err_git,
        "suivis": 0, "lus": 0, "illisibles": 0, "illisibles_exemples": [],
        "volumineux_ecartes": 0, "volumineux_exemples": [],
        "ast_tentes": 0, "ast_echecs": 0, "ast_echecs_exemples": [],
        "populations": {}, "controles": {},
        "taux_illisible": 0.0, "taux_ast_echec": 0.0,
    }
    if fichiers is None:
        diag["controles"] = {"INDEX_GIT": False}
        diag["instrument_ok"] = False
        return _toutes_illisibles(reg, "index git indisponible : %s" % err_git), diag

    diag["suivis"] = len(fichiers)
    scores = {}
    indices_rx = {}
    for nom, spec in reg["surfaces"].items():
        scores[nom] = {"preuve": 0, "indice": 0, "temoins": [], "fichiers": []}
        motif = (spec.get("indice") or {}).get("motif")
        rx = None
        if motif:
            try:
                rx = re.compile(motif, re.I)
            except re.error:
                rx = None
        indices_rx[nom] = rx

    pops = {CODE: 0, CONFIG: 0, TEST: 0, DOC: 0, DATA: 0, VENDOR: 0, META: 0}
    for rel in fichiers:
        pop = classer(rel)
        pops[pop] = pops.get(pop, 0) + 1
        if pop in (DATA, VENDOR, META):
            # Ni preuve NI indice. DATA et VENDOR ne sont pas notre code ; META
            # est notre code mais il DECRIT les surfaces au lieu de les exposer.
            # Un instrument qui se mesure lui-meme mesure son vocabulaire.
            continue
        chemin = racine / rel
        try:
            taille = chemin.stat().st_size
        except Exception as exc:
            diag["illisibles"] += 1
            if len(diag["illisibles_exemples"]) < 5:
                diag["illisibles_exemples"].append("%s (%s)" % (rel, type(exc).__name__))
            continue
        if taille > MAX_OCTETS:
            diag["volumineux_ecartes"] += 1
            if len(diag["volumineux_exemples"]) < 5:
                diag["volumineux_exemples"].append("%s (%.1f Mo)" % (rel, taille / 1e6))
            continue
        try:
            texte = chemin.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            diag["illisibles"] += 1
            if len(diag["illisibles_exemples"]) < 5:
                diag["illisibles_exemples"].append("%s (%s)" % (rel, type(exc).__name__))
            continue
        diag["lus"] += 1

        if rel.lower().endswith(".py"):
            diag["ast_tentes"] += 1
            signaux, err_ast = signaux_python(texte)
            if signaux is None:
                diag["ast_echecs"] += 1
                if len(diag["ast_echecs_exemples"]) < 5:
                    diag["ast_echecs_exemples"].append("%s (%s)" % (rel, err_ast))
                signaux = signaux_lexicaux(texte)
        else:
            signaux = signaux_lexicaux(texte)
        sceller(signaux)

        for nom, spec in reg["surfaces"].items():
            score, temoins = correspond(spec.get("preuve") or {}, signaux)
            if score and pop in PORTENT_PREUVE:
                scores[nom]["preuve"] += score
                scores[nom]["fichiers"].append(rel)
                for t in temoins:
                    if t not in scores[nom]["temoins"]:
                        scores[nom]["temoins"].append(t)
            elif score:
                scores[nom]["indice"] += score
            else:
                rx = indices_rx.get(nom)
                if rx is not None and rx.search(texte):
                    scores[nom]["indice"] += 1

    diag["populations"] = pops
    denom = diag["lus"] + diag["illisibles"]
    if denom:
        diag["taux_illisible"] = round(diag["illisibles"] / denom, 4)
    if diag["ast_tentes"]:
        diag["taux_ast_echec"] = round(diag["ast_echecs"] / diag["ast_tentes"], 4)

    surfaces = {}
    for nom, spec in reg["surfaces"].items():
        cur = scores[nom]
        seuil = int((spec.get("preuve") or {}).get("seuil") or 1)
        if cur["preuve"] >= seuil:
            etat = PROVEN
            pourquoi = "%d signature(s) structurelle(s) en CODE/CONFIG, seuil %d" % (cur["preuve"], seuil)
        elif cur["preuve"] or cur["indice"]:
            etat = SUSPECT
            pourquoi = "citee (%d indice) mais %d signature < seuil %d" % (cur["indice"], cur["preuve"], seuil)
        else:
            etat = ABSENT
            pourquoi = "aucune signature ni mention dans le code versionne"
        surfaces[nom] = {
            "etat": etat, "score_preuve": cur["preuve"], "score_indice": cur["indice"],
            "priorite": spec.get("priorite"), "libelle": spec.get("libelle"),
            "pourquoi": pourquoi, "temoins": cur["temoins"][:6],
            "fichiers": sorted(set(cur["fichiers"]))[:4],
            "sans_autorite": spec.get("sans_autorite"),
        }

    prouvees = set()
    for nom in surfaces:
        if surfaces[nom]["etat"] == PROVEN:
            prouvees.add(nom)
    manquantes = [n for n in SANITE_ATTENDUE if n not in prouvees]
    diag["controles"] = {
        "INDEX_GIT": True,
        "INDEX_COVERAGE": diag["lus"] >= PLANCHER_FICHIERS,
        "PATH_CLASSIFICATION": diag["suivis"] == sum(pops.values()),
        "UNREADABLE_RATE": diag["taux_illisible"] <= PLAFOND_ILLISIBLES,
        "OVERSIZED_FILE_EXCLUSION": True,
        "CODE_ONLY_ASSERTION": pops[CODE] > 0,
        "AST_PARSE_RATE": diag["taux_ast_echec"] <= PLAFOND_AST_ECHECS,
        "SURFACE_DETECTION_SANITY": not manquantes,
    }
    diag["instrument_ok"] = all(diag["controles"].values())
    if manquantes:
        diag["sanity_manquantes"] = manquantes
    return surfaces, diag


# --------------------------------------------------------------------------
# Artefact d'inventaire : la DECOUVERTE se pose sur disque et s'y relit.
#
# Sans artefact, les trois etapes (discover / applicable / verify) ne peuvent
# pas etre calculees independamment : chacune re-scannerait le depot. C'est ce
# couplage qui rendait le moteur laborieux.
# --------------------------------------------------------------------------

INVENTAIRE = ROOT / "sandbox" / "npsc_surfaces.json"


def sauver_inventaire(surfaces, diag, cible=INVENTAIRE):
    """Pose la photographie des surfaces. Rend le chemin reel, ou None.

    Les echecs sont ACCUMULES et rendus : un repli qui echoue partout doit dire
    pourquoi. Sans cela, un `return None` se lit « pas de place ou ecrire »
    alors qu'il peut cacher un refus d'ACL, un disque plein ou un JSON invalide.
    """
    charge = {"genere": _horodatage(), "surfaces": surfaces, "instrument": diag}
    refus = []
    for candidat in (Path(cible), INVENTAIRE):
        try:
            candidat.parent.mkdir(parents=True, exist_ok=True)
            candidat.write_text(json.dumps(charge, ensure_ascii=False, indent=2), encoding="utf-8")
            return candidat
        except Exception as exc:
            refus.append("%s : %s" % (candidat, type(exc).__name__))
    diag["inventaire_non_pose"] = refus
    print("[npsc] inventaire non pose — %s" % " | ".join(refus))
    return None


def charger_inventaire(source=INVENTAIRE):
    """Relit la photographie. Rend (surfaces, diag, erreur).

    Ne re-scanne RIEN : c'est tout l'interet. Un etat ancien est normalise vers
    le vocabulaire courant plutot que rejete — un artefact d'hier reste lisible.
    """
    try:
        charge = json.loads(Path(source).read_text(encoding="utf-8"))
    except Exception as exc:
        return None, None, "inventaire illisible (%s) : %s" % (source, exc)
    surfaces = charge.get("surfaces")
    if not isinstance(surfaces, dict):
        return None, None, "inventaire sans section 'surfaces'"
    for mesure in surfaces.values():
        ancien = mesure.get("etat")
        if ancien in _ANCIENS_ETATS:
            mesure["etat"] = _ANCIENS_ETATS[ancien]
    return surfaces, charge.get("instrument") or {}, None
