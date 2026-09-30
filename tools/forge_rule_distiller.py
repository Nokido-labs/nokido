#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_rule_distiller.py — distiller un GARDE depuis un correctif reel.

Aujourd'hui, chaque morsure produit un fix, et c'est un humain (ou moi) qui
ecrit ensuite le garde a la main — quand il y pense. Ce module ferme la boucle
dans l'autre sens : partant d'un commit de FIX, il propose la regle qui aurait
attrape le defaut AVANT qu'il ne morde.

Deux garde-fous, parce qu'une regle inventee est pire que pas de regle :

  * FORMES CLOSES. On ne genere pas de code : on emet une ligne declarative
    (`appel_sans_kwarg`, `appel_interdit`) que `forge_golden_rules_ast` sait
    appliquer. Un distillateur qui ecrirait du Python dans le scanner serait un
    LLM deguise en garde.
  * BACKTEST, jamais un avis. Une candidate n'est retenue que si elle MORD sur
    la version fautive (le parent du fix) et se TAIT sur HEAD. C'est la methode
    deja actee le 2026-08-13 : un axe n'entre que s'il pointe une ligne reparee.
    Muette sur le parent = elle n'a rien vu ; bavarde sur HEAD = elle ouvre une
    dette immediate, donc elle sera desarmee dans la semaine.

Usage :
    forge_rule_distiller.py --commit <sha>              # rapport
    forge_rule_distiller.py --commit <sha> --json
    forge_rule_distiller.py --commit <sha> --ecrire     # ajoute au registre
Sortie : exit 0 si au moins une candidate survit au backtest, 1 sinon.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nokido_agent.tools import forge_golden_rules_ast as G  # noqa: E402

ROOT = G.ROOT
_IGNORE_PREFIXES = ("tests/", "sandbox/", "legacy/", "_attic/")


def _git(*args: str) -> str:
    """`git` sous un compte non proprietaire du depot -> safe.directory explicite."""
    cmd = ["git", "-C", ROOT, "-c", f"safe.directory={ROOT}", *args]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} : {out.stderr.strip()[:200]}")
    return out.stdout


def fichiers_corriges(sha: str) -> list[str]:
    """Fichiers .py de produit touches par le commit (tests et bacs a sable exclus)."""
    lignes = _git("show", "--name-only", "--pretty=format:", sha).splitlines()
    return [ln.strip().replace("\\", "/") for ln in lignes
            if ln.strip().endswith(".py")
            and not ln.strip().replace("\\", "/").startswith(_IGNORE_PREFIXES)]


def source(ref: str, chemin: str) -> str:
    try:
        return _git("show", f"{ref}:{chemin}")
    except RuntimeError as exc:
        print(f"  [info] {chemin} absent de {ref} ({str(exc)[:60]})")
        return ""


def racines_importees(src: str) -> set[str]:
    """Modules importes : seule racine de cible admissible.

    MESURE 2026-08-18, premiere passe : le distillateur a propose
    `appel_interdit depuis.items` — `depuis` est une variable locale, et son
    `.items()` avait juste ete refactore. Une regle nommee d'apres un nom de
    variable ne veut rien dire hors du fichier ou elle est nee. On n'admet donc
    que `module.fonction`, avec `module` reellement importe la.
    """
    noms: set[str] = set()
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return noms   # muet-ok : l'appelant annonce deja la version non analysable
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            noms |= {(a.asname or a.name).split(".")[0] for a in noeud.names}
        elif isinstance(noeud, ast.ImportFrom):
            noms |= {(a.asname or a.name) for a in noeud.names}
    return noms


def appels(src: str) -> dict[str, list[set]]:
    """cible pointee -> un ensemble de kwargs par appel. `None` = **kwargs."""
    out: dict[str, list[set]] = {}
    try:
        arbre = ast.parse(src)
    except SyntaxError as exc:
        print(f"  [info] version non analysable (SyntaxError: {exc.msg})")
        return out
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = G._dotted(noeud.func)
        if not cible:
            continue
        out.setdefault(cible, []).append({k.arg for k in noeud.keywords})
    return out


def candidats(avant: dict[str, list[set]], apres: dict[str, list[set]],
              racines: set[str] | None = None,
              racines_apres: set[str] | None = None) -> list[dict]:
    """Ce que le correctif a CHANGE, traduit en formes closes.

    `racines` = modules importes dans la version FAUTIVE, `racines_apres` dans
    la CORRIGEE : un fix qui remplace `os.system` par `subprocess.run` importe
    justement `subprocess` a ce moment-la, et juger la remplacante sur les
    imports d'avant la rendait invisible.
    """
    trouves: list[dict] = []
    apres_racines = racines if racines_apres is None else racines_apres

    def _qualifiee(cible: str, connues: set[str] | None) -> bool:
        if "." not in cible:
            return False
        return connues is None or cible.split(".")[0] in connues

    def qualifiee(cible: str) -> bool:
        return _qualifiee(cible, racines)

    for cible, apres_appels in apres.items():
        if not qualifiee(cible):
            continue
        avant_appels = avant.get(cible)
        if not avant_appels:
            continue
        # Forme 1 : le fix a ajoute un kwarg que TOUS les appels portent
        # desormais, alors qu'au moins un ne l'avait pas. Un kwarg present
        # partout des l'origine ne prouve rien.
        communs_apres = set.intersection(*[a for a in apres_appels]) if apres_appels else set()
        for kwarg in sorted(k for k in communs_apres if k):
            if any(kwarg not in a and None not in a for a in avant_appels):
                trouves.append({"forme": "appel_sans_kwarg", "cible": cible, "kwarg": kwarg})
    # Forme 2 : la cible a disparu du fichier corrige — mais une disparition
    # seule ne prouve RIEN. MESURE 2026-08-18 sur les 25 derniers correctifs :
    # sans autre condition, cette forme a propose « json.dumps interdit »,
    # « os.path.dirname interdit », « argparse.ArgumentParser interdit » — 12
    # candidates sur 13, toutes absurdes, parce qu'un refactor deplace du code
    # et fait disparaitre des idiomes du fichier. On exige donc une
    # SUBSTITUTION : le correctif a introduit au moins une cible qualifiee
    # nouvelle, signe qu'il a remplace un appel plutot que deplace du texte.
    remplacantes = sorted(c for c in apres if _qualifiee(c, apres_racines) and c not in avant)
    if remplacantes:
        for cible, avant_appels in avant.items():
            if qualifiee(cible) and cible not in apres and avant_appels:
                trouves.append({"forme": "appel_interdit", "cible": cible,
                                "remplace_par": remplacantes})
    return trouves


def _regle(candidat: dict, sha: str) -> dict:
    base = candidat["cible"].replace(".", "-").lower()
    if candidat["forme"] == "appel_sans_kwarg":
        rid = f"apprise-{base}-sans-{candidat['kwarg']}"
        msg = (f"{candidat['cible']} appele sans `{candidat['kwarg']}` — "
               f"defaut deja paye, corrige en {sha[:8]}")
    else:
        rid = f"apprise-{base}-interdit"
        remplace = ", ".join(candidat.get("remplace_par", [])[:3])
        msg = (f"{candidat['cible']} : appel retire par le correctif {sha[:8]}"
               + (f", au profit de {remplace}" if remplace else ""))
    return {"id": rid, "severity": "WARNING", "message": msg, **candidat}


def morsures(regles: list[dict], parent: str, chemin: str) -> dict[str, int]:
    """Ce que les candidates auraient trouve sur la version FAUTIVE."""
    compte: dict[str, int] = {}
    for f in G.scan_source(chemin, parent, regles):
        compte[f["rule"]] = compte.get(f["rule"], 0) + 1
    return compte


def bruit_sur_head(regles: list[dict]) -> dict[str, int]:
    """Un SEUL balayage du depot, quel que soit le nombre de candidates.

    Un scan par candidate coutait 2120 fichiers relus a chaque fois : sur un lot
    de 25 correctifs, l'outil devenait trop lent pour etre lance, donc il ne
    l'aurait plus ete du tout.
    """
    bruit: dict[str, int] = {}
    for fichier in G.collect(["app", "tools"]):
        for f in G.scan_file(fichier, regles):
            if f["rule"].startswith("apprise-"):
                bruit[f["rule"]] = bruit.get(f["rule"], 0) + 1
    return bruit


def verdicts(regles: list[dict], mordu: dict[str, int], bruit: dict[str, int],
             tolerance: int) -> dict[str, dict]:
    resultat = {}
    for r in regles:
        mord, sur_head = mordu.get(r["id"], 0), bruit.get(r["id"], 0)
        if not mord:
            motif = "muette sur la version fautive — elle n'aurait rien vu"
        elif sur_head > tolerance:
            # Mesure 2026-08-18 : `sqlite3.connect sans timeout`, distille du
            # commit 8c0b0089, est une regle JUSTE avec 363 sites existants. La
            # rejeter sans dire comment l'admettre reviendrait a jeter le signal.
            motif = (f"{sur_head} finding(s) sur HEAD — dette existante, pas une "
                     f"nouveaute ; --tolerance {sur_head} pour l'admettre en WARNING "
                     f"en connaissance de cause")
        else:
            motif = ""
        resultat[r["id"]] = {"mord_sur_fautif": mord, "sur_head": sur_head,
                             "retenue": not motif, "motif": motif}
    return resultat


def backtest(regles: list[dict], parent: str, chemin: str, tolerance: int) -> dict[str, dict]:
    """Verdict par regle sur UN fichier : mord sur la version fautive, muette sur HEAD."""
    return verdicts(regles, morsures(regles, parent, chemin),
                    bruit_sur_head(regles), tolerance)


def ecrire(retenues: list[dict]) -> int:
    try:
        with open(G.APPRISES, encoding="utf-8") as fh:
            registre = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ABORT: registre illisible ({exc})")
        return 3
    connues = {r.get("id") for r in registre.get("regles", [])}
    neuves = [r for r in retenues if r["id"] not in connues]
    if not neuves:
        print("[distiller] rien a ecrire : toutes ces regles sont deja au registre")
        return 0
    registre["regles"] = registre.get("regles", []) + neuves
    with open(G.APPRISES, "w", encoding="utf-8") as fh:
        json.dump(registre, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"[distiller] {len(neuves)} regle(s) ajoutee(s) a "
          f"{os.path.relpath(G.APPRISES, ROOT)} (severity WARNING, non promue)")
    return 0


def candidates_du_commit(sha: str) -> list[tuple[dict, str, str]]:
    """[(regle candidate, source fautive, chemin)] pour un commit de fix."""
    out: list[tuple[dict, str, str]] = []
    for chemin in fichiers_corriges(sha):
        parent, corrige = source(f"{sha}^", chemin), source(sha, chemin)
        if not parent or not corrige:
            continue
        for c in candidats(appels(parent), appels(corrige),
                           racines_importees(parent), racines_importees(corrige)):
            out.append((_regle(c, sha), parent, chemin))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Distiller un garde depuis un correctif")
    ap.add_argument("--commit", help="sha du commit de fix")
    ap.add_argument("--lot", type=int, metavar="N",
                    help="distiller les N derniers commits `fix...` d'un coup")
    ap.add_argument("--tolerance", type=int, default=0,
                    help="findings tolerés sur HEAD (defaut 0)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ecrire", action="store_true", help="ajoute les retenues au registre")
    a = ap.parse_args()

    if not a.commit and not a.lot:
        print("ABORT: --commit <sha> ou --lot <N>")
        return 3
    if a.lot:
        shas = _git("log", f"-n{a.lot}", "--grep=^fix", "-E", "--format=%H").split()
    else:
        shas = [_git("rev-parse", a.commit).strip()]

    # cle de regle -> (regle, [(source fautive, chemin, sha)])
    par_id: dict[str, tuple[dict, list[tuple[str, str, str]]]] = {}
    for sha in shas:
        for regle, parent, chemin in candidates_du_commit(sha):
            fiche = par_id.setdefault(regle["id"], (regle, []))
            fiche[1].append((parent, chemin, sha))
    if not par_id:
        print(f"[distiller] {len(shas)} commit(s) examine(s) — aucune candidate")
        return 1

    regles = [regle for regle, _sites in par_id.values()]
    bruit = bruit_sur_head(regles)      # UN seul balayage, quel que soit le lot
    mordu = {rid: sum(morsures([regle], parent, chemin).get(rid, 0)
                      for parent, chemin, _sha in sites)
             for rid, (regle, sites) in par_id.items()}
    verd = verdicts(regles, mordu, bruit, a.tolerance)

    retenues: list[dict] = []
    rapport: list[dict] = []
    for rid, (regle, sites) in sorted(par_id.items()):
        v = verd[rid]
        # Une meme regle distillee de PLUSIEURS correctifs distincts est le
        # signal le plus fort du lot : le meme defaut a mordu plusieurs fois.
        origine = {"commit": sites[0][2][:12], "fichier": sites[0][1],
                   "correctifs": sorted({s[2][:8] for s in sites}),
                   "mord_sur_fautif": v["mord_sur_fautif"]}
        rapport.append({**regle, **v, "origine": origine})
        if v["retenue"]:
            retenues.append({**regle, "origine": origine})

    if a.json:
        print(json.dumps({"commits": len(shas), "candidates": rapport}, ensure_ascii=False))
    else:
        print(f"[distiller] {len(shas)} commit(s) : {len(rapport)} candidate(s), "
              f"{len(retenues)} retenue(s) au backtest")
        for c in rapport:
            etat = "RETENUE" if c["retenue"] else f"rejetee — {c['motif']}"
            marque = (f", vue sur {len(c['origine']['correctifs'])} correctifs"
                      if len(c["origine"]["correctifs"]) > 1 else "")
            print(f"  [{etat}] {c['id']}  ({c['origine']['fichier']}, mord "
                  f"{c['mord_sur_fautif']}x sur le parent, {c['sur_head']} sur HEAD{marque})")
    if a.ecrire and retenues:
        return ecrire(retenues)
    return 0 if retenues else 1


if __name__ == "__main__":
    raise SystemExit(main())
