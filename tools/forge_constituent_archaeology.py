#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_constituent_archaeology.py — Phase 6 : archeologie des CONSTITUANTS.

POURQUOI CETTE PHASE
====================
Phase 1 (`forge_archaeology`) trouve 1732 vestiges, mais a la granularite du
FICHIER SUPPRIME uniquement (`git log --diff-filter=D`, `.py` seuls). Elle rate donc,
par construction, tout ce qui disparait SANS qu'un fichier soit supprime :

  - une fonction ou une classe retiree d'un fichier CONSERVE ;
  - une entree de registre retiree d'un dict / set / enum (un provider sorti de
    la table, un tool sorti du catalogue, une action sortie d'un enum, une route,
    un service, un hook) ;
  - tout ce qui n'est pas `.py` (`.ts`, `.js`, `.ps1`, configs).

Mesure fondatrice du 2026-08-16 : `forge_lmstudio.py`, `forge_litellm_router.py` et
les 16 modules swarm sont TOUS presents, aucun n'a jamais ete supprime -- et
pourtant `ollama_local`, `lmstudio_native` et `llamacpp_local` sont declares
inatteignables sur chat / code / swarm / debate (39 providers declares, 17
atteignables). L'archeologie de suppression ne pouvait rien en voir.

METHODE
=======
Une passe UNIQUE et streamee sur `git log --all -U0`, par depot. On repere les
LIGNES supprimees qui definissent un constituant, puis on tranche en croisant avec
les noms VIVANTS de tous les depots :

  REECRIT  : le nom vit encore dans le HEAD du MEME depot (deplace/renomme/reecrit)
  MIGRE    : le nom vit dans le HEAD d'un AUTRE depot
  DISPARU  : introuvable dans tous les HEAD connus

REGLE DE SONDE (leçon du 2026-08-12, rappelee par Phase 1) : une passe qui n'a pas
pu observer rend INDETERMINE -- jamais « 0 disparu ». Un depot dont `git log`
echoue est NOMME, jamais compte comme vide.

CE QUE CETTE PHASE NE FAIT PAS
==============================
Elle ne juge pas l'ATTEIGNABILITE du vivant (constituant present mais que plus
aucun chemin n'atteint). C'est le second angle mort, traite ailleurs : ici on ne
regarde que ce qui a disparu du texte.

Usage :
    forge_constituent_archaeology.py [--repos nom=chemin ...] [--max-lignes N]
    forge_constituent_archaeology.py --json --out sandbox/constituents.json
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

__FORGE_COLOR__ = "observabilite/audit : archeologie des constituants (phase 6)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import re
import subprocess          # `supprimes()` streame `git log` via Popen

from nokido_agent.tools.forge_archeo_socle import bruit_motifs
from nokido_agent.tools.forge_archeo_socle import git_rc as _git

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(ROOT)


def _log(m: str) -> None:
    """Defini AVANT `_depots_defaut`, qui l'appelle a l'import du module.

    Il vivait plus bas : quand `sandbox/archaeology_clones/` n'existe pas -- le
    cas sur un checkout CI neuf -- la branche d'erreur levait
    `NameError: _log`, et le module entier devenait inimportable. Bug latent
    depuis l'origine, jamais vu en local ou le dossier existe.
    """
    print(f"[constituants] {m}", flush=True)


# Phase 1 listait nokido-workspace comme ABSENT alors que c'est le depot de
# COMPOSITION -- celui ou une capacite peut mourir sans qu'aucun module ne bouge.
def _depots_defaut() -> dict:
    """Les 9 depots de l'ecosysteme, DECOUVERTS -- pas codes en dur.

    Phase 1 declarait `nokido-workspace` ABSENT alors qu'il est bien un depot (68
    noms vivants, mesure du 2026-08-16) : un chemin fige finit toujours par mentir.
    Les 7 autres depots sont clones sous sandbox/archaeology_clones/ ; on les prend
    tels qu'ils sont, et tout ajout futur est ramasse sans toucher au code.
    """
    d = {"nokido": ROOT, "nokido-workspace": _PARENT}
    clones = os.path.join(ROOT, "sandbox", "archaeology_clones")
    try:
        for nom in sorted(os.listdir(clones)):
            chemin = os.path.join(clones, nom)
            if os.path.isdir(chemin):
                d.setdefault(nom, chemin)
    except OSError as e:
        _log(f"clones illisibles ({clones}) : {type(e).__name__} — "
             f"seuls nokido et le workspace seront peignes")
    return d


DEPOTS_DEFAUT = _depots_defaut()

_BRUIT = ("_attic", "backups", "node_modules", ".venv", "site-packages", "RAG/",
          "RAG_plain_bak", "shadow_mutation", "docsets", "eval_repos", "/tmp_",
          "dist/", "build/", ".min.js")

_EXT = (".py", ".ts", ".js", ".mjs", ".ps1")

# Un constituant = une chose qu'on peut perdre isolement. On ne capture que des
# DEFINITIONS, jamais des usages : une ligne d'appel supprimee n'est pas une perte.
MOTIFS = (
    ("fonction", re.compile(r"^-\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")),
    ("classe", re.compile(r"^-\s*class\s+([A-Za-z_]\w*)")),
    ("fonction_js", re.compile(r"^-\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)")),
    # Entree de registre : "nom": ... dans un dict/enum. C'est par la que sortent
    # les providers, les tools, les actions et les routes.
    ("entree_registre", re.compile(r"^-\s*[\"']([A-Za-z_][\w.\-]{2,60})[\"']\s*:")),
    ("constante", re.compile(r"^-\s*([A-Z][A-Z0-9_]{3,60})\s*[:=]\s")),
)

# Les memes formes, cote VIVANT, pour construire l'index des noms encore definis.
MOTIFS_VIVANTS = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"^\s*[\"']([A-Za-z_][\w.\-]{2,60})[\"']\s*:", re.M),
    re.compile(r"^\s*([A-Z][A-Z0-9_]{3,60})\s*[:=]\s", re.M),
)


def _est_bruit(chemin: str) -> bool:
    return bruit_motifs(chemin, _BRUIT, ("tmp_", "test_"))


def est_depot(p: str) -> bool:
    """La RACINE d'un depot — pas seulement « quelque part dedans ».

    `rev-parse --git-dir` reussit depuis n'importe quel sous-dossier : il REMONTE
    au depot parent. Un dossier quelconque passe en --repos etait donc analyse avec
    l'historique de son parent, fabriquant des vestiges qui n'ont jamais existe la
    (pris par le test d'effet, 2026-08-16). On exige donc que le toplevel soit CE
    chemin. `--show-toplevel` marche aussi pour un submodule, dont le .git est un
    FICHIER : le test naif `isdir('.git')` l'ecartait a tort (leçon Phase 1).
    """
    if not os.path.isdir(p):
        return False
    rc, out = _git(p, "rev-parse", "--show-toplevel", timeout=20)
    if rc != 0 or not out.strip():
        return False
    return os.path.normcase(os.path.realpath(out.strip())) == \
        os.path.normcase(os.path.realpath(p))


def noms_vivants(repo: str) -> set:
    """Tous les noms encore DEFINIS dans le HEAD d'un depot.

    Lu depuis le working tree (ls-files + lecture), pas via `git show` par fichier :
    un aller-retour git par fichier coutait des minutes sur 8 depots.
    """
    rc, out = _git(repo, "ls-files", timeout=90)
    if rc != 0:
        _log(f"  {os.path.basename(repo)} : ls-files KO -> 0 nom vivant, "
             f"tout y paraitra DISPARU. Verdict a lire comme INDETERMINE.")
        return set()
    vivants = set()
    illisibles = []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel.endswith(_EXT) or _est_bruit(rel):
            continue
        try:
            with open(os.path.join(repo, rel), encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError as e:
            illisibles.append(f"{rel} ({type(e).__name__})")
            continue
        for motif in MOTIFS_VIVANTS:
            vivants.update(n for n in motif.findall(src) if est_nom_de_code(n))
    if illisibles:
        # Un fichier vivant non lu retire ses noms de l'index -> ils paraitront
        # DISPARUS. On le dit, plutot que de laisser l'absence passer pour une perte.
        _log(f"  {os.path.basename(repo)} : {len(illisibles)} fichier(s) vivant(s) "
             f"illisible(s), leurs noms peuvent paraitre disparus — "
             f"{', '.join(illisibles[:3])}")
    return vivants


def supprimes(repo: str, max_lignes: int):
    """Constituants dont la DEFINITION a ete supprimee, sur tout l'historique.

    Streame `git log --all -U0` : le charger en memoire d'un bloc, c'etait des
    centaines de Mo sur les gros depots (et le gel PC du 2026-08-02 rappelle ce que
    coute une passe non bornee). On borne aussi le nombre de lignes lues.
    """
    cmd = ["git", "-c", "safe.directory=*", "-C", repo, "log", "--all", "-U0",
           "--no-renames", "--no-color", "--date=short",
           "--pretty=format:__C__%h|%ad|%s"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, errors="replace", bufsize=1)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"

    trouves = {}
    sha = date = msg = ""
    fichier = ""
    lues = 0
    try:
        for ligne in proc.stdout:  # type: ignore[union-attr]
            lues += 1
            if lues > max_lignes:
                _log(f"  borne atteinte ({max_lignes} lignes) sur {os.path.basename(repo)}")
                break
            if ligne.startswith("__C__"):
                parts = ligne[5:].rstrip("\n").split("|", 2)
                sha, date, msg = (parts + ["", "", ""])[:3]
                continue
            if ligne.startswith("--- a/"):
                fichier = ligne[6:].strip()
                continue
            if ligne.startswith("+++ b/"):
                continue
            if not ligne.startswith("-") or ligne.startswith("---"):
                continue
            if not fichier.endswith(_EXT) or _est_bruit(fichier):
                continue
            hit = detecter(ligne)
            if hit:
                genre, nom = hit
                cle = (genre, nom)
                # premiere occurrence = suppression la plus RECENTE (log anti-chrono)
                if cle not in trouves:
                    trouves[cle] = {"genre": genre, "nom": nom, "fichier": fichier,
                                    "sha_suppr": sha, "date_suppr": date,
                                    "msg_suppr": msg[:110]}
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001  # muet-ok : le flux est deja lu, tuer un
            pass          # process deja mort n'apprend rien et ne doit rien casser
    return list(trouves.values()), ""


def classer_constituant(nom: str, depot: str, vivants: dict):
    """(etat, hotes) d'un constituant supprime, au vu des noms VIVANTS de tout l'ecosysteme.

    Trois etats, jamais un seul « perdu » : la leçon de Phase 1 est qu'un nom absent
    ici peut vivre ailleurs (feature migree), ou etre revenu dans le meme depot
    (reecriture). Seul le troisieme cas est une perte.
    """
    if nom in vivants.get(depot, ()):
        return "REECRIT", [depot]
    hotes = sorted(d for d, s in vivants.items() if nom in s)
    if hotes:
        return "MIGRE", hotes
    return "DISPARU", []


# Extensions : `CMakeLists.txt` et `Cargo.toml` passaient le test du chemin pointe
# (leurs deux segments sont des identifiants) alors que ce sont des NOMS DE FICHIER.
_EXTENSIONS = {"txt", "json", "py", "toml", "md", "yml", "yaml", "js", "ts", "cfg",
               "ini", "log", "csv", "xml", "html", "css", "sh", "ps1", "bat", "lock",
               "env", "db", "sql", "png", "svg", "jsonl", "exe", "dll", "so"}


def est_nom_de_code(nom: str) -> bool:
    """Le nom peut-il designer un constituant de CODE ?

    Le motif `entree_registre` capture toute cle `"x":` — donc aussi les cles de
    documentation, les en-tetes HTTP et les noms de fichiers. Mesures du 2026-08-16,
    en deux passes : d'abord `ADR-001`, `B.3.1`, `Accept-Encoding` ; puis, une fois
    ceux-la ecartes, `CMakeLists.txt`, `Cargo.toml`, `EP`, `G`, `Ok`.

    Trois criteres, tous nes d'un faux positif observe :
      - au moins 3 caracteres (`G`, `EP`, `Ok` ne designent rien qu'on perde) ;
      - un identifiant, ou un chemin pointe dont CHAQUE segment en est un
        (`mem.swap_pct` est un canal de vitals bien reel ; `B.3.1` non) ;
      - dont le dernier segment n'est pas une EXTENSION de fichier.
    """
    if not nom or len(nom) < 3:
        return False
    if nom.isidentifier():
        return True
    if "." in nom:
        segs = nom.split(".")
        if segs[-1].lower() in _EXTENSIONS:
            return False
        return all(seg.isidentifier() for seg in segs)
    return False


def detecter(ligne: str):
    """(genre, nom) si la ligne supprime une DEFINITION, sinon None.

    On ne capture jamais un usage : `-    resultat = axe_tools()` n'est pas une
    perte de constituant, c'est un appel retire. Confondre les deux ferait crier
    l'outil a chaque refactor.
    """
    for genre, motif in MOTIFS:
        m = motif.match(ligne)
        if not m:
            continue
        nom = m.group(1)
        if nom.startswith("__") or len(nom) < 3 or not est_nom_de_code(nom):
            return None
        return genre, nom
    return None


def analyser(depots: dict, max_lignes: int) -> dict:
    presents = {n: p for n, p in depots.items() if est_depot(p)}
    absents = sorted(n for n in depots if n not in presents)
    if not presents:
        return {"observable": False,
                "raison": f"aucun depot lisible (absents: {absents})"}

    _log(f"depots lisibles : {', '.join(sorted(presents))}"
         + (f" | ABSENTS : {', '.join(absents)}" if absents else ""))

    vivants = {}
    for n, p in presents.items():
        vivants[n] = noms_vivants(p)
        _log(f"  {n}: {len(vivants[n])} noms vivants")
    union = set().union(*vivants.values()) if vivants else set()

    constituants = []
    illisibles = []
    for n, p in presents.items():
        res, err = supprimes(p, max_lignes)
        if res is None:
            illisibles.append({"depot": n, "erreur": err})
            continue
        for c in res:
            etat, hotes = classer_constituant(c["nom"], n, vivants)
            constituants.append({"depot": n, **c, "etat": etat, "vit_dans": hotes})
        _log(f"  {n}: {len(res)} definitions supprimees")

    par_etat, par_genre = {}, {}
    for c in constituants:
        par_etat[c["etat"]] = par_etat.get(c["etat"], 0) + 1
        if c["etat"] == "DISPARU":
            par_genre[c["genre"]] = par_genre.get(c["genre"], 0) + 1
    constituants.sort(key=lambda c: (c["etat"] != "DISPARU", c.get("date_suppr", "")),
                      reverse=False)
    return {"observable": True, "depots_analyses": sorted(presents),
            "depots_absents": absents, "depots_illisibles": illisibles,
            "resume": par_etat, "disparus_par_genre": par_genre,
            "constituants": constituants}


def main() -> int:
    ap = argparse.ArgumentParser(description="Archeologie des constituants (Phase 6)")
    ap.add_argument("--repos", nargs="*", default=[], help="nom=chemin supplementaires")
    ap.add_argument("--out", default=os.path.join(ROOT, "sandbox", "constituents.json"))
    ap.add_argument("--max-lignes", type=int, default=4_000_000)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args()

    depots = dict(DEPOTS_DEFAUT)
    for spec in a.repos:
        if "=" in spec:
            n, p = spec.split("=", 1)
            depots[n] = p

    res = analyser(depots, a.max_lignes)
    if not res.get("observable"):
        _log(f"INDETERMINE : {res.get('raison')}")
        return 2

    try:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
    except OSError as e:
        _log(f"ecriture impossible : {e}")

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    r = res["resume"]
    _log(f"{sum(r.values())} definitions supprimees — "
         + ", ".join(f"{k}={v}" for k, v in sorted(r.items())))
    _log("DISPARUS par genre : "
         + (", ".join(f"{k}={v}" for k, v in sorted(res["disparus_par_genre"].items()))
            or "aucun"))
    for x in res["depots_illisibles"]:
        _log(f"  INDETERMINE sur {x['depot']} : {x['erreur']}")
    disparus = [c for c in res["constituants"] if c["etat"] == "DISPARU"]
    _log(f"top {a.top} disparus (plus recents en tete) :")
    for c in sorted(disparus, key=lambda c: c.get("date_suppr", ""), reverse=True)[:a.top]:
        _log(f"  [{c['genre']:<16}] {c['nom']:<34} {c['depot']}:{c['fichier']}"
             f"  ({c['date_suppr']})")
    _log(f"ecrit : {os.path.relpath(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
