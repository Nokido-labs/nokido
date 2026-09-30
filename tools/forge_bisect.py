#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_bisect.py — recherche binaire du commit coupable, sur critere REEL.

`git bisect` trouve le commit fautif en ~12 etapes sur 4000, mais il ne vaut que
par la fiabilite de son verdict : il faut une commande qui reponde OUI/NON sans
ambiguite. Nokido en possede desormais plusieurs — tests NR, cliquet de
couverture, Golden State, Golden Rules, duplication — c'est ce qui rend cet
outil utilisable aujourd'hui alors qu'il ne l'etait pas hier.

Deux choix de conception qui ne sont pas negociables :

1. **Jamais dans le depot principal.** Bisect fait des checkout : lancer cela
   dans l'arbre de travail ferait basculer, en vol, le code que le hub execute.
   Le 2026-08-02, couper son propre canal a laisse le hub mort douze minutes.
   On travaille donc dans un `git worktree` jetable, hors du depot.

2. **Les sous-depots suivent.** Le super-depot ne versionne que des POINTEURS :
   sans `git submodule update` a chaque etape, on teste l'ancien contenu avec un
   nouveau pointeur, et le verdict ne veut rien dire. C'est precisement le cas
   d'un depot ou la regression vient d'un sous-module.

Usage :
    forge_bisect.py --bon <sha_ancien> --critere nr:tests/nr/test_observabilite_nr.py
    forge_bisect.py --bon HEAD~200 --mauvais HEAD --critere golden-rules
    forge_bisect.py --bon v1.2 --critere "cmd:python tools/mon_check.py"
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

__FORGE_COLOR__ = "qualite/quality : recherche binaire du commit coupable sur critere reel"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Scratch DURABLE et gitignore, jamais le temp systeme. tempfile.gettempdir()
# rend C:/tmp : volatile, purge, world-writable -- exactement le wrapper ancre
# sous C:\tmp qui a saute le 2026-08-12 (montage V: perdu, gate fail-closed sur
# 100% des appels). Le worktree git exige un vrai systeme de fichiers (pas de
# wasm), mais on bisecte NOTRE propre historique -- du code de confiance, aucune
# isolation d'untrusted requise ; ce qui compte est que rien n'atterrisse dans
# un espace volatile. sandbox/ est gitignore (n'apparait pas dans git status) et
# vit avec le depot.
_SCRATCH = os.path.join(ROOT, "sandbox", "bisect")

# Criteres deja outilles dans le depot : un verdict binaire, sans service externe.
# La cle est ce qu'on tape ; la valeur, la commande passee a `git bisect run`.
CRITERES = {
    "golden-rules": ["tools/forge_golden_rules_ast.py", "app", "tools", "--socle"],
    "duplication": ["tools/forge_dup_detector.py", "app", "tools", "--socle"],
    "cliquet": ["-m", "pytest", "tests/nr/test_nr_coverage_ratchet_nr.py", "-q",
                "-p", "no:cacheprovider"],
    "golden": ["tools/forge_golden_state.py", "--verify"],
}


def _git(args: list[str], cwd: str | None = None, timeout: int = 600):
    return subprocess.run(["git", "-c", f"safe.directory={ROOT}", *args],
                          capture_output=True, text=True, errors="replace",
                          cwd=cwd or ROOT, timeout=timeout)


def _python() -> str:
    """Interpreteur qui existe pour le compte courant (cf. forge_mutation_test)."""
    try:
        sys.path.insert(0, ROOT)
        from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON  # type: ignore
        if os.path.exists(LAFORGE_PYTHON):
            return LAFORGE_PYTHON
    except Exception:  # noqa: BLE001 - module absent ou chemin derive de ~ inexistant
        pass
    return sys.executable


def construire_commande(critere: str) -> list[str]:
    """Traduit un critere en commande de verdict (rc=0 bon, rc!=0 mauvais)."""
    py = _python()
    if critere.startswith("cmd:"):
        return critere[4:].split()
    if critere.startswith("nr:"):
        return [py, "-m", "pytest", critere[3:], "-q", "-p", "no:cacheprovider"]
    if critere in CRITERES:
        return [py, *CRITERES[critere]]
    raise SystemExit(f"critere inconnu : {critere}. Connus : {sorted(CRITERES)} "
                     "ou nr:<chemin_test> ou cmd:<commande>")


def _a_des_sousdepots(arbre: str) -> bool:
    return os.path.exists(os.path.join(arbre, ".gitmodules"))


class CompositionInstable(RuntimeError):
    """Les sous-depots n'ont pas pu etre alignes sur les pointeurs du commit :
    juger ici testerait l'ancien contenu, le verdict ne signifierait rien."""


def _sync_sousdepots(arbre: str) -> tuple[bool, str]:
    """Aligne les sous-depots sur les gitlinks du commit courant, PUIS verifie
    que chaque HEAD de sous-depot EGALE le pointeur enregistre.

    `submodule update` peut echouer partiellement (reseau, ACL) sans code non
    nul evident ; on ne se fie donc pas au seul rc, on CONFRONTE le HEAD reel au
    pointeur. Sans quoi un nouveau pointeur sur un ancien contenu passe pour teste.
    """
    r = _git(["submodule", "update", "--init", "--recursive", "--force"], cwd=arbre)
    if r.returncode != 0:
        return False, f"submodule update rc={r.returncode}: {(r.stderr or '')[:160]}"
    # gitlink attendu (ls-tree) vs HEAD reel de chaque sous-depot
    lt = _git(["ls-tree", "-r", "HEAD"], cwd=arbre)
    if lt.returncode != 0:
        return False, "ls-tree muet apres sync"
    for ligne in (lt.stdout or "").splitlines():
        champs = ligne.split()
        if len(champs) >= 4 and champs[0] == "160000" and champs[1] == "commit":
            chemin = ligne.split("\t", 1)[1].strip() if "\t" in ligne else champs[3]
            attendu = champs[2]
            h = _git(["rev-parse", "HEAD"], cwd=os.path.join(arbre, chemin))
            reel = (h.stdout or "").strip()
            if h.returncode != 0 or reel != attendu:
                return False, (f"{chemin} desynchronise : pointeur {attendu[:12]} "
                               f"!= HEAD {reel[:12] or '?'}")
    return True, ""


def _script_etape(arbre: str, commande: list[str], sousdepots: bool) -> str:
    """Ecrit le script que `git bisect run` appellera a chaque etape.

    Il synchronise les sous-depots AVANT de juger, et fait de cette sync une
    PRECONDITION DURE : si elle echoue, le script rend 125 -- code que
    `git bisect run` traite comme « commit non testable » (skip). Sans cette
    barriere, un pointeur neuf sur un contenu ancien serait juge quand meme, et
    bisect pourrait designer un commit teste avec la MAUVAISE composition. C'est
    precisement le cas ou la regression vient d'un sous-depot.
    """
    if os.name == "nt":
        lignes = ["@echo off"]
        if sousdepots:
            lignes.append("git submodule update --init --recursive --force || exit /b 125")
        lignes.append(" ".join(f'"{c}"' if " " in c else c for c in commande))
    else:
        lignes = ["#!/bin/sh"]
        if sousdepots:
            lignes.append("git submodule update --init --recursive --force || exit 125")
        lignes.append(" ".join(f'"{c}"' if " " in c else c for c in commande))
    ext = ".bat" if os.name == "nt" else ".sh"
    chemin = os.path.join(arbre, f"_bisect_etape{ext}")
    with open(chemin, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lignes) + "\n")
    if os.name != "nt":
        os.chmod(chemin, 0o755)
    return chemin


def _verdict(arbre: str, commande: list[str], sousdepots: bool) -> bool:
    """True si le critere est SATISFAIT (etat sain) a l'etat courant de l'arbre.

    Leve CompositionInstable si les sous-depots n'ont pas pu etre alignes : on
    ne rend jamais un verdict sur une composition qu'on n'a pas su reconstituer.
    """
    if sousdepots:
        ok, motif = _sync_sousdepots(arbre)
        if not ok:
            raise CompositionInstable(motif)
    r = subprocess.run(commande, capture_output=True, text=True,
                       errors="replace", cwd=arbre, timeout=1800)
    return r.returncode == 0


def executer(bon: str, mauvais: str, critere: str, garder: bool = False) -> dict:
    commande = construire_commande(critere)
    os.makedirs(_SCRATCH, exist_ok=True)
    arbre = os.path.join(_SCRATCH, f"wt_{os.getpid()}")

    r = _git(["worktree", "add", "--detach", arbre, mauvais])
    if r.returncode != 0:
        return {"erreur": f"worktree impossible : {(r.stderr or '').strip()[:300]}"}
    sousdepots = _a_des_sousdepots(arbre)

    try:
        # Verifier les DEUX bornes avant de chercher : un bisect lance sur des
        # bornes fausses converge quand meme, et designe un innocent.
        try:
            _borne_mauvaise = _verdict(arbre, commande, sousdepots)
        except CompositionInstable as e:
            return {"erreur": f"composition instable sur {mauvais} : {e} — "
                              "impossible d'aligner les sous-depots, bisect avorte"}
        if _borne_mauvaise:
            return {"erreur": f"le critere passe DEJA sur {mauvais} : il n'y a rien "
                              "a chercher (ou le critere ne detecte pas la panne)"}
        _git(["checkout", "--detach", bon], cwd=arbre)
        try:
            _borne_bonne = _verdict(arbre, commande, sousdepots)
        except CompositionInstable as e:
            return {"erreur": f"composition instable sur {bon} : {e} — "
                              "impossible d'aligner les sous-depots, bisect avorte"}
        if not _borne_bonne:
            return {"erreur": f"le critere echoue DEJA sur {bon} : cette borne n'est "
                              "pas saine, remonter plus loin dans l'historique"}

        _git(["bisect", "start"], cwd=arbre)
        _git(["bisect", "bad", mauvais], cwd=arbre)
        _git(["bisect", "good", bon], cwd=arbre)
        script = _script_etape(arbre, commande, sousdepots)
        run = _git(["bisect", "run", script], cwd=arbre, timeout=7200)
        sortie = (run.stdout or "") + (run.stderr or "")

        coupable = ""
        for ligne in sortie.splitlines():
            if "is the first bad commit" in ligne:
                coupable = ligne.split()[0]
                break
        if not coupable:
            return {"erreur": "bisect n'a designe aucun commit",
                    "sortie": sortie[-1200:]}

        det = _git(["show", "--stat", "--pretty=format:%H%n%an%n%ad%n%s", coupable],
                   cwd=arbre)
        return {"coupable": coupable, "critere": critere,
                "sous_depots": sousdepots, "detail": (det.stdout or "")[:2500]}
    finally:
        _git(["bisect", "reset"], cwd=arbre)
        if not garder:
            _git(["worktree", "remove", "--force", arbre])
            shutil.rmtree(arbre, ignore_errors=True)
            _git(["worktree", "prune"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Bisect gouverne Nokido")
    ap.add_argument("--bon", required=True, help="commit ou le critere PASSE")
    ap.add_argument("--mauvais", default="HEAD", help="commit ou le critere ECHOUE")
    ap.add_argument("--critere", required=True,
                    help=f"{sorted(CRITERES)} | nr:<chemin_test> | cmd:<commande>")
    ap.add_argument("--garder-worktree", action="store_true",
                    help="ne pas detruire l'arbre jetable (inspection post-mortem)")
    args = ap.parse_args()

    res = executer(args.bon, args.mauvais, args.critere, args.garder_worktree)
    if res.get("erreur"):
        print("ABORT: " + res["erreur"])
        if res.get("sortie"):
            print(res["sortie"])
        return 2
    print(f"[bisect] critere « {res['critere'] } » — sous-depots synchronises : "
          f"{'oui' if res['sous_depots'] else 'aucun'}")
    print(f"[bisect] premier commit fautif : {res['coupable']}")
    print(res["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
