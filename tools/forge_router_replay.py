#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Replay des observations du routeur — rejoue la DECISION, jamais les signaux.

MANDAT OWNER 2026-09-01, phase 2. Le shadow accumule des observations pendant que le
guetteur attend la fenetre nominale. Ce script les rend REJOUABLES, pour qu'au moment ou
BGE-M3 repondra le materiel experimental soit deja pret au lieu d'etre bricole.

REGLE CARDINALE : le replay ne recalcule NI le lexical NI le vectoriel. Il reprend les
scores tels que le moteur les a produits et ne recalcule QUE la decision du routeur.
Recalculer les signaux hors du moteur creerait une SECONDE VERITE : le jour ou la
normalisation BM25, le repli FAISS ou le top-200 du sidecar changeraient, ce script
continuerait a produire des chiffres coherents entre eux et FAUX par rapport au moteur.

CE QU'IL NE FAIT PAS, et pourquoi :
  - il ne CALIBRE rien. Comparer deux ponderations ne dit pas laquelle est meilleure ;
    seule une baseline figee plus une verite terrain le diront ;
  - il ne presente AUCUNE difference de poids comme une amelioration. Une diff est une
    diff ;
  - il refuse de rejouer ce qui n'est pas une OBSERVATION_REELLE. Une fixture rejouee
    comme une mesure fabriquerait un verdict a partir d'un jeu de test.

Usage :
    LAFORGE_PYTHON tools/forge_router_replay.py            # replay + compteurs
    LAFORGE_PYTHON tools/forge_router_replay.py --diff 5   # + echantillon A/B
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/banc-de-mesure-routage"

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_retrieval_router import (  # noqa: E402
    OBSERVATION_REELLE, SCHEMA_OBSERVATION, decider,
)

JOURNAL = ROOT / "sandbox" / "router_observations.jsonl"
CHAMPS_REQUIS = ("query", "decision", "kind", "schema")


def _lire(chemin: Path):
    """Rend (lignes, illisibles). Une ligne illisible est COMPTEE, jamais ignoree."""
    lignes, illisibles = [], 0
    if not chemin.exists():
        return lignes, illisibles
    for brut in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        brut = brut.strip()
        if not brut:
            continue
        try:
            lignes.append(json.loads(brut))
        except ValueError:
            illisibles += 1
    return lignes, illisibles


# ── AH4 (2026-09-12) : MESURER L'ADAPTATION, PAS LA DERIVE ───────────────────
# `rejouer` compare la decision d'hier a celle d'aujourd'hui SUR LA MEME ENTREE :
# c'est une mesure de derive du code. Elle ne dit rien de ce qui arrive quand
# l'ENTREE change — c'est-a-dire de l'adaptation, qui est la question de AH4.
#
# CE QUE LA PREMIERE MESURE A TROUVE, et qui vaut plus que la fonction :
# `decider` EST adaptatif (canal vectoriel indisponible -> poids reporte au
# lexical, un REPORT et non une penalite) ... et `RAGEngine.search` l'appelle
# avec `{}`. La capacite existe, complete, et n'est sollicitee nulle part.
# Ce n'est pas un bug a corriger ici : le choix est documente dans `search`
# (la disponibilite n'est connue qu'APRES le classement, la faire peser sur les
# poids qui le PRODUISENT serait circulaire). Le role de cette fonction est de
# CHIFFRER l'ecart entre capacite et sollicitation, pas de trancher l'arbitrage.
_CHAMPS_POIDS = ("lexical_weight", "vector_weight", "structure_weight", "profil")


def mesurer_adaptation(observations=None, info: dict | None = None,
                       chemin: Path = JOURNAL, limite: int | None = None) -> dict:
    """Le systeme CHANGE-t-il d'avis quand une information arrive ?

    `info` est l'information injectee dans le contexte de disponibilite (par
    exemple `{"vector": "UNKNOWN"}`). Chaque requete est rejouee AVEC et SANS,
    et l'on compte les decisions qui bougent.

    ADAPTE / INERTE / NON_MESURABLE — et, distinct du verdict, l'ecart entre la
    CAPACITE d'adaptation (le code sait le faire) et sa SOLLICITATION REELLE
    (le chemin d'appel lui donne-t-il l'information ?). Un mecanisme present
    n'est pas un effet.
    """
    info = dict(info or {})
    if observations is None:
        observations, _ill = _lire(chemin)
        if limite:
            observations = observations[-limite:]

    retenues, ecartees_test, ecartees_forme = [], 0, 0
    for o in observations:
        if (o or {}).get("origine") == "test":
            ecartees_test += 1
            continue
        if not isinstance(o, dict) or "query" not in o or "decision" not in o:
            ecartees_forme += 1
            continue
        retenues.append(o)

    adaptees = inertes = avec_ctx = 0
    exemples = []
    for o in retenues:
        ctx = dict((o.get("decision") or {}).get("availability_context") or {})
        if ctx:
            avec_ctx += 1
        avant = decider(o["query"], ctx)
        apres = decider(o["query"], {**ctx, **info})
        ecart = {k: (getattr(avant, k), getattr(apres, k))
                 for k in _CHAMPS_POIDS
                 if getattr(avant, k) != getattr(apres, k)}
        if ecart:
            adaptees += 1
            if len(exemples) < 10:
                exemples.append({"query": o["query"][:90], "ecart": ecart})
        else:
            inertes += 1

    # La CAPACITE se lit sur une epreuve temoin, pas sur le corpus : un corpus
    # sans contexte ne peut pas prouver qu'un code ne sait pas s'adapter.
    _t = "une question ordinaire sur la memoire"
    capacite = "PRESENTE" if decider(_t, {}) != decider(_t, {"vector": "UNKNOWN"}) \
        else "ABSENTE"

    base = {
        "journal": str(chemin),
        "information_injectee": info,
        "observations_retenues": len(retenues),
        "observations_de_test_ecartees": ecartees_test,
        "observations_hors_forme": ecartees_forme,
        "observations_avec_contexte_de_disponibilite": avec_ctx,
        "capacite_d_adaptation": capacite,
        # Trois etats, pas deux. Mesure du 2026-09-12 : UNE observation sur dix
        # portait un contexte de disponibilite — un binaire aurait rendu
        # « OBSERVEE » et fait croire que le chemin reel alimente la decision.
        "sollicitation_reelle": ("JAMAIS" if not avec_ctx
                                 else "OBSERVEE" if avec_ctx * 2 >= len(retenues)
                                 else "MARGINALE"),
        "taux_sollicitation_pct": (round(100.0 * avec_ctx / len(retenues), 1)
                                   if retenues else None),
        "adaptees": adaptees, "inertes": inertes,
        "exemples": exemples,
        "note": ("CAPACITE et SOLLICITATION sont deux choses. `decider` sait reporter "
                 "le poids d'un canal indisponible ; si `availability_context` est "
                 "vide partout, c'est que personne ne le lui dit."),
    }
    if not retenues:
        base.update({"verdict": "NON_MESURABLE", "taux_adaptation_pct": None,
                     "raison": "aucune observation exploitable hors test"})
        return base
    base["taux_adaptation_pct"] = round(100.0 * adaptees / len(retenues), 1)
    base["verdict"] = "ADAPTE" if adaptees else "INERTE"
    return base


def rejouer(chemin: Path = JOURNAL, limite: int | None = None) -> dict:
    lignes, illisibles = _lire(chemin)
    if limite:
        lignes = lignes[-limite:]

    compte = {"lues": len(lignes), "illisibles": illisibles, "rejouees": 0,
              "identiques": 0, "divergentes": 0}
    ecartees: dict = {}
    divergences = []

    for ligne in lignes:
        manquants = [c for c in CHAMPS_REQUIS if c not in ligne]
        if manquants:
            ecartees["champs_manquants"] = ecartees.get("champs_manquants", 0) + 1
            continue
        if ligne["kind"] != OBSERVATION_REELLE:
            ecartees[f"kind={ligne['kind']}"] = ecartees.get(f"kind={ligne['kind']}", 0) + 1
            continue
        if ligne["schema"] != SCHEMA_OBSERVATION:
            ecartees[f"schema={ligne['schema']}"] = ecartees.get(f"schema={ligne['schema']}", 0) + 1
            continue

        avant = ligne["decision"]
        # SEULE la decision est recalculee, a partir des ENTREES enregistrees.
        apres = decider(ligne["query"], avant.get("availability_context") or {})
        compte["rejouees"] += 1

        ecart = {
            k: (avant.get(k), getattr(apres, k))
            for k in ("lexical_weight", "vector_weight", "structure_weight", "profil")
            if avant.get(k) != getattr(apres, k)
        }
        if ecart:
            compte["divergentes"] += 1
            if len(divergences) < 20:
                divergences.append({"query_id": ligne.get("query_id"),
                                    "query": ligne["query"][:90],
                                    "engine_commit": ligne.get("engine_commit"),
                                    "ecart": ecart,
                                    "raison_avant": avant.get("reason", "")[:110],
                                    "raison_apres": apres.reason[:110]})
        else:
            compte["identiques"] += 1

    return {
        "journal": str(chemin), "compte": compte, "ecartees": ecartees,
        "divergences": divergences,
        "note": ("Une DIVERGENCE signale que le routeur ne deciderait plus pareil sur la "
                 "meme entree -- c'est une derive a instruire, PAS une amelioration. "
                 "Aucune qualite n'est mesuree ici : il n'existe pas encore de baseline."),
    }


def diff_ab(chemin: Path = JOURNAL, n: int = 5) -> list:
    """Diff CURRENT_BASELINE vs ROUTER_SHADOW, sans jugement de valeur.

    Le rang vient du ranking REEL (celui qui a servi) ; le vecteur de poids vient du
    shadow, qui n'a rien applique. Mettre les deux cote a cote ne dit PAS lequel est
    meilleur -- cela dit seulement ou ils se seraient separes.
    """
    lignes, _ = _lire(chemin)
    out = []
    for ligne in [x for x in lignes if x.get("kind") == OBSERVATION_REELLE][-n:]:
        d = ligne.get("decision") or {}
        for r in (ligne.get("resultats") or [])[:3]:
            out.append({
                "query_id": ligne.get("query_id"),
                "candidate": r.get("chunk_id"),
                "CURRENT_BASELINE": {"rank": r.get("rank"), "final_score": r.get("final_score")},
                "ROUTER_SHADOW": {"lexical_w": d.get("lexical_weight"),
                                  "vector_w": d.get("vector_weight"),
                                  "structure_w": d.get("structure_weight"),
                                  "profil": d.get("profil")},
                "availability": r.get("availability"),
                "reason": (d.get("reason") or "")[:120],
            })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay des decisions du routeur shadow.")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--diff", type=int, default=0, help="echantillon A/B a afficher")
    # AH4 : une mesure qu'aucun point d'entree n'expose est une dette de cablage.
    ap.add_argument("--adaptation", metavar="CANAL=ETAT", default=None,
                    help="mesure l'ADAPTATION : rejoue chaque requete avec cette "
                         "information en plus (ex. vector=UNKNOWN)")
    args = ap.parse_args(argv)

    if args.adaptation:
        canal, _, etat = args.adaptation.partition("=")
        print(json.dumps(mesurer_adaptation(info={canal: etat or "UNKNOWN"},
                                            limite=args.limite),
                         ensure_ascii=False, indent=1))
        return 0

    res = rejouer(limite=args.limite)
    if args.diff:
        res["diff_ab"] = diff_ab(n=args.diff)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
