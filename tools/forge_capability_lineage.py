#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_capability_lineage.py — Phase 7 : LIGNEE de chaque constituant.

CE QUE PHASE 6 NE DIT PAS
=========================
`forge_constituent_archaeology` (Phase 6) ne retient que la DERNIERE suppression :
elle sait qu'un constituant a disparu, jamais quand il est ne, combien de fois il
est revenu, ni ou se trouve le dernier etat ou il vivait. Or c'est precisement ce
qu'il faut pour decider : une fonction supprimee la semaine de sa naissance n'est
pas un patrimoine, une capacite portee 6 mois et retiree hier en est un.

Phase 7 parcourt l'historique du PLUS ANCIEN au PLUS RECENT et bâtit, par
constituant : `apparu -> modifie -> disparu -> reapparu`, avec le **commit temoin**
— le dernier ou le constituant etait present. C'est le point de depart d'un
`diff temoin..HEAD` quand on veut savoir ce qui l'a emporte.

LE PIEGE QUI FAUSSE TOUT : LE DEPLACEMENT
=========================================
En `-U0`, deplacer une fonction dans son fichier produit `-def x` PUIS `+def x`
dans le MEME commit. Compter les lignes naivement ferait de chaque refactor une
disparition suivie d'une resurrection — du bruit pur, en volume. On agrege donc par
COMMIT et on n'applique que le NET (`retires - ajoutes`), ce qui annule les
deplacements sans rien perdre des vraies transitions.

AUTOMATE
========
Etat initial : absent. `+` sur un absent = APPARITION. `-` sur un present =
DISPARITION. Les repetitions (`+` sur un present) ne comptent pas : elles decrivent
une modification, pas un cycle de vie. Le nombre de cycles distingue un aller-retour
de refactor d'une capacite reellement abandonnee.

REGLE DE SONDE : un depot dont le journal est illisible est NOMME, jamais compte
comme vide (leçon des Phases 1 et 6).

Usage :
    forge_capability_lineage.py [--repos nom=chemin ...] [--max-lignes N]
    forge_capability_lineage.py --json --out sandbox/lineages.json
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : lignee de chaque constituant (phase 7)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nokido_agent.tools import forge_constituent_archaeology as A  # noqa: E402  (reutilisation Phase 6)


def _log(m: str) -> None:
    print(f"[lignees] {m}", flush=True)


def _detecter_ajout(ligne: str):
    """(genre, nom) si la ligne AJOUTE une definition.

    On reutilise le detecteur de Phase 6, qui est ancre sur le `-` du diff : une
    ligne ajoutee a le meme corps, seul le prefixe change. Reecrire les motifs ici
    les ferait diverger a la premiere evolution — un seul detecteur, deux prefixes.
    """
    return A.detecter("-" + ligne[1:]) if ligne.startswith("+") else None


def evenements(repo: str, max_lignes: int):
    """Cycles de vie par constituant, du commit le PLUS ANCIEN au plus recent."""
    cmd = ["git", "-c", "safe.directory=*", "-C", repo, "log", "--all", "--reverse",
           "-U0", "--no-renames", "--no-color", "--date=short",
           "--pretty=format:__C__%h|%ad|%s"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, errors="replace", bufsize=1)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"

    vies: dict = {}
    sha = date = ""
    prec_sha = prec_date = ""  # dernier commit CLOTURE : le temoin d'une mort
    fichier = ""
    ajoutes: set = set()
    retires: set = set()
    lues = 0
    tronque = False

    def _cloturer_commit():
        """Applique le NET du commit courant : les deplacements s'annulent."""
        nonlocal prec_sha, prec_date
        if not sha:
            return
        for cle in ajoutes - retires:
            v = vies.setdefault(cle, {"genre": cle[0], "nom": cle[1], "present": False,
                                      "apparitions": 0, "disparitions": 0,
                                      "ne_le": date, "ne_sha": sha, "fichier": fichier,
                                      "temoin_sha": "", "temoin_date": "",
                                      "mort_sha": "", "mort_date": "", "_fichiers": set()})
            # DISPERSION : un nom vu dans 40 fichiers est un mot commun (`source`,
            # `save`, `description` -- des cles de dict), pas une capacite. Un nom vu
            # dans 1 ou 2 en est une. Mesure du 2026-08-16 : sans ce compteur, le
            # rapport etait noye par des cles JSON banales. On borne le set : au-dela
            # de 12 la reponse est deja « commun », inutile de tout retenir.
            if len(v["_fichiers"]) < 12:
                v["_fichiers"].add(fichier)
            if not v["present"]:
                v["present"] = True
                v["apparitions"] += 1
        for cle in retires - ajoutes:
            v = vies.get(cle)
            if v is None or not v["present"]:
                continue  # retrait d'un constituant jamais vu vivant : rien a conclure
            v["present"] = False
            v["disparitions"] += 1
            v["mort_sha"], v["mort_date"] = sha, date
            # TEMOIN = dernier commit ou il vivait, donc CELUI D'AVANT. Le poser ici
            # coute O(1) par mort. Le rafraichir pour tous les vivants a chaque commit
            # donnait le meme resultat en O(constituants x commits) -- des dizaines de
            # millions d'iterations pour une information deja connue a l'instant utile.
            v["temoin_sha"], v["temoin_date"] = prec_sha or sha, prec_date or date
        prec_sha, prec_date = sha, date

    try:
        for ligne in proc.stdout:  # type: ignore[union-attr]
            lues += 1
            if lues > max_lignes:
                tronque = True
                break
            if ligne.startswith("__C__"):
                _cloturer_commit()
                ajoutes, retires = set(), set()
                parts = ligne[5:].rstrip("\n").split("|", 2)
                sha, date = (parts + ["", ""])[:2]
                continue
            if ligne.startswith("--- a/"):
                fichier = ligne[6:].strip()
                continue
            if ligne.startswith("+++ b/"):
                f = ligne[6:].strip()
                if f and f != "dev/null":
                    fichier = f
                continue
            if not fichier.endswith(A._EXT) or A._est_bruit(fichier):
                continue
            if ligne.startswith("+") and not ligne.startswith("+++"):
                hit = _detecter_ajout(ligne)
                if hit:
                    ajoutes.add(hit)
            elif ligne.startswith("-") and not ligne.startswith("---"):
                hit = A.detecter(ligne)
                if hit:
                    retires.add(hit)
        _cloturer_commit()
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001  # muet-ok : flux deja lu, tuer un process
            pass          # deja mort n'apprend rien et ne doit rien casser
    return vies, ("borne atteinte" if tronque else "")


def _etat(v: dict) -> str:
    """Le cycle de vie, en un mot.

    `RESSUSCITE` compte : un constituant deja revenu une fois est une capacite que
    le corps redemande — le supprimer a nouveau merite un avis, pas un silence.
    """
    if v["present"]:
        return "RESSUSCITE" if v["apparitions"] > 1 else "VIVANT"
    return "PERDU_APRES_RETOURS" if v["apparitions"] > 1 else "PERDU"


def analyser(depots: dict, max_lignes: int) -> dict:
    presents = {n: p for n, p in depots.items() if A.est_depot(p)}
    absents = sorted(n for n in depots if n not in presents)
    if not presents:
        return {"observable": False, "raison": f"aucun depot lisible (absents: {absents})"}
    _log(f"depots : {', '.join(sorted(presents))}"
         + (f" | ABSENTS : {', '.join(absents)}" if absents else ""))

    lignees = []
    illisibles = []
    tronques = []
    for n, p in presents.items():
        vies, motif = evenements(p, max_lignes)
        if vies is None:
            illisibles.append({"depot": n, "erreur": motif})
            _log(f"  {n} : INDETERMINE ({motif})")
            continue
        if motif:
            tronques.append(n)
            _log(f"  {n} : {motif} — lignees PARTIELLES, a lire comme incompletes")
        for v in vies.values():
            if v["present"]:
                # Vivant : son temoin est l'etat courant, il n'y a rien a retrouver.
                v["temoin_sha"], v["temoin_date"] = "HEAD", ""
            v["n_fichiers"] = len(v.pop("_fichiers"))
            v["specifique"] = v["n_fichiers"] <= 3
            lignees.append({"depot": n, **v, "etat": _etat(v)})
        _log(f"  {n} : {len(vies)} constituants suivis")

    par_etat: dict = {}
    for c in lignees:
        par_etat[c["etat"]] = par_etat.get(c["etat"], 0) + 1
    return {"observable": True, "depots_analyses": sorted(presents),
            "depots_absents": absents, "depots_illisibles": illisibles,
            "depots_tronques": tronques, "resume": par_etat, "lignees": lignees}


def main() -> int:
    ap = argparse.ArgumentParser(description="Lignees des constituants (Phase 7)")
    ap.add_argument("--repos", nargs="*", default=[])
    ap.add_argument("--out", default=os.path.join(ROOT, "sandbox", "lineages.json"))
    # ATTENTION : en parcours ASCENDANT, la borne coupe le PRESENT, pas le passe.
    # Mesure du 2026-08-16 : a 4 000 000 le depot nokido etait tronque, et les pertes
    # du 14/08 -- celles qui ont motive cette phase -- n'etaient jamais atteintes. Une
    # borne posee pour eviter l'emballement supprimait exactement ce qu'on cherche.
    # Elle reste, comme garde-fou, mais assez haute pour ne plus mordre ; et tout
    # depot tronque est NOMME dans le rapport, jamais rendu comme complet.
    ap.add_argument("--max-lignes", type=int, default=60_000_000)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()

    depots = dict(A.DEPOTS_DEFAUT)
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

    _log("etats : " + ", ".join(f"{k}={v}" for k, v in sorted(res["resume"].items())))
    for x in res["depots_illisibles"]:
        _log(f"  INDETERMINE sur {x['depot']} : {x['erreur']}")
    # Les plus couteux d'abord : longtemps portes, revenus, puis perdus.
    perdus = [c for c in res["lignees"] if not c["present"] and c["specifique"]]
    generiques = sum(1 for c in res["lignees"] if not c["present"] and not c["specifique"])
    perdus.sort(key=lambda c: (c["apparitions"] > 1, c.get("mort_date", "")), reverse=True)
    _log(f"{generiques} perte(s) ecartee(s) comme noms COMMUNS (vus dans >3 fichiers)")
    _log(f"top {a.top} pertes SPECIFIQUES (retours d'abord, puis les plus recentes) :")
    for c in perdus[:a.top]:
        _log(f"  [{c['etat']:<19}] {c['nom']:<32} {c['depot']}  "
             f"ne {c['ne_le']} ({c['ne_sha']}) mort {c['mort_date']} ({c['mort_sha']}) "
             f"| {c['apparitions']} apparition(s) | temoin {c['temoin_sha'] or '?'}")
    _log(f"ecrit : {os.path.relpath(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
