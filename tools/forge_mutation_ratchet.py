#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_mutation_ratchet.py — cliquet de mutation sur les surfaces critiques.

`forge_mutation_test.py` MESURE (combien de mutants survivent) mais son verdict ne
BLOQUE pas : 4 survivants sur 35 rendaient quand meme exit 0. Ce cliquet ferme ce
faux-vert, exactement comme les Golden Rules ferment le leur : il gele le nombre de
survivants par (module, genre) et ECHOUE des qu'une NOUVELLE faiblesse apparait --
un test qui cesse de couvrir un comportement deja protege.

Surfaces visees : les OUTILS ANTI-REGRESSION eux-memes. La critique du 2026-08-15
le dit — « Nokido souffre de bugs dans les instruments censes prouver qu'il n'a pas
de bugs ». On mute donc en priorite ces instruments, sur leurs propres tests NR.

COUT : chaque mutant relance la suite de tests du surface. On borne (max_mutants
par surface, poignee de surfaces) pour tenir sous ~90 s. Ce n'est pas une passe
exhaustive : c'est une sentinelle sur ce qui doit ABSOLUMENT rester teste.

Usage :
    forge_mutation_ratchet.py --check          # 0 conforme / 1 nouvelle faiblesse
    forge_mutation_ratchet.py --ecrire-socle   # fige l'etat courant
    forge_mutation_ratchet.py --json

REJOUER EN LOCAL SANS COMPTE PRIVILEGIE (mesure 2026-08-18)
----------------------------------------------------------
Muter, c'est ECRIRE dans le fichier source. Or `tools/` ne donne que (RX) au
groupe `LaForgeSandboxUsers` : tout job detache y meurt en PermissionError, et
le cliquet rend INDETERMINE — pas « aucun survivant ». Longtemps le verdict
n'etait donc accessible qu'en CI (~10 min par boucle).

La sortie ne demande AUCUNE elevation : `sandbox/` porte, lui, une ACE
explicite `LaForgeSandboxUsers:(OI)(CI)(M)`. Un arbre de travail git pose la
donne donc un depot COMPLET et inscriptible par le compte sandbox :

    git -C <racine> worktree add sandbox/mutation_wt HEAD --detach   # compte owner
    run action=run_job script=<racine>/sandbox/mutation_wt/tools/forge_mutation_ratchet.py

Le script mute alors `sandbox/mutation_wt/tools/...` : son `ROOT` est le
worktree, ses suites NR et son socle aussi. Le `tools/` reel n'est jamais
touche — plus sur que d'accorder l'ecriture a un compte qui a le reseau.
Rafraichir avant campagne (`git -C sandbox/mutation_wt checkout --detach HEAD`),
et `git worktree remove` quand c'est fini.
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

__FORGE_COLOR__ = "locomoteur/orchestr : cliquet de mutation sur les surfaces critiques"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCLE = os.path.join(ROOT, "tests", "nr", "mutation_socle.json")

# (module de production, sa suite NR, plafond de mutants). Les instruments
# anti-regression, sur leurs propres tests d'effet. On ne met PAS
# forge_mutation_test lui-meme (se muter soi-meme = recursion sans valeur).
# Le champ « suite » est passe tel quel a pytest (`tests.split()`) : une surface
# peut donc etre jugee sur PLUSIEURS fichiers. Mesure du 2026-08-18 : le module
# golden avait gagne deux familles de tests (apoptose, regles apprises) qui ne
# tournaient PAS ici — les mutants de ce code neuf survivaient tous, et le
# cliquet criait « nouvelle faiblesse » sur du code en realite couvert. Un
# cliquet qui juge sur une suite incomplete mesure le mauvais objet.
SURFACES = [
    ("tools/forge_golden_rules_ast.py",
     "tests/nr/test_golden_rules_ast_nr.py tests/nr/test_golden_rules_apoptose_nr.py "
     "tests/nr/test_golden_rules_apprises_nr.py", 14),
    ("tools/forge_dup_detector.py", "tests/nr/test_dup_detector_nr.py", 14),
    ("tools/forge_release_lock.py", "tests/nr/test_release_lock_provenance_nr.py", 14),
    ("tools/forge_bisect.py", "tests/nr/test_bisect_nr.py", 12),
    # B1 (2026-09-12). Premiere surface hors tools/ : le verrou de ressource est
    # le garde qui empeche deux agy en --dangerously-skip-permissions d'ecrire le
    # meme arbre. Un mutant qui survit ici, c'est une exclusion qui n'exclut pas.
    ("app/forge_lock_manager.py", "tests/nr/test_agy_lock_ressource_reelle_nr.py", 12),
    ("app/forge_intent_parser.py", "tests/nr/test_intent_multi_verbe_nr.py", 10),
    ("tools/forge_retrieval_sweep.py", "tests/nr/test_sweep_total_jamais_inconnu_nr.py", 8),
    # ⚠️ RETRAIT MESURE (2026-09-12) — `app/forge_tool_annotations.py` a ete
    # inscrit ici le matin meme, en SUPPOSANT que le mutateur atteindrait
    # `comportement_reel` et `declaration_dementie`. Mesure en worktree :
    # **12 mutants, 0 tue, tous sur les lignes 65-70** — c'est-a-dire les entrees
    # de `_TABLE`. Le mutateur prend les premiers sites du fichier, la table est
    # en tete, la logique n'a JAMAIS ete touchee. Sur cette surface le cliquet ne
    # mesurait que la stabilite d'une constante, et les mutants n'etaient tuables
    # que par un test qui recopie la table — tautologique.
    #
    # Une surface qui ne mord rien est le defaut meme que ce cliquet combat : on
    # la retire au lieu de geler un faux socle. `test_AF1_...` reste evidemment
    # dans `ci_local.PURE_TESTS` : il protege toujours, il n'est simplement pas
    # mutable utilement.
    #
    # Remplacante CHOISIE SUR MESURE, pas supposee (3 candidates confrontees) :
    #   forge_memory_gate      10 mutants, 8 tues, 80 % — survivants sur du CODE
    #   forge_router_replay    10 mutants, 8 tues, 80 % — candidate de reserve
    #   forge_retrieval_router 10 mutants, 7 tues, 70 % — candidate de reserve
    # `forge_memory_gate` l'emporte : c'est un GARDE (filtre qualite AVANT tout
    # INSERT en memoire), et V1 a mesure le jour meme qu'une panne de son capteur
    # OUVRAIT le portail. Un mutant qui survit ici, c'est un garde d'ingestion
    # dont un comportement cesse d'etre protege.
    ("tools/forge_memory_gate.py",
     "tests/nr/test_V1_confiance_etat_nomme_nr.py", 8),
]


def mesurer() -> dict:
    """{module|genre: nb_survivants} sur toutes les surfaces + meta par surface."""
    sys.path.insert(0, ROOT)
    from nokido_agent.tools import forge_mutation_test as M

    par_cle: dict[str, int] = {}
    surfaces_meta = []
    for module, test, cap in SURFACES:
        propre, motif = M._git_propre(module.replace("\\", "/"))
        if not propre:
            surfaces_meta.append({"module": module, "erreur": f"non propre : {motif}"})
            continue
        res = M.executer(module, test, cap)
        if res.get("erreur"):
            surfaces_meta.append({"module": module, "erreur": res["erreur"]})
            continue
        for s in res.get("survivants", []):
            cle = f"{module}|{s['genre']}"
            par_cle[cle] = par_cle.get(cle, 0) + 1
        surfaces_meta.append({"module": module, "mutants": res.get("mutants"),
                              "tues": res.get("tues"),
                              "survivants": len(res.get("survivants", [])),
                              "score": res.get("score")})
    return {"par_cle": par_cle, "surfaces": surfaces_meta}


def _verdict(courant: dict) -> tuple[int, dict]:
    try:
        with open(SOCLE, encoding="utf-8") as fh:
            gele = json.load(fh).get("par_cle", {})
    except (OSError, json.JSONDecodeError) as exc:
        return 3, {"etat": "INDETERMINE",
                   "raison": f"socle illisible ({exc}) — regenerer avec --ecrire-socle"}
    # Une surface qui n'a pas pu tourner (module non propre, suite deja rouge)
    # ne doit pas se lire comme « aucun survivant » : c'est INDETERMINE.
    en_echec = [s for s in courant["surfaces"] if s.get("erreur")]
    pc = courant["par_cle"]
    neuf = {k: v for k, v in pc.items() if v > gele.get(k, 0)}
    if neuf:
        return 1, {"etat": "REGRESSION", "nouveaux": neuf,
                   "surfaces": courant["surfaces"]}
    if en_echec:
        return 3, {"etat": "INDETERMINE",
                   "raison": "surface(s) non mesurable(s)", "echecs": en_echec}
    recul = sum(gele.values()) - sum(pc.values())
    return 0, {"etat": "CONFORME", "survivants_total": sum(pc.values()),
               "recul": recul, "surfaces": courant["surfaces"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Cliquet de mutation sur surfaces critiques")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ecrire-socle", action="store_true")
    ap.add_argument("--json", action="store_true")
    # UN VERDICT QUI NE VIT QUE SUR STDOUT EST PERDU. Mesure du 2026-09-10 : le
    # cliquet a tourne en job detache, et TOUS les fichiers du job (.log, .err,
    # .json, .rc) avaient disparu au moment de lire le resultat — 25 min de
    # mutation pour rien, et aucun moyen de distinguer « pas fini » de « mort ».
    # Le meme jour, 0 fichier `.rc` sur 14 jobs presents : ce canal ne peut pas
    # porter un verdict. Le rapport s'ECRIT donc a un chemin qu'on choisit.
    ap.add_argument("--sortie", metavar="FICHIER",
                    help="ecrit le rapport JSON (avec son code) a ce chemin absolu")
    a = ap.parse_args()

    courant = mesurer()

    if a.ecrire_socle:
        os.makedirs(os.path.dirname(SOCLE), exist_ok=True)
        with open(SOCLE, "w", encoding="utf-8") as fh:
            json.dump({"genere_par": "tools/forge_mutation_ratchet.py --ecrire-socle",
                       "par_cle": courant["par_cle"],
                       "surfaces": courant["surfaces"]},
                      fh, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"[mutation-ratchet] socle ecrit : {os.path.relpath(SOCLE, ROOT)} "
              f"({sum(courant['par_cle'].values())} survivants geles sur "
              f"{len(SURFACES)} surfaces)")
        return 0

    code, rapport = _verdict(courant)
    if a.sortie:
        cible = os.path.abspath(a.sortie)
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        with open(cible, "w", encoding="utf-8") as fh:
            json.dump({"code": code, **rapport}, fh, ensure_ascii=False, indent=2)
        print(f"[mutation-ratchet] verdict ecrit : {cible}")
    if a.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return code
    print(f"[mutation-ratchet] {rapport['etat']}")
    # Un INDETERMINE qui ne nomme ni la surface ni le motif n'est pas
    # exploitable : la CI affichait « surface(s) non mesurable(s) » et personne
    # ne pouvait savoir qu'il s'agissait d'un refus d'ACL (mesure 18/08).
    for s in rapport.get("echecs", []):
        print(f"   NON MESURE  {s['module']} — {s['erreur']}")
    for s in rapport.get("surfaces", []):
        if s.get("erreur"):
            print(f"   ERREUR  {s['module']} — {s['erreur']}")
        else:
            print(f"   {s['module']:<34} {s['tues']}/{s['mutants']} tues "
                  f"({s['survivants']} survivants, score {s['score']}%)")
    for k, v in rapport.get("nouveaux", {}).items():
        print(f"   + NOUVELLE FAIBLESSE  {k}  -> {v}")
    if rapport.get("raison"):
        print(f"   {rapport['raison']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
