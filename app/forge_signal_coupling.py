#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Couplage EMETTEUR <-> CONSOMMATEUR : detecter les signaux orphelins.

Le corps produit des signaux orphelins DANS LES DEUX SENS, et chaque sens a coute
une panne mesuree le 2026-07-30 :

  consommateur SANS emetteur : `INSULIN_VECTORIZATION` etait declaree, avait un
      recepteur reel (le frein de batch de `forge_rag_warmup`, « > 0.4 -> batch / 2 »)
      et lisait 0.0 EN PERMANENCE. Le frein n'avait jamais freine. Meme forme pour
      `llama.wanted` : quatre lecteurs, un seul poseur sur six reveilleurs, d'ou
      73 arrets de llama-server:8091 et 312,94 Go recharges en 7,6 jours.
  emetteur SANS consommateur : les faits `self_care` du demon epistemique, ecrits en
      continu, lus par personne ; `orchestrator_recommendations`, 14 lignes d'avril,
      aucune appliquee, aucun lecteur.

COMPLEMENTAIRE de `forge_endocrine.orphans()`, pas un doublon : celui-la couvre UN
sens (hormone sans recepteur) et les hormones SEULES. On lui delegue cette moitie au
lieu de la re-deriver, et on lui emprunte son bon motif -- `assumed` distingue
l'absence MOTIVEE de l'angle mort, une absence justifiee n'est pas un defaut.

## Pourquoi l'ECRITURE est instrumentee, et pas inferee du code

L'analyse statique NE SUFFIT PAS, c'est mesure : un grep sur `llama.wanted` a rendu
14 lectures et 0 ecriture, et c'etait FAUX -- l'ecriture passait par
`CIBLES[cible]["drapeau"]`, une clef de configuration invisible au litteral. Revue AGY
du 2026-07-30 : « l'audit AST atteint ses limites des qu'il y a indirection dynamique
(`CIBLES[x]["drapeau"]`, `getattr()`, json persistant ou IPC) ». Un emetteur se
CONSTATE donc a l'execution. Le cout est negligeable devant un faux orphelin : les
emissions sont rares (un drapeau au reveil, une hormone par minute), ce n'est pas un
chemin chaud.

## La POLICY, et pourquoi elle interdit la neutralisation automatique

AGY proposait de neutraliser automatiquement un signal orphelin « pour eviter
l'inhibition aveugle ». Refute en partie, et il en est convenu : cela vaut pour un
signal dont l'ABSENCE BLOQUE -- le cortisol qui opposait un veto au spawn, le
neutraliser libere. Cela ne vaut PAS pour un signal dont l'absence PERMET :
`llama.wanted` sans emetteur, le neutraliser aurait SUPPRIME la protection au lieu
d'ajouter l'emetteur manquant, et le corps aurait continue a recharger 5 Go en boucle
en croyant s'etre soigne.

Chaque signal porte donc sa `policy`, et l'equivalence biologique est celle qu'AGY a
nommee :

  fail_closed : l'absence du signal BLOQUE l'action. Inhibition tonique GABAergique
      (striatum -> globus pallidus) : le frein court par defaut, lever l'inhibition
      debloque. Remede d'un orphelin : desarmer le frein.
  fail_open   : l'absence du signal AUTORISE l'action. Facteur trophique facon NGF :
      sans lui la cellule entre normalement en apoptose. Remede d'un orphelin :
      AJOUTER l'emetteur, jamais retirer le garde.

Ce module ne neutralise RIEN. Il NOMME, avec le sens de l'echec. Corriger un couplage
est une decision, pas un reflexe.

Usage :
    LAFORGE_PYTHON -c "from forge_signal_coupling import emit_signal; emit_signal('llama.wanted')"
    LAFORGE_PYTHON app/forge_signal_coupling.py            # verdicts
    LAFORGE_PYTHON app/forge_signal_coupling.py --json
"""

from __future__ import annotations

__FORGE_COLOR__ = "sn-vegetatif/couplage-signaux"

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

DB = ROOT / "sandbox" / "signal_emissions.db"

# Fenetre au-dela de laquelle une emission ne compte plus comme « vivante ».
# 24 h : assez long pour couvrir un signal rare (un reveil par jour), assez court
# pour qu'un emetteur mort se voie avant qu'on ait oublie pourquoi il existait.
VIVANT_S = 86400.0

FAIL_CLOSED = "fail_closed"   # absence => BLOQUE l'action ; remede = desarmer le frein
FAIL_OPEN = "fail_open"       # absence => AUTORISE l'action ; remede = AJOUTER l'emetteur

# TROPHISME — SEUIL DE HILL, pas une exponentielle. Correction apportee par la revue
# AGY du 2026-07-30 (tour 3, T3.2), et je l'avais soumise precisement pour savoir si ma
# courbe avait un referent : elle n'en avait pas. Le NGF n'agit PAS en gradient continu,
# il agit par SEUIL DE SURVIE TRANSCRIPTIONNEL, loi du tout-ou-rien au recepteur
# TrkA/p75NTR. Un `exp(-age/tau)` « maintient des branches zombies artificiellement en
# vie » : il n'y a jamais de moment ou le capteur dit franchement que la voie est morte.
#
# Hill : troph = 1 / (1 + (age / SEUIL)^n). A l'age du seuil il vaut 0.5, a la moitie
# du seuil 0.94, au double 0.06 -- la transition est RAIDE, donc lisible.
TROPHISME_SEUIL_S = 21600.0   # 6 h : age auquel la voie est a mi-survie
TROPHISME_HILL_N = 4          # n >= 3 exige par la revue ; 4 donne une marche nette
# HYSTERESIS : la voie est declaree degenerescente sous ce trophisme, et n'en sort que
# par une EMISSION NEUVE — laquelle remet l'age a zero, donc le trophisme a 1.0. Le
# systeme ne peut pas osciller autour du seuil, ce qui est tout l'objet de l'hysteresis.
TROPHISME_PLANCHER = 0.25

# Catalogue des signaux SURVEILLES. Seed = ceux dont la panne a ete mesuree le
# 2026-07-30. `consumers` liste les modules qui LISENT (constate par lecture du code,
# c'est fiable dans ce sens : un lecteur ne s'indirecte pas, il appelle).
SIGNAUX: dict[str, dict] = {
    "INSULIN_VECTORIZATION": {
        "kind": "hormone",
        "policy": FAIL_OPEN,
        "consumers": ["app/forge_rag_warmup.py"],
        "note": "frein de batch RAG > 0.4 ; a lu 0.0 en permanence jusqu'au 30/07",
    },
    "llama.wanted": {
        "kind": "flag",
        "policy": FAIL_OPEN,
        "consumers": ["app/forge_resource_manager.py", "tools/forge_llama_keeper.py",
                      "app/forge_health_diagnostic.py"],
        "note": "intention de charge ; 6 reveilleurs, 1 poseur -> 312,94 Go recharges",
    },
    "docker.wanted": {
        "kind": "flag",
        "policy": FAIL_OPEN,
        "consumers": ["app/forge_resource_manager.py"],
        "note": "le seul qui marchait : UN chemin canonique qui declare",
    },
    "rerank.wanted": {
        "kind": "flag",
        "policy": FAIL_OPEN,
        "consumers": ["app/forge_resource_manager.py"],
        "note": "meme famille que llama.wanted (reranker :8100, 6,57 Go)",
    },
    "lmstudio.wanted": {
        "kind": "flag",
        "policy": FAIL_OPEN,
        "consumers": ["app/forge_resource_manager.py"],
    },
    "snn.wanted": {
        "kind": "flag",
        "policy": FAIL_CLOSED,
        "consumers": ["app/forge_resource_manager.py"],
        "note": "arme le capteur SNN des vitals (Phase 39, ecrit le 2026-05-25 et "
                "JAMAIS execute : il dependait de FORGE_SNN_ENABLED, variable posee "
                "nulle part). FAIL_CLOSED parce que l'absence doit rester l'etat sur "
                "par defaut : un capteur qui s'arme tout seul est pire qu'un capteur "
                "eteint. Retirer le fichier suffit a desarmer, sans restart.",
    },
    "CORTISOL_FRUSTRATION": {
        "kind": "hormone",
        "policy": FAIL_CLOSED,
        "consumers": ["app/forge_resource_manager.py", "tools/forge_organ_pulse.py"],
        "note": "absence = plus de durcissement des seuils ; 3 paralysies iatrogenes le 29/07",
    },
    "self_care": {
        "kind": "fact",
        "policy": FAIL_OPEN,
        "consumers": ["app/forge_autonomous_loops.py"],
        "note": "1 ecrivain 0 lecteur jusqu'au 30/07 ; consomme par pat_self_improvement",
    },
    "orchestrator_recommendations": {
        "kind": "table",
        "policy": FAIL_OPEN,
        "consumers": [],
        "note": "AUCUN applicateur : 17 propositions, 0 appliquee. Orphelin ASSUME, "
                "appliquer est une decision owner (applicateur deux etages a venir)",
    },
}

# Absences MOTIVEES : un orphelin justifie n'est pas un defaut (motif emprunte a
# `forge_endocrine.NO_RECEPTOR_REASON`). Sans cette table, le capteur crie sur des
# choix deliberes, se fait desarmer, et ne sert plus a rien.
ORPHELIN_ASSUME = {
    "orchestrator_recommendations": "applicateur volontairement absent : appliquer "
                                    "une proposition mute le corps, ca se demande",
}


def _conn() -> sqlite3.Connection:
    """Base DEDIEE, autocommit + WAL. Volontairement PAS la base RAG.

    Y ecrire par `forge_db_path.open_writer()` ferait passer chaque emission par le
    verrou de la base partagee, pour une donnee qui n'interesse que ce module. On
    reprend en revanche ses trois reglages, qui sont ce qui evite la contention :
    autocommit (`isolation_level=None`), WAL, et un `busy_timeout` non nul.
    """
    DB.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(DB), timeout=5.0, isolation_level=None)
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("PRAGMA busy_timeout=5000")
    cx.execute(
        "CREATE TABLE IF NOT EXISTS emissions ("
        " signal TEXT NOT NULL,"
        " emitter TEXT NOT NULL,"
        " n INTEGER NOT NULL DEFAULT 0,"
        " last_ts REAL,"
        " PRIMARY KEY (signal, emitter))"
    )
    cx.execute(
        "CREATE TABLE IF NOT EXISTS lectures ("
        " signal TEXT NOT NULL,"
        " consumer TEXT NOT NULL,"
        " n INTEGER NOT NULL DEFAULT 0,"
        " last_ts REAL,"
        " PRIMARY KEY (signal, consumer))"
    )
    cx.execute(
        "CREATE TABLE IF NOT EXISTS transductions ("
        " signal TEXT NOT NULL,"
        " consumer TEXT NOT NULL,"
        " n INTEGER NOT NULL DEFAULT 0,"
        " last_ts REAL,"
        " PRIMARY KEY (signal, consumer))"
    )
    return cx


def emit_signal(signal: str, emitter: str | None = None) -> bool:
    """CONSTATE une emission. A appeler la ou le signal est REELLEMENT ecrit.

    `emitter` par defaut = le module appelant, deduit de la pile : on veut savoir QUI
    emet, pas seulement que quelqu'un emet -- c'est la difference entre « ce signal a
    un emetteur » et « ces cinq reveilleurs sur six ne declarent pas ».

    Fail-safe : rend False et ne leve JAMAIS. Un capteur de couplage qui casse
    l'emission qu'il observe serait pire que le defaut qu'il cherche.
    """
    if not emitter:
        try:
            f = sys._getframe(1)
            emitter = "%s:%s" % (os.path.basename(f.f_code.co_filename), f.f_code.co_name)
        except Exception:
            emitter = "inconnu"
    try:
        with _conn() as cx:
            cx.execute(
                "INSERT INTO emissions (signal, emitter, n, last_ts) VALUES (?,?,1,?) "
                "ON CONFLICT(signal, emitter) DO UPDATE SET n = n + 1, last_ts = ?",
                (str(signal), str(emitter), time.time(), time.time()),
            )
        return True
    except Exception:
        return False  # muet-ok : l'instrumentation ne doit jamais casser l'emetteur


def emetteurs(signal: str) -> list[dict]:
    """Qui a emis ce signal, et quand. Liste VIDE = aucun emetteur CONSTATE."""
    try:
        with _conn() as cx:
            rows = cx.execute(
                "SELECT emitter, n, last_ts FROM emissions WHERE signal=? ORDER BY last_ts DESC",
                (str(signal),),
            ).fetchall()
    except Exception as exc:
        print("[couplage] emissions ILLISIBLES (%s)" % type(exc).__name__, file=sys.stderr)
        return []
    now = time.time()
    out = []
    for r in rows:
        age = now - (r[2] or 0)
        out.append({"emetteur": r[0], "n": r[1], "age_s": round(age, 1),
                    "vivant": age < VIVANT_S,
                    "trophisme": round(_trophisme(age), 3)})
    return out


def _trophisme(age_s: float) -> float:
    """Survie de la voie : SEUIL de Hill, pas une decroissance douce.

    `1 / (1 + (age / SEUIL)^n)`. Le choix du seuil raide sur l'exponentielle est une
    correction de la revue AGY : le facteur trophique biologique est tout-ou-rien, et
    une courbe douce laisse vivre des branches zombies qu'aucun verdict ne tranche.
    """
    if age_s <= 0:
        return 1.0
    return 1.0 / (1.0 + (float(age_s) / TROPHISME_SEUIL_S) ** TROPHISME_HILL_N)


def transduce_signal(signal: str, consumer: str | None = None) -> bool:
    """CONSTATE une TRANSDUCTION : le consommateur a REELLEMENT change de comportement.

    Distinction apportee par la revue AGY (tour 3, T3.4), et elle repond au defaut
    central de la journee. En biologie un RECEPTEUR LEURRE (OPG, ACKR3) fixe le ligand
    mais n'a pas de domaine de signalisation intracellulaire : il consomme sans
    transduire. Le frein de batch de `forge_rag_warmup` etait exactement ca -- il
    LISAIT `INSULIN_VECTORIZATION` depuis des mois et n'a jamais freine, parce que la
    valeur lue etait toujours 0.0. Un capteur qui compte les LECTURES l'aurait declare
    couple.

    On n'appelle donc pas ceci a la lecture, mais LA OU LA BRANCHE AGIT : batch divise,
    delai pose, allocation refusee, signal fille emis. Lectures > 0 et transductions
    = 0 => statut DECOY.
    """
    if not consumer:
        try:
            f = sys._getframe(1)
            consumer = "%s:%s" % (os.path.basename(f.f_code.co_filename), f.f_code.co_name)
        except Exception:
            consumer = "inconnu"
    try:
        with _conn() as cx:
            cx.execute(
                "INSERT INTO transductions (signal, consumer, n, last_ts) VALUES (?,?,1,?) "
                "ON CONFLICT(signal, consumer) DO UPDATE SET n = n + 1, last_ts = ?",
                (str(signal), str(consumer), time.time(), time.time()),
            )
        return True
    except Exception:
        return False  # muet-ok : l'observabilite ne casse jamais l'effet qu'elle observe


def observe_signal(signal: str, consumer: str | None = None) -> bool:
    """CONSTATE une LECTURE : le consommateur a consulte le signal.

    Indispensable pour ne pas crier au recepteur leurre a tort. Le verdict DECOY exige
    `lectures > 0 ET transductions == 0` (formulation exacte de la revue AGY) : compter
    les EMISSIONS a la place des lectures fabrique un faux positif immediat, mesure des
    la premiere execution -- un consommateur qui n'a simplement PAS ENCORE TOURNE n'est
    pas un leurre, et un garde qui crie a faux se fait desarmer.
    """
    if not consumer:
        try:
            f = sys._getframe(1)
            consumer = "%s:%s" % (os.path.basename(f.f_code.co_filename), f.f_code.co_name)
        except Exception:
            consumer = "inconnu"
    try:
        with _conn() as cx:
            cx.execute(
                "INSERT INTO lectures (signal, consumer, n, last_ts) VALUES (?,?,1,?) "
                "ON CONFLICT(signal, consumer) DO UPDATE SET n = n + 1, last_ts = ?",
                (str(signal), str(consumer), time.time(), time.time()),
            )
        return True
    except Exception:
        return False  # muet-ok : l'observabilite ne casse jamais la lecture qu'elle observe


def lectures(signal: str) -> list[dict]:
    """Qui a CONSULTE ce signal. Vide = personne ne l'a lu, ou personne n'est instrumente."""
    try:
        with _conn() as cx:
            rows = cx.execute(
                "SELECT consumer, n, last_ts FROM lectures WHERE signal=? "
                "ORDER BY last_ts DESC", (str(signal),)).fetchall()
    except Exception:
        return []
    now = time.time()
    return [{"consommateur": r[0], "n": r[1], "age_s": round(now - (r[2] or 0), 1)}
            for r in rows]


def transductions(signal: str) -> list[dict]:
    """Qui a REELLEMENT agi sur ce signal. Vide = aucune transduction constatee."""
    try:
        with _conn() as cx:
            rows = cx.execute(
                "SELECT consumer, n, last_ts FROM transductions WHERE signal=? "
                "ORDER BY last_ts DESC", (str(signal),)).fetchall()
    except Exception:
        return []
    now = time.time()
    return [{"consommateur": r[0], "n": r[1], "age_s": round(now - (r[2] or 0), 1),
             "trophisme": round(_trophisme(now - (r[2] or 0)), 3)} for r in rows]


def _hormone_lue(nom: str):
    """Valeur courante d'une hormone. None = illisible, PAS zero."""
    try:
        from nokido_agent.app.forge_endocrine import read as _read
        return _read(nom)
    except Exception:
        return None


def _flag_pose(nom: str):
    """Le drapeau existe-t-il ? None si le chemin est illisible (compte sandbox)."""
    try:
        p = ROOT / "sandbox" / nom
        return p.exists()
    except OSError:
        return None  # muet-ok : trois etats, un acces refuse n'est pas une absence


def couplage() -> list[dict]:
    """Verdict par signal. NE NEUTRALISE RIEN : nomme, avec le SENS de l'echec."""
    out = []
    for nom, spec in SIGNAUX.items():
        ems = emetteurs(nom)
        vivants = [e for e in ems if e["vivant"]]
        cons = list(spec.get("consumers") or [])

        # Etat observe cote signal, quand il est observable sans instrumentation.
        observe = None
        if spec["kind"] == "hormone":
            observe = _hormone_lue(nom)
        elif spec["kind"] == "flag":
            observe = _flag_pose(nom)

        assume = nom in ORPHELIN_ASSUME
        if not cons:
            verdict = "ORPHELIN_CONSOMMATEUR"
        elif not vivants:
            # Nuance qui evite un faux positif franc : sans instrumentation posee, on
            # ne sait pas s'il n'y a pas d'emetteur ou si personne ne l'a instrumente.
            verdict = "SANS_MESURE" if not ems else "ORPHELIN_EMETTEUR"
        else:
            verdict = "COUPLE"

        remede = None
        if verdict == "ORPHELIN_EMETTEUR":
            remede = ("AJOUTER l'emetteur -- ne PAS retirer le garde (fail_open)"
                      if spec["policy"] == FAIL_OPEN
                      else "DESARMER le frein -- son absence bloque (fail_closed)")
        elif verdict == "ORPHELIN_CONSOMMATEUR":
            remede = "brancher un consommateur, ou assumer l'orphelin en le declarant"
        elif verdict == "DECOY_LECTEUR_PASSIF":
            remede = ("le consommateur LIT sans AGIR (recepteur leurre) : instrumenter "
                      "sa branche par transduce_signal, ou constater qu'elle est morte")

        # Trophisme de la voie = celui de son emetteur le PLUS FRAIS. Une voie tenue
        # par un seul emetteur actif est vivante, meme si dix autres ont cesse.
        troph = max((e["trophisme"] for e in ems), default=0.0)
        degen = bool(ems) and troph < TROPHISME_PLANCHER
        if degen and not remede:
            remede = (
                "voie en DEGENERESCENCE (trophisme %.3f) : raviver l'emetteur, "
                "son absence AUTORISE l'action" % troph
                if spec["policy"] == FAIL_OPEN else
                "voie en DEGENERESCENCE (trophisme %.3f) : verifier que ce frein "
                "est encore voulu" % troph
            )

        # RECEPTEUR LEURRE : des consommateurs declares, des emissions constatees, et
        # AUCUNE transduction. C'est le defaut le plus couteux car il se lit comme un
        # couplage sain. On ne le declare que si le signal a REELLEMENT ete emis :
        # sans emission, ne pas transduire est le comportement correct.
        # Trois etats sur la transduction, jamais deux. Le verdict DECOY exige des
        # LECTURES constatees : sans elles, l'absence de transduction ne distingue pas
        # « lit sans agir » (leurre reel) de « n'a pas encore tourne » (rien a dire).
        lus = lectures(nom)
        trans = transductions(nom)
        if trans:
            verdict_trans = "TRANSDUIT"
        elif lus:
            verdict = "DECOY_LECTEUR_PASSIF"
            verdict_trans = "LU SANS EFFET"
            # Remede reattribue ICI : la chaine de remedes s'execute AVANT que ce
            # verdict existe, donc un DECOY en sortait sans remede — mesure, et corrige
            # dans le tour meme, parce qu'un capteur qui designe un defaut sans dire
            # quoi faire se fait ignorer aussi surement qu'un capteur muet.
            remede = ("le consommateur LIT sans AGIR (recepteur leurre facon OPG/ACKR3) : "
                      "instrumenter sa branche d'effet, ou constater qu'elle est morte")
        else:
            verdict_trans = "SANS_MESURE"

        out.append({
            "transduction": verdict_trans,
            "transducteurs": len(trans), "lecteurs_constates": len(lus),
            "signal": nom, "kind": spec["kind"], "policy": spec["policy"],
            "verdict": verdict, "assume": assume,
            "trophisme": round(troph, 3), "degenerescence": degen,
            "raison_assume": ORPHELIN_ASSUME.get(nom),
            "emetteurs_vivants": len(vivants), "emetteurs_connus": len(ems),
            "consommateurs": len(cons), "observe": observe,
            "remede": remede, "note": spec.get("note"),
            "detail_emetteurs": ems[:4],
        })
    ordre = {"DECOY_LECTEUR_PASSIF": 0, "ORPHELIN_EMETTEUR": 1,
             "ORPHELIN_CONSOMMATEUR": 2, "SANS_MESURE": 3, "COUPLE": 4}
    return sorted(out, key=lambda d: (d["assume"], ordre.get(d["verdict"], 9), d["signal"]))


def findings() -> list[dict]:
    """Les seuls verdicts ACTIONNABLES, orphelins assumes exclus.

    Mesure 2026-08-02 : ce filtre ne gardait que les verdicts `ORPHELIN*`. Or quand le
    capteur n'a AUCUNE observation, tous les signaux sortent en `SANS_MESURE` -> la
    liste revenait VIDE, c'est-a-dire « aucun probleme », pour un capteur qui n'avait
    rien mesure du tout. Le garde ecrit pour traquer les signaux sans emetteur etait
    lui-meme sans emetteur, et il le disait en silence.

    Un capteur muet doit le CRIER : trois etats, jamais deux. Si rien n'a ete observe,
    on rend un finding explicite au lieu du vide rassurant.
    """
    tous = couplage()
    # DECOY et DEGENERESCENCE remontent ICI, au meme titre que les orphelins.
    # Mesure 2026-08-03 : le corps portait TROIS recepteurs leurres
    # (docker.wanted, lmstudio.wanted, rerank.wanted) et une voie `llama.wanted`
    # a trophisme 0,01, et cette liste sortait VIDE parce que le filtre ne gardait
    # que les verdicts ORPHELIN*. Or `couplage()` dit elle-meme du DECOY qu'il est
    # « le defaut le plus couteux car il se lit comme un couplage sain » : le
    # detecter sans le remonter revient exactement a ne pas le detecter -- c'est
    # le meme defaut que celui corrige le 02/08 pour SANS_MESURE, sur un autre
    # verdict.
    reels = [d for d in tous
             if (d["verdict"].startswith("ORPHELIN")
                 or d["verdict"] == "DECOY_LECTEUR_PASSIF"
                 or d.get("degenerescence"))
             and not d["assume"]]
    mesures = [d for d in tous
               if d.get("emetteurs_connus") or d.get("lecteurs_constates")]
    if tous and not mesures:
        reels.insert(0, {
            "signal": "(tous)",
            "verdict": "SANS_MESURE_TOTALE",
            "raison": "aucune emission ni lecture constatee sur %d signaux : le capteur "
                      "n'a PAS d'observation, ce n'est pas « aucun probleme »" % len(tous),
            "remede": "appeler emit_signal() au point qui POSE le signal et "
                      "observe_signal() au point qui le LIT ; sans ces deux appels "
                      "le couplage est invisible",
            "assume": False,
        })
    return reels


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Signaux orphelins : emetteur <-> consommateur.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--emit", help="constater une emission (usage manuel/test)")
    args = ap.parse_args(argv)

    if args.emit:
        print("emission constatee :", emit_signal(args.emit, emitter="cli"))
        return 0

    res = couplage()
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print("COUPLAGE DES SIGNAUX — un signal orphelin est une panne silencieuse")
    print("=" * 96)
    print("%-28s %-8s %-21s %4s %4s %6s %s"
          % ("signal", "policy", "verdict", "em", "cons", "troph", "observe"))
    print("-" * 96)
    for d in res:
        marque = " (assume)" if d["assume"] else ""
        if d.get("degenerescence"):
            marque += " DEGENERESCENCE"
        print("%-28s %-8s %-21s %4d %4d %6.2f %s%s"
              % (d["signal"][:28], d["policy"].replace("fail_", ""),
                 d["verdict"], d["emetteurs_vivants"], d["consommateurs"],
                 d.get("trophisme") or 0.0, d["observe"], marque))
    deg = [d for d in res if d.get("degenerescence")]
    if deg:
        print("\nVOIES EN DEGENERESCENCE (%d) — emises jadis, plus stimulees. "
              "MARQUEES, jamais coupees :" % len(deg))
        for d in deg:
            print("     %-28s trophisme %.3f — %s" % (d["signal"][:28], d["trophisme"],
                  "ajouter/raviver l'emetteur" if d["policy"] == FAIL_OPEN
                  else "verifier que le frein est encore voulu"))
    act = findings()
    if act:
        print("\nA TRAITER (%d) :" % len(act))
        for d in act:
            print("  ! %-28s %s" % (d["signal"][:28], d["remede"]))
            if d.get("note"):
                print("      %s" % d["note"])
    sm = [d for d in res if d["verdict"] == "SANS_MESURE"]
    if sm:
        print("\n%d signal(aux) SANS MESURE — emission jamais instrumentee. Ce n'est PAS "
              "« pas d'emetteur », c'est « je ne peux pas voir »." % len(sm))
        for d in sm:
            print("     %s" % d["signal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
