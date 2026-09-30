#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_reachability_ledger.py — Phase 8 : registre d'ATTEIGNABILITE.

CE QU'IL AJOUTE
===============
Phases 6 et 7 disent ce qui a disparu et quand. Elles ne disent pas si ce qui RESTE
est encore atteignable. Or la mesure fondatrice du 2026-08-16 porte exactement la-
dessus : `forge_lmstudio.py`, `forge_litellm_router.py` et les 16 modules swarm sont
tous presents, aucun n'a jamais ete supprime, et pourtant 39 providers declares ne
donnent que 17 atteignables. Un fichier present ne prouve aucune capacite.

Ce registre repond, pour chaque constituant : **defini ? reference ? offert ?
prouve ?** — et en tire un etat unique.

=======
CE QUE CE REGISTRE NE VOIT PAS -- mesure du 2026-09-16, a lire AVANT d'agir sur
un verdict ORPHELIN
====================================================================
Il mesure le couplage STATIQUE : une definition, des references dans du code.
Or ce corps est massivement a couplage DYNAMIQUE. Un constituant peut donc etre
parfaitement vivant et sortir ORPHELIN parce qu'il est atteint par un chemin que
l'analyse de source ne traverse pas :

  - declare dans `proxy_deno/core/services.toml` (les services sont nommes la,
    pas importes) -- c'est le cas de `NokidoAnthropicIngress`, `NokidoCaddyTLS`,
    `NokidoGoDispatcher`, `NokidoWebEgress`, tous sortis ORPHELIN alors qu'ils
    sont des services declares ;
  - appele par dispatch MCP sur son NOM, par decorateur, ou par import paresseux
    (`_import_command_palette`, `_import_security`) ;
  - reference depuis une chaine de caracteres, un dictionnaire, un hook.

MESURE : sur 897 ORPHELIN du 2026-09-16, la ventilation par forme donne 782
snake_case, 49 CONSTANTES, 29 classes, 37 autres -- et les CONSTANTES incluent le
vocabulaire d'etats des instruments eux-memes (`GHOST_slot_sans_runtime`,
`CRED_INVALID_cle_absente`). Aucun de ces trois-la n'est du code mort.

CONSEQUENCE OPERATOIRE : ORPHELIN est un SIGNAL D'ALERTE, jamais un verdict de
suppression. Meme statut que `ZONE_MORTE` dans `forge_body_regulation_audit`, qui
n'autorise aucune suppression et se croise avec le log de l'organe. Avant d'agir
sur une ligne de cette liste, chercher le chemin DYNAMIQUE : TOML, dispatch par
nom, decorateur, chaine. C'est aussi, probablement, la raison pour laquelle ce
registre n'a jamais ete cable a un gate : ses verdicts bruts ne sont pas
actionnables tels quels.

ETATS
=====
=====
  PROVEN              vivant, et une PREUVE d'usage existe : soit un appel reussi
                      dans le socle de capacites, soit un test qui le cite
  OFFERT_NON_PROUVE   vivant et expose a la surface (tool/action), mais rien ne
                      demontre qu'il fonctionne
  UNPROVEN            vivant et reference ailleurs, sans preuve
  ORPHELIN            vivant, defini, et cite NULLE PART ailleurs -- le code existe,
                      aucun chemin ne le traverse. C'est le fossile type
  HISTORICALLY_PROVEN disparu, mais un test le citait : la capacite fut demontree
  LOST                disparu, jamais prouve
  UNKNOWN             non observable -- jamais confondu avec une absence

HIERARCHIE DE PREUVE
====================
Un appel REUSSI dans la trace vaut mieux qu'un test, qui vaut mieux qu'une
reference, qui vaut mieux qu'une definition. On ne descend d'un cran que faute du
precedent, et l'absence de test n'est JAMAIS lue comme une absence de capacite
(consigne owner) : c'est pourquoi UNPROVEN et LOST sont des etats distincts.

Usage :
    forge_reachability_ledger.py [--repos nom=chemin ...]
    forge_reachability_ledger.py --json --out sandbox/reachability.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nokido_agent.tools import forge_constituent_archaeology as A  # noqa: E402  (reutilisation Phase 6)

CONSTITUANTS = os.path.join(ROOT, "sandbox", "constituents.json")
SOCLE = os.path.join(ROOT, "tests", "nr", "capability_socle.json")

_IDENT = re.compile(r"[A-Za-z_]\w{2,}")
# Bruit vendor : identique a Phase 6, MAIS sans exclure les tests -- ici ils sont
# une SOURCE (ce sont eux qui prouvent), pas du bruit a ecarter.
_BRUIT_VENDOR = ("_attic", "backups", "node_modules", ".venv", "site-packages",
                 "RAG/", "RAG_plain_bak", "shadow_mutation", "docsets",
                 "eval_repos", "dist/", "build/", ".min.js")


def _log(m: str) -> None:
    print(f"[atteignabilite] {m}", flush=True)


def _vendor(chemin: str) -> bool:
    c = chemin.replace("\\", "/")
    return any(m in c for m in _BRUIT_VENDOR)


def _est_test(chemin: str) -> bool:
    c = chemin.replace("\\", "/").lower()
    base = c.rsplit("/", 1)[-1]
    return "/tests/" in c or "/test/" in c or base.startswith("test_") or base.endswith("_test.py")


def index_references(repo: str):
    """(refs_production, refs_tests) : combien de fois chaque identifiant apparait.

    On compte les OCCURRENCES, pas les definitions : un nom qui n'apparait qu'une
    seule fois dans tout le depot n'est cite que par sa propre definition -- donc
    plus rien ne l'atteint.
    """
    rc, out = A._git(repo, "ls-files", timeout=90)
    if rc != 0:
        return None, None
    prod, tests = Counter(), Counter()
    illisibles = 0
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel.endswith(A._EXT) or _vendor(rel):
            continue
        try:
            with open(os.path.join(repo, rel), encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            illisibles += 1
            continue
        cible = tests if _est_test(rel) else prod
        cible.update(_IDENT.findall(src))
    if illisibles:
        # Un fichier non lu retire SES references : les noms qu'il citait peuvent
        # alors paraitre ORPHELINS. On le dit, plutot que d'accuser du code sain.
        _log(f"  {os.path.basename(repo)} : {illisibles} fichier(s) illisible(s) — "
             f"des orphelins peuvent en decouler a tort")
    return prod, tests


def modules_presents(repo: str) -> set:
    """Les MODULES du depot : `app/x.py` definit le constituant `x`.

    Cette evidence manquait au ledger, qui ne recensait que les `def` et les
    `class`. AUCUN module n'etait donc jamais « defini » : tout module cite par un
    test ressortait « prouve jadis, plus atteignable ». Mesure 2026-08-29 — huit
    modules classes HISTORICALLY_PROVEN ou LOST existaient sur disque ET etaient
    importes : `forge_conv_sanitizer` par quinze fichiers dont le pare-feu
    semantique, `forge_services` (classe LOST) par `Nokido.py` lui-meme. Un
    inventaire qui declare perdu du code vivant ne se trompe pas seulement : il
    invite a le reecrire, c'est-a-dire exactement la regression qu'il doit eviter.
    """
    rc, out = A._git(repo, "ls-files", timeout=90)
    if rc != 0:
        return set()          # INDETERMINE : l'appelant garde ses disparus
    noms = set()
    for rel in out.splitlines():
        rel = rel.strip()
        if rel.endswith(".py") and not _vendor(rel):
            noms.add(os.path.basename(rel)[:-3])
    return noms


def _surface_offerte():
    """Noms offerts a la surface MCP : tools ET actions.

    Reutilise les sondes deja durcies du cliquet de capacites plutot que d'en
    refaire une : c'est la meme question, et une seconde implementation finirait
    par diverger de la premiere.
    """
    try:
        from nokido_agent.tools import forge_capability_ratchet as R  # noqa: PLC0415

        RM = R._rm()
        struct, exposed, actions, _ = R._surface(RM)
        if struct is None:
            return None
        return set(struct) | set(exposed) | set(actions)
    except Exception as e:  # noqa: BLE001
        _log(f"surface MCP non observable : {type(e).__name__}: {str(e)[:70]}")
        return None


def _prouves_par_usage():
    """Capacites dont un appel a REUSSI, d'apres le socle. La preuve la plus forte.

    Le socle indexe des TOOLS (`run`, `rag`...) ; le code, lui, porte des fonctions
    `handle_<tool>`. On produit donc les deux formes, ce qui referme le chainon
    capacite MCP <-> module qui manquait jusqu'ici.
    """
    try:
        with open(SOCLE, encoding="utf-8") as fh:
            caps = json.load(fh).get("capacites", {})
    except (OSError, json.JSONDecodeError) as e:
        _log(f"socle de capacites illisible ({type(e).__name__}) — preuve par usage indisponible")
        return set()
    noms = set()
    for v in caps.values():
        t = str(v.get("tool") or "")
        if t:
            noms.add(t)
            noms.add("handle_" + t)
    return noms


def classer_vivant(nom: str, usage: set, tests, surface, prod):
    """(etat, preuve) d'un constituant VIVANT, du plus fort au plus faible indice.

    On ne descend d'un cran que faute du precedent. L'absence de test n'est JAMAIS
    lue comme une absence de capacite (consigne owner) : c'est pourquoi UNPROVEN
    existe a cote d'ORPHELIN — le premier est atteignable sans preuve, le second
    n'est atteignable par rien.
    """
    if nom in usage:
        return "PROVEN", "appel reussi (socle)"
    n_tests = tests.get(nom, 0)
    if n_tests > 0:
        return "PROVEN", f"cite par {n_tests} occurrence(s) de test"
    if surface is not None and nom in surface:
        return "OFFERT_NON_PROUVE", "expose a la surface MCP"
    n_prod = prod.get(nom, 0)
    if n_prod > 1:
        return "UNPROVEN", f"{n_prod} references en production"
    return "ORPHELIN", "aucune reference hors sa definition"


def classer_disparu(nom: str, tests):
    """(etat, preuve) d'un constituant DISPARU.

    Un test qui le cite encore prouve que la capacite fut demontree — et signale au
    passage un test qui reference du vide.
    """
    n = tests.get(nom, 0)
    if n > 0:
        return "HISTORICALLY_PROVEN", f"{n} occurrence(s) de test le citent encore"
    return "LOST", "disparu, aucune preuve retrouvee"


def analyser(depots: dict) -> dict:
    presents = {n: p for n, p in depots.items() if A.est_depot(p)}
    absents = sorted(n for n in depots if n not in presents)
    if not presents:
        return {"observable": False, "raison": f"aucun depot lisible (absents: {absents})"}

    vivants, prod, tests = {}, Counter(), Counter()
    illisibles = []
    for n, p in presents.items():
        vivants[n] = A.noms_vivants(p)
        pr, te = index_references(p)
        if pr is None:
            illisibles.append(n)
            _log(f"  {n} : INDETERMINE (ls-files KO)")
            continue
        prod.update(pr)
        tests.update(te)
        _log(f"  {n} : {len(vivants[n])} definis, {len(pr)} identifiants en production, "
             f"{len(te)} en tests")

    surface = _surface_offerte()
    usage = _prouves_par_usage()
    _log(f"surface MCP : {len(surface) if surface is not None else 'INDETERMINE'} noms | "
         f"prouves par usage : {len(usage)}")

    # Disparus (Phase 6) : un test a-t-il deja demontre la capacite ?
    disparus = []
    try:
        with open(CONSTITUANTS, encoding="utf-8") as fh:
            disparus = [c for c in json.load(fh).get("constituants", [])
                        if c.get("etat") == "DISPARU"]
    except (OSError, json.JSONDecodeError):
        _log("Phase 6 absente — le volet DISPARUS sera vide, pas nul")

    fiches = []
    for n, noms in vivants.items():
        for nom in noms:
            etat, preuve = classer_vivant(nom, usage, tests, surface, prod)
            fiches.append({"nom": nom, "depot": n, "vivant": True,
                           "etat": etat, "preuve": preuve})

    # Un « disparu » de la Phase 6 a pu REVENIR depuis : restauration, ou renommage
    # LaForge -> Nokido. On le verifie avant de le declarer perdu, et on le DIT au
    # lieu de l'ecarter en silence — un volet disparus qui maigrit sans explication
    # se lit comme un progres.
    modules = set()
    for _n, _p in presents.items():
        modules |= modules_presents(_p)
    tous_vivants = set()
    for _noms in vivants.values():
        tous_vivants |= set(_noms or ())
    revenus = 0
    for c in disparus:
        nom = c.get("nom", "")
        if nom and (nom in modules or nom in tous_vivants):
            revenus += 1
            fiches.append({"nom": nom, "depot": c.get("depot"), "vivant": True,
                           "etat": "REVENU", "genre": c.get("genre"),
                           "fichier": c.get("fichier"),
                           "preuve": "declare DISPARU par la Phase 6, present aujourd'hui"})
            continue
        etat, preuve = classer_disparu(nom, tests)
        fiches.append({"nom": nom, "depot": c.get("depot"), "vivant": False,
                       "etat": etat, "preuve": preuve, "genre": c.get("genre"),
                       "fichier": c.get("fichier"), "date_suppr": c.get("date_suppr")})
    if revenus:
        _log(f"{revenus} constituant(s) declare(s) DISPARU sont REVENUS (presents sur "
             f"disque) — reclasses REVENU, jamais comptes comme perdus")

    resume = Counter(f["etat"] for f in fiches)
    return {"observable": True, "depots_analyses": sorted(presents),
            "depots_absents": absents, "depots_illisibles": illisibles,
            "surface_observable": surface is not None,
            "resume": dict(resume), "fiches": fiches}


def main() -> int:
    ap = argparse.ArgumentParser(description="Registre d'atteignabilite (Phase 8)")
    ap.add_argument("--repos", nargs="*", default=[])
    ap.add_argument("--out", default=os.path.join(ROOT, "sandbox", "reachability.json"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    depots = dict(A.DEPOTS_DEFAUT)
    for spec in a.repos:
        if "=" in spec:
            n, p = spec.split("=", 1)
            depots[n] = p

    res = analyser(depots)
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
    if not res["surface_observable"]:
        _log("  surface MCP NON OBSERVABLE -> aucun OFFERT_NON_PROUVE n'a pu etre etabli")
    orph = [f for f in res["fiches"] if f["etat"] == "ORPHELIN"]
    _log(f"top {a.top} ORPHELINS (code present, aucun chemin ne l'atteint) :")
    for f in sorted(orph, key=lambda x: x["nom"])[:a.top]:
        _log(f"  {f['nom']:<40} {f['depot']}")
    _log(f"ecrit : {os.path.relpath(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
