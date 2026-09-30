#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_success_oplog.py — la memoire des VICTOIRES, pas des intentions.

__FORGE_COLOR__ ci-dessous : memoire, pas qualite.

LE DEFAUT QU'IL CORRIGE (constat owner, 2026-08-31)
===================================================
La documentation de Nokido dit surtout « ce module DEVRAIT faire X » ou « cet
outil PERMET de faire Y ». Ce qui sert a un reflexe est l'inverse :

    X A ETE FAIT, avec CETTE procedure, sur CETTE version, et ca a REUSSI.

`forge_symptom_index` indexe deja les symptomes ET les aveux d'erreur : Nokido a
donc la memoire de ses ECHECS, pas celle de ses reussites. Ce module est le
miroir manquant.

LA SOURCE EST GRATUITE ET DEJA LA
=================================
Un commit de correction est une verite terrain datee : quelqu'un a constate un
symptome, applique une procedure, et juge le resultat suffisant pour le
committer. `forge_axis_backtest` s'en sert deja comme verite terrain pour
mesurer ses axes. On ne fabrique aucune donnee nouvelle : on la RANGE.

TROIS ETATS, ET C'EST TOUT L'ENJEU
==================================
  CONSTATE  un correctif a ete committe pour ce symptome. C'est un FAIT.
  PROUVE    une mesure POSTERIEURE a confirme l'extinction du symptome.
  INFIRME   le symptome est revenu apres ce correctif.

On n'ecrit JAMAIS `PROUVE` a l'ecriture. Le faire reviendrait a enregistrer une
intention en la deguisant en preuve — exactement le defaut qu'on corrige. La
promotion est le travail d'une passe separee, qui dispose du recul.

Usage :
  forge_success_oplog.py --backfill 300     # miner l'historique
  forge_success_oplog.py --commit HEAD      # enregistrer un commit
  forge_success_oplog.py --chercher "database is locked"
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/oplog-succes"

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "sandbox" / "success_oplog.jsonl"

CONSTATE, PROUVE, INFIRME = "CONSTATE", "PROUVE", "INFIRME"

# Seuls les commits qui REPARENT comptent. Un `feat` cree une capacite ; il ne
# constate pas la disparition d'un symptome, donc il n'a pas sa place ici.
_PREFIXES_CORRECTIFS = ("fix", "perf", "revert", "hotfix")
_RE_SUJET = re.compile(r"^(?P<type>[a-z]+)(\((?P<scope>[^)]*)\))?\s*:\s*(?P<sujet>.+)$")
_RE_JETON = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{3,}")
# Mots trop courants pour porter un symptome. Mesure du 2026-08-31 : sur la
# question « le hub rend database is locked pendant une ecriture concurrente »,
# QUATRE des cinq procedures remontees matchaient sur le seul jeton « rend ».
# Un match sur un verbe francais est du bruit, et le bruit en tete de reponse
# coute plus cher qu'une reponse vide : il fait ouvrir des pistes mortes.
_VIDES = {"pour", "dans", "avec", "sans", "plus", "moins", "cette", "leur",
          "quand", "alors", "etait", "etre", "faire", "fait", "tout", "tous",
          "rend", "rendre", "rendu", "rends", "pendant", "avant", "apres",
          "chaque", "meme", "aussi", "depuis", "entre", "vers", "selon",
          "comme", "donc", "mais", "elle", "celui", "cela", "ceci", "leurs",
          "sont", "peut", "doit", "deja", "encore", "ainsi", "puis", "afin",
          "voir", "lire", "mettre", "prendre", "passer", "laisser", "quel",
          "quelle", "toute", "toutes", "autre", "autres", "bien", "trop"}


def _git(*args, root: Path | None = None) -> str:
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(root or ROOT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60)
    return r.stdout or ""


def _jetons(txt: str) -> list:
    vus = []
    for m in _RE_JETON.findall(txt or ""):
        b = m.lower()
        if b in _VIDES or b in vus:
            continue
        vus.append(b)
    return vus[:20]


def analyser_commit(sha: str, root: Path | None = None) -> dict | None:
    """Rend l'entree d'oplog d'un commit CORRECTIF, ou None si ce n'en est pas un.

    Rendre None n'est pas un echec : c'est le cas majoritaire, et le compter est
    ce qui permet de dire quelle FRACTION de l'historique nourrit la memoire.
    """
    brut = _git("show", "-s", "--format=%H%n%ad%n%s%n%b", "--date=short", sha,
                root=root).strip()
    if not brut:
        return None
    lignes = brut.split("\n")
    plein, date, sujet = lignes[0], lignes[1], lignes[2]
    corps = "\n".join(lignes[3:])
    m = _RE_SUJET.match(sujet.strip())
    if not m or m.group("type") not in _PREFIXES_CORRECTIFS:
        return None
    fichiers = [f for f in _git("show", "--name-only", "--format=", sha,
                                root=root).split("\n") if f.strip()]
    tests = [f for f in fichiers if f.startswith("tests/")]
    return {
        "commit": plein[:12],
        "date": date,
        "symptome": m.group("sujet").strip(),
        "scope": m.group("scope") or "",
        "jetons": _jetons(sujet + " " + corps[:600]),
        "procedure": {"fichiers": fichiers[:12], "n_fichiers": len(fichiers),
                      "tests_dans_le_commit": tests[:6]},
        # Un correctif SANS test n'est pas moins reel, mais il est moins
        # reutilisable : on le dit au lieu de le noyer.
        "reutilisable": bool(tests),
        "etat": CONSTATE,
    }


def entrees(log: Path | None = None) -> list:
    """Le journal REPLIE : une entree par commit, la DERNIERE gagne.

    Le journal reste append-only (consigne owner : rien n'est supprime). Une
    promotion d'etat s'ajoute donc a la suite, et c'est la lecture qui replie.
    Sans ce repli, `chercher` rendrait a la fois l'etat initial et l'etat promu
    du meme correctif — deux verdicts contradictoires pour un seul evenement.
    """
    chemin = log or LOG
    if not chemin.exists():
        return []
    par_commit: dict = {}
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(ligne)
        except ValueError:
            continue          # ligne coupee : ignoree, jamais fatale
        c = e.get("commit")
        if not c:
            continue
        if c in par_commit:
            par_commit[c].update(e)   # la promotion complete, elle n'efface pas
        else:
            par_commit[c] = e
    return list(par_commit.values())


# Une recidive suppose une DISTANCE. Mesure du 2026-08-31, premiere passe reelle :
# 10 infirmations sur 15 examinees, dont deux commits du MEME JOUR qui
# s'infirmaient MUTUELLEMENT, et des series d'ameliorations successives sur un
# meme fichier prises pour des retours de defaut. Iterer sur un fichier dans la
# journee est du travail en cours ; un defaut n'est « revenu » que s'il
# reapparait apres que le correctif a eu le temps de tenir.
ECART_RECIDIVE_JOURS = 14


def _jours(a: str, b: str) -> float | None:
    """Ecart en jours entre deux dates ISO. None si l'une est illisible."""
    try:
        return (datetime.fromisoformat(str(b)[:10])
                - datetime.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


def recidive(entree: dict, posterieures: list, min_jetons: int = 2,
             ecart_jours: int = ECART_RECIDIVE_JOURS) -> dict | None:
    """Le symptome est-il REVENU apres ce correctif ?

    TROIS conditions cumulatives, toutes payees par une fausse alerte mesuree :
      - au moins deux jetons de fond en commun (un seul accuserait tout commit
        du meme domaine) ;
      - au moins un fichier en commun ;
      - un ecart d'au moins `ecart_jours` jours, STRICTEMENT posterieur.

    Marquer INFIRME a tort retire une procedure des propositions : le cout des
    deux erreurs n'est pas symetrique, donc on s'abstient au moindre doute.
    """
    mes_jetons = set(entree.get("jetons") or []) | set(_jetons(entree.get("symptome") or ""))
    mes_fichiers = set((entree.get("procedure") or {}).get("fichiers") or [])
    if not mes_fichiers:
        return None
    for p in posterieures:
        if p.get("commit") == entree.get("commit"):
            continue
        ecart = _jours(entree.get("date") or "", p.get("date") or "")
        if ecart is None or ecart < ecart_jours:
            continue          # meme journee ou iteration proche : pas une recidive
        communs = mes_jetons & (set(p.get("jetons") or [])
                                | set(_jetons(p.get("symptome") or "")))
        fichiers = mes_fichiers & set((p.get("procedure") or {}).get("fichiers") or [])
        if len(communs) >= min_jetons and fichiers:
            return {"commit": p.get("commit"), "date": p.get("date"),
                    "ecart_jours": ecart,
                    "jetons_communs": sorted(communs)[:6],
                    "fichiers_communs": sorted(fichiers)[:4]}
    return None


def reviser_infirmations(log: Path | None = None,
                         ecart_jours: int = ECART_RECIDIVE_JOURS) -> dict:
    """Rend a CONSTATE les INFIRME que le critere corrige ne retient plus.

    Le journal est append-only : on n'efface pas un verdict errone, on en ecrit
    un nouveau qui dit POURQUOI il est retire. Un verdict faux qu'on supprime
    devient invisible ; un verdict faux qu'on corrige reste instructif.
    """
    toutes = entrees(log)
    rendus = []
    for e in toutes:
        if e.get("etat") != INFIRME:
            continue
        if recidive(e, toutes, ecart_jours=ecart_jours) is None:
            promouvoir(e["commit"], CONSTATE,
                       {"revision": "infirmation retiree : ecart < %d jours ou "
                                    "critere non satisfait" % ecart_jours,
                        "ancienne_preuve": e.get("preuve")}, log=log)
            rendus.append(e["commit"])
    return {"infirme_avant": sum(1 for e in toutes if e.get("etat") == INFIRME),
            "rendus_a_constate": len(rendus), "commits": rendus[:10]}


def _terminer_ligne(chemin: Path) -> None:
    """Garantit que le journal finit par un saut de ligne AVANT tout ajout.

    Sans ce garde, un ajout se colle a la derniere entree et corrompt DEUX
    enregistrements d'un coup : celui d'avant et celui qu'on ecrit. Mesure du
    2026-08-31 : trois tests de promotion rouges, une seule cause. Un journal
    append-only finit toujours par rencontrer un fichier sans fin de ligne
    (troncature, edition a la main, ecriture interrompue).
    """
    try:
        if chemin.exists() and chemin.stat().st_size:
            with open(chemin, "rb") as fh:
                fh.seek(-1, 2)
                if fh.read(1) != b"\n":
                    with open(chemin, "a", encoding="utf-8") as out:
                        out.write("\n")
    except OSError as exc:  # noqa: BLE001 - le dire, ne pas ecrire a l'aveugle
        print("[oplog] fin de ligne non verifiable (%s)" % type(exc).__name__,
              flush=True)


def promouvoir(commit: str, etat: str, preuve: dict,
               log: Path | None = None) -> dict:
    """Ajoute un enregistrement d'etat. Append-only : rien n'est reecrit."""
    chemin = log or LOG
    e = {"commit": commit, "etat": etat, "preuve": preuve,
         "promu_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    chemin.parent.mkdir(parents=True, exist_ok=True)
    _terminer_ligne(chemin)
    with open(chemin, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def _tests_gates(root: Path) -> set:
    """Les tests reellement joues en CI (whitelist PURE_TESTS de ci_local)."""
    try:
        src = (root / "tools" / "ci_local.py").read_text(encoding="utf-8",
                                                         errors="replace")
    except OSError:
        return set()
    return set(re.findall(r'"(tests/nr/[^"]+\.py)"', src))


def _lanceur_pytest(tests: list, root: Path) -> bool:
    """Vrai si TOUS les tests passent. Un echec d'execution vaut FAUX."""
    import subprocess as _sp
    import sys as _s
    try:
        r = _sp.run([_s.executable, "-m", "pytest", *tests, "-q", "--no-header",
                     "-p", "no:cacheprovider"],
                    cwd=str(root), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=300)
        return r.returncode == 0
    except (OSError, _sp.SubprocessError):
        return False


def evaluer(log: Path | None = None, root: Path | None = None,
            max_examen: int = 15, max_execution: int = 3,
            lanceur=None) -> dict:
    """Fait passer des entrees de CONSTATE a PROUVE ou INFIRME.

    DEUX REGLES, ET UNE ABSTENTION ASSUMEE :

      INFIRME  un correctif posterieur a re-touche les memes fichiers avec un
               symptome proche. Le probleme est revenu : c'est une mesure.

      PROUVE   le correctif a livre des tests, ces tests sont dans PURE_TESTS
               (donc joues en CI), et ils passent MAINTENANT. C'est une mesure
               POSTERIEURE et EXECUTABLE.

      sinon    l'entree reste CONSTATE.

    CE QU'ON NE FAIT PAS, ET POURQUOI. La consigne initiale etait « PROUVE quand
    une passe posterieure ne revoit plus le symptome ». Promouvoir sur une
    ABSENCE de recidive serait un argument du silence : ne pas avoir revu un
    defaut ne prouve pas qu'il a disparu, seulement qu'on ne l'a pas croise.
    Une preuve doit etre POSITIVE et rejouable — d'ou l'exigence d'un test vert.
    Les entrees sans test restent CONSTATE : proposables comme piste historique,
    jamais presentees comme sures.
    """
    racine = root or ROOT
    toutes = entrees(log)
    candidates = [e for e in toutes if e.get("etat") == CONSTATE]
    gates = _tests_gates(racine)
    lanceur = lanceur or (lambda tests: _lanceur_pytest(tests, racine))
    bilan = {"examinees": 0, "prouvees": 0, "infirmees": 0, "inchangees": 0,
             "sans_test": 0, "tests_hors_ci": 0, "executions": 0}

    for e in candidates[:max_examen]:
        bilan["examinees"] += 1
        rec = recidive(e, toutes)
        if rec:
            promouvoir(e["commit"], INFIRME, {"recidive": rec}, log=log)
            bilan["infirmees"] += 1
            continue
        tests = [t for t in (e.get("procedure") or {}).get("tests_dans_le_commit") or []]
        if not tests:
            bilan["sans_test"] += 1
            bilan["inchangees"] += 1
            continue
        hors = [t for t in tests if t not in gates]
        if hors:
            # Un test hors whitelist ne tourne pas en CI : il ne prouve rien.
            bilan["tests_hors_ci"] += 1
            bilan["inchangees"] += 1
            continue
        if bilan["executions"] >= max_execution:
            bilan["inchangees"] += 1
            continue
        bilan["executions"] += 1
        if lanceur(tests):
            promouvoir(e["commit"], PROUVE,
                       {"tests": tests, "verifie_le": datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")}, log=log)
            bilan["prouvees"] += 1
        else:
            bilan["inchangees"] += 1
    bilan["candidates_restantes"] = max(0, len(candidates) - bilan["examinees"])
    return bilan


def capacites_touchees(fichiers, log: Path | None = None,
                       etats: tuple = (PROUVE,), root: Path | None = None) -> list:
    """Les capacites dont le PERIMETRE est touche par ces fichiers.

    POURQUOI (question ouverte depuis le 2026-08-12, la plus recente des trois).
    Nokido possede la preuve qu'une capacite fonctionnait -- un correctif, ses
    tests, et une mesure posterieure qui les a vus verts. Rien n'utilisait cette
    preuve au moment ou un agent modifie les memes fichiers. Une regression
    etait donc traitee comme un bug neuf, alors que c'est la RUPTURE D'UN
    INVARIANT HISTORIQUE : on sait que ca marchait, et on sait avec quel test le
    verifier.

    Par defaut on ne remonte que les PROUVE : un CONSTATE n'a pas de mesure
    posterieure, donc rien a proteger. Avertir sur lui ferait crier le garde
    195 fois sur 199 -- et un garde qui crie a faux se fait desarmer.

    Les tests viennent du commit qui a PROUVE la capacite : un test renomme ou retire
    depuis resterait cite, et l'avertissement ferait rejouer un fichier qui n'existe plus
    (vecu le 2026-09-27 : tests/nr/test_forge_veille_campagne_nr.py). `tests` ne porte donc
    que les fichiers PRESENTS sous `root` ; les autres sont DITS dans `tests_absents`.
    """
    racine = Path(root) if root is not None else ROOT
    vises = {str(f).replace("\\", "/").lstrip("./") for f in (fichiers or []) if f}
    if not vises:
        return []
    sortie = []
    for e in entrees(log):
        if e.get("etat") not in etats:
            continue
        perimetre = {str(f).replace("\\", "/")
                     for f in (e.get("procedure") or {}).get("fichiers") or []}
        communs = {p for p in perimetre
                   if any(v.endswith(p) or p.endswith(v) for v in vises)}
        if not communs:
            continue
        cites = list((e.get("procedure") or {}).get("tests_dans_le_commit") or [])
        sortie.append({
            "commit": e.get("commit"), "date": e.get("date"),
            "symptome": (e.get("symptome") or "")[:90],
            "etat": e.get("etat"),
            "fichiers_communs": sorted(communs)[:4],
            "tests": [t for t in cites if (racine / t).is_file()],
            "tests_absents": [t for t in cites if not (racine / t).is_file()],
        })
    return sortie


def _deja(chemin: Path) -> set:
    if not chemin.exists():
        return set()
    vus = set()
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            vus.add(json.loads(ligne).get("commit"))
        except ValueError:
            continue          # ligne corrompue : ignoree, jamais fatale
    return vus


def enregistrer(sha: str = "HEAD", root: Path | None = None,
                log: Path | None = None) -> dict | None:
    """Append-only, idempotent par sha."""
    chemin = log or LOG
    e = analyser_commit(sha, root=root)
    if not e:
        return None
    if e["commit"] in _deja(chemin):
        return e
    chemin.parent.mkdir(parents=True, exist_ok=True)
    _terminer_ligne(chemin)
    with open(chemin, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def chercher(terme: str, limite: int = 5, log: Path | None = None) -> list:
    """Le MATCHER : ce probleme ressemble-t-il a quelque chose de deja repare ?"""
    chemin = log or LOG
    if not chemin.exists():
        return []
    besoin = set(_jetons(terme))
    if not besoin:
        return []
    scores = []
    for e in entrees(chemin):
        champ = set(e.get("jetons") or []) | set(_jetons(e.get("symptome") or ""))
        commun = besoin & champ
        if commun:
            scores.append((len(commun), e, sorted(commun)))
    scores.sort(key=lambda t: -t[0])
    # `.get` et non l'index : le journal replie peut porter un enregistrement de
    # promotion arrive sans son entree d'origine (journal tronque, reprise).
    return [{"score": n, "commit": e.get("commit"), "date": e.get("date", "?"),
             "symptome": e.get("symptome", "(symptome inconnu)"),
             "etat": e.get("etat", CONSTATE),
             "reutilisable": e.get("reutilisable"),
             "fichiers": (e.get("procedure") or {}).get("fichiers", [])[:5],
             "termes_communs": c}
            for n, e, c in scores[:limite]]


def backfill(n: int = 300, root: Path | None = None, log: Path | None = None) -> dict:
    shas = [s for s in _git("log", "-%d" % n, "--format=%H", root=root).split("\n")
            if s.strip()]
    ecrits = ignores = 0
    for s in shas:
        if enregistrer(s, root=root, log=log):
            ecrits += 1
        else:
            ignores += 1
    # Le DENOMINATEUR : sans lui, « 40 succes enregistres » ne dit pas si c'est
    # 40 sur 45 ou 40 sur 4000.
    return {"commits_examines": len(shas), "correctifs": ecrits,
            "non_correctifs": ignores}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Memoire des corrections reussies.")
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--commit", default="")
    ap.add_argument("--chercher", default="")
    a = ap.parse_args()
    if a.backfill:
        print(json.dumps(backfill(a.backfill), ensure_ascii=False))
    elif a.commit:
        print(json.dumps(enregistrer(a.commit), ensure_ascii=False))
    elif a.chercher:
        print(json.dumps(chercher(a.chercher), ensure_ascii=False, indent=1))
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
