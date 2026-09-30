# -*- coding: utf-8 -*-
"""A0-3 — chaine de preuve des ONZE entrees de `arbitrer_pression`.

POURQUOI CET OUTIL EXISTE
=========================
Owner, 2026-09-05 : « une fois le `coder_up` fiable, il faudra verifier que TOUTES
les entrees de decision ont une chaine de preuve complete », avec pour chacune
`source -> fraicheur -> semantique -> consommation par l'arbitre`.

Ce n'est pas une precaution abstraite. Deux entrees ont deja menti, chacune avec un
effet different, et aucune ne se voyait :

- `inutile_s` : le lecteur faisait `float(ts)` sur une date ISO, `ValueError` avalee,
  `None` rendu — l'arbitre lisait « inactivite INCONNUE » et s'abstenait A CHAQUE
  TICK, indefiniment. `llama-server` (4,8 Go) n'etait jamais evince.
- `coder_up` : la sonde passait par PowerShell, indisponible depuis le compte du hub
  (`rc=-1`), et tombait donc toujours sur son defaut — indistinguable d'un coder mort.

Le point commun : **une entree fausse ne se signale pas**. Elle produit une decision
plausible, motivee, journalisee — et fausse. D'ou cet audit, qui interroge chaque
source REELLEMENT et rend ce qu'elle vaut, y compris son cout en millisecondes : une
sonde lente sur un chemin appele a chaque tick est un probleme en soi.

CE QU'IL NE FAIT PAS
====================
Il ne juge pas la DECISION, seulement la qualite de ses ENTREES. Tant que celle-ci
n'est pas demontree, mesurer `rules_v1` comme ligne de base reviendrait a mesurer un
defaut et a l'appeler politique.
"""
from __future__ import annotations

__FORGE_COLOR__ = "regulation/audit-entrees-arbitre"

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MESUREE, DERIVEE, INCONNUE, ILLISIBLE = "MESUREE", "DERIVEE", "INCONNUE", "ILLISIBLE"

# Semantique et consommation, ecrites une fois pour toutes : c'est la moitie de
# l'audit. Une valeur juste consommee de travers reste un defaut.
CONTRAT = {
    "rhythm": ("forge_endocrine_system.get_rhythm",
               "etat endocrinien global", "MODULE la tolerance (grace), ne decide pas"),
    "coder_up": ("llamacpp_native_status.verdict",
                 "le coder SERT-il (port+process)", "autorise la branche yield_coder"),
    "coder_conns": ("_coder_conns", "connexions actives ; <0 = mesure absente",
                    "!=0 protege (y compris <0, prudence)"),
    "chains_active": ("get_active_intents", "chaines de veille en cours",
                      ">0 protege"),
    "embed_wanted": ("get_active_intents", "l'embedder est reclame",
                     "compose embed_affame"),
    "backlog": ("_backlog_pending_qualifie", "chunks PENDING qualifies",
                "compose embed_affame ; fait CEDER le coder"),
    "embedder_up": ("_port_ecoute(8099)", "l'embedder ecoute",
                    "compose embed_affame (nie si up)"),
    "coder_ram_gb": ("llamacpp_native_status.ram_gb", "RSS du coder",
                     "gain annonce de l'eviction"),
    "free_gb": ("_free_now", "RAM libre LIVE (jamais l'instantane publie)",
                "compare au seuil de confort"),
    "demande_active": ("_demande_active_llama", "une demande ouverte existe",
                       "None => protege (prudence)"),
    "inutile_s": ("_inutile_s_llama", "duree CONTINUE a zero connexion",
                  "None => protege ; >= grace => evincable"),
}

# A0-3c (2026-09-05) — MESUREES mais PAS ENCORE CONSOMMEES par `arbitrer_pression`.
#
# Table SEPAREE, et c'est le fond du sujet. Mon premier jet les avait mises dans
# `CONTRAT` : le garde d'egalite stricte de `test_arbitre_entrees_audit_nr` a refuse,
# et il avait raison. `CONTRAT` decrit ce qui ENTRE dans la decision ; y ranger une
# grandeur que la fonction ne recoit pas aurait fait lire au rapport « couverture
# complete des entrees » en comptant une grandeur qui n'entre nulle part -- le
# meme faux calme qu'un garde branche sur un signal sans emetteur.
#
# L'arbitre ne connaissait QUE la RAM. L'owner a mesure « ram 86 % et nvme 100 % » :
# deux symptomes qu'aucune entree ne reliait, alors qu'une machine qui pagine ecrit
# sur le disque. On expose donc la mesure MAINTENANT et on decide de la politique
# en A0-4, sur observation. Poser un seuil ici serait inventer une regle avant
# d'avoir regarde.
CONTRAT_OBSERVE = {
    "disque_occupation_pct": ("forge_vitals_channels.grp_disque",
                              "% temps disque (PDH PhysicalDisk _Total, peut depasser 100)",
                              "AUCUNE consommation a ce jour -- exposee pour A0-4"),
}


def _classer(nom: str, valeur, err: str) -> tuple:
    """Rend (etat, remarque). Une valeur presente ne suffit pas : elle doit SIGNIFIER."""
    if err:
        return ILLISIBLE, err
    if valeur is None:
        return INCONNUE, "rend None : l'arbitre doit s'abstenir"
    if nom == "backlog":
        # (valeur, age_s, source) — le seul triplet, parce qu'il a deja menti.
        try:
            v, age, src = valeur
        except Exception:  # noqa: BLE001
            return ILLISIBLE, "forme inattendue"
        if v is None or int(v) < 0:
            return INCONNUE, "backlog=%s src=%s" % (v, src)
        if age is not None and age > 93600:
            return INCONNUE, "snapshot perime (%.0f h)" % (age / 3600.0)
        return MESUREE, "age %.0f h" % ((age or 0) / 3600.0)
    if nom == "disque_occupation_pct":
        # Un ratio PDH n'a pas de valeur a sa premiere collecte, et le compteur est
        # refuse aux comptes hors du groupe S-1-5-32-559. Les deux cas rendent
        # INCONNUE -- jamais 0, qui se lirait « disque au repos ».
        return (MESUREE, "") if isinstance(valeur, (int, float)) else (
            INCONNUE, "pas de valeur (premiere collecte ou compteur refuse)")
    if nom == "coder_conns" and isinstance(valeur, int) and valeur < 0:
        return INCONNUE, "mesure absente (protege par contrat)"
    if nom == "coder_up" and valeur == "INCERTAIN":
        return INCONNUE, "preuves partielles"
    return MESUREE, ""


def _occupation_disque():
    """% temps disque, vu par un process NEUF.

    ATTENTION A LA LECTURE DU COUT. Un compteur de RATIO n'a pas de valeur avant sa
    deuxieme collecte, et cet audit tourne dans un process qui vient de naitre : il
    doit donc amorcer puis attendre. La seconde qui apparait dans `cout_ms` est le
    prix de l'AMORCE, PAS celui d'une decision -- dans le regulateur la requete PDH
    reste ouverte entre les ticks et une lecture coute 0,3 ms (mesure 2026-09-05).
    Sans cette phrase, `sondes_lentes_ms` ferait conclure que l'arbitre paie une
    seconde par arbitrage, ce qui est faux d'un facteur 3000.
    """
    import time as _t

    from nokido_agent.app.forge_vitals_channels import grp_disque

    etat: dict = {}
    grp_disque(etat)          # amorce : rend {} par contrat
    _t.sleep(1.05)            # un ratio a besoin de deux points espaces
    vals, _note = grp_disque(etat)
    return vals.get("dbsy")


def audit() -> dict:
    from nokido_agent.app import forge_resource_manager as rm

    try:
        from nokido_agent.app.forge_endocrine_system import get_rhythm
    except Exception:  # noqa: BLE001
        get_rhythm = None
    st = rm.llamacpp_native_status()
    try:
        intents = rm.get_active_intents()
    except Exception:  # noqa: BLE001
        intents = {}
    sources = {
        "rhythm": (get_rhythm or (lambda: None)),
        "coder_up": lambda: st.get("verdict"),
        "coder_conns": rm._coder_conns,
        "chains_active": lambda: intents.get("chains_active"),
        "embed_wanted": lambda: intents.get("embed_wanted"),
        "backlog": rm._backlog_pending_qualifie,
        "embedder_up": lambda: rm._port_ecoute(
            int(os.environ.get("LAFORGE_LLAMA_EMBED_PORT", "8099"))),
        "coder_ram_gb": lambda: st.get("ram_gb"),
        "free_gb": rm._free_now,
        "demande_active": rm._demande_active_llama,
        "inutile_s": rm._inutile_s_llama,
    }
    observees = {"disque_occupation_pct": _occupation_disque}
    entrees, observ = {}, {}
    for nom, fn in list(sources.items()) + list(observees.items()):
        t0 = time.time()
        err, valeur = "", None
        try:
            valeur = fn()
        except Exception as exc:  # noqa: BLE001
            err = "%s: %s" % (type(exc).__name__, str(exc)[:70])
        ms = round((time.time() - t0) * 1000.0, 1)
        etat, remarque = _classer(nom, valeur, err)
        cible = entrees if nom in sources else observ
        src, sens, conso = (CONTRAT.get(nom) or CONTRAT_OBSERVE.get(nom)
                            or ("?", "?", "?"))
        cible[nom] = {"valeur": repr(valeur)[:90], "etat": etat, "remarque": remarque,
                      "cout_ms": ms, "source": src, "semantique": sens,
                      "consommation": conso}
    compte: dict = {}
    for e in entrees.values():
        compte[e["etat"]] = compte.get(e["etat"], 0) + 1
    lentes = {k: v["cout_ms"] for k, v in list(entrees.items()) + list(observ.items())
              if v["cout_ms"] >= 100.0}
    return {"ts": time.time(), "entrees": entrees, "observees": observ,
            "resume": compte, "sondes_lentes_ms": lentes,
            "verdict": "COUVERTURE COMPLETE" if compte.get(MESUREE) == len(entrees)
                       else "COUVERTURE INCOMPLETE"}


def journal(chemin: str = "") -> dict:
    """Denominateurs du journal de decision (A0-4b). Lecture SEULE.

    Les quatre comptes restent SEPARES, et c'est le point : melanges, « 0 action »
    se lirait « 0 occasion ». Mesure du 2026-09-05 qui l'impose -- 0 arbitrage
    journalise en 5,7 jours, sans qu'on puisse dire si l'arbitre avait seulement
    ete appele. `illisibles` est imprime pour la meme raison : un journal qu'on
    n'a pas pu lire n'est pas un journal vide.
    """
    import collections

    p = chemin or os.path.join(ROOT, "sandbox", "decision_observations.jsonl")
    out = {"fichier": p, "ticks_all": 0, "ticks_decision_observes": 0,
           "ticks_sautes": 0, "ticks_with_action": 0, "ticks_with_unknown": 0,
           "illisibles": 0, "sauts": {}, "actions": {}, "inconnues_par_entree": {},
           "policy_ids": {}, "fenetre": None}
    if not os.path.exists(p):
        out["absent"] = True   # ABSENT n'est pas VIDE : le journal peut n'avoir jamais tourne
        return out
    sauts = collections.Counter()
    actions = collections.Counter()
    inc = collections.Counter()
    pol = collections.Counter()
    ts: list = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                d = json.loads(ligne)
            except Exception:  # noqa: BLE001
                out["illisibles"] += 1
                continue
            out["ticks_all"] += 1
            pol[d.get("policy_id") or "?"] += 1
            if isinstance(d.get("ts"), (int, float)):
                ts.append(d["ts"])
            if d.get("saut"):
                out["ticks_sautes"] += 1
                sauts[d["saut"]] += 1
                continue
            out["ticks_decision_observes"] += 1
            a = (d.get("output") or {}).get("action") or "?"
            actions[a] += 1
            if a not in ("noop", "?"):
                out["ticks_with_action"] += 1
            manquantes = d.get("inconnues") or []
            if manquantes:
                out["ticks_with_unknown"] += 1
                inc.update(manquantes)
    out["sauts"] = dict(sauts)
    out["actions"] = dict(actions)
    out["inconnues_par_entree"] = dict(inc.most_common())
    out["policy_ids"] = dict(pol)
    if ts:
        out["fenetre"] = {"debut": min(ts), "fin": max(ts),
                          "duree_h": round((max(ts) - min(ts)) / 3600.0, 2)}
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — muet-ok : sortie non reconfigurable
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--journal", action="store_true",
                    help="denominateurs du journal de decision (A0-4b), lecture seule")
    a = ap.parse_args()
    if a.journal:
        j = journal()
        if a.json:
            print(json.dumps(j, ensure_ascii=False, indent=1))
            return 0
        if j.get("absent"):
            print("journal ABSENT (%s) -- jamais ecrit, ce qui n'est PAS un journal vide"
                  % j["fichier"])
            return 0
        print("fenetre : %s" % json.dumps(j["fenetre"], ensure_ascii=False))
        for c in ("ticks_all", "ticks_sautes", "ticks_decision_observes",
                  "ticks_with_action", "ticks_with_unknown", "illisibles"):
            print("  %-26s %d" % (c, j[c]))
        print("  sauts        :", json.dumps(j["sauts"], ensure_ascii=False))
        print("  actions      :", json.dumps(j["actions"], ensure_ascii=False))
        print("  inconnues    :", json.dumps(j["inconnues_par_entree"], ensure_ascii=False))
        print("  policy_ids   :", json.dumps(j["policy_ids"], ensure_ascii=False))
        return 0
    r = audit()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print("%-16s %-10s %-9s %-30s %s" % ("ENTREE", "ETAT", "COUT", "VALEUR", "REMARQUE"))
    for nom, e in r["entrees"].items():
        print("%-16s %-10s %7s  %-30s %s"
              % (nom, e["etat"], "%.0f ms" % e["cout_ms"], e["valeur"][:30],
                 e["remarque"][:60]))
    if r.get("observees"):
        # Affichees SOUS les entrees et nommees autrement : une grandeur qu'on
        # mesure sans la consommer ne doit pas se lire comme une entree de la
        # decision. Le jour ou elle en devient une, elle remonte dans CONTRAT et
        # le garde d'egalite stricte l'exige.
        print("\nOBSERVEES (mesurees, PAS encore consommees par arbitrer_pression) :")
        for nom, e in r["observees"].items():
            print("%-16s %-10s %7s  %-30s %s"
                  % (nom, e["etat"], "%.0f ms" % e["cout_ms"], e["valeur"][:30],
                     e["consommation"][:60]))
    print("\nresume :", json.dumps(r["resume"], ensure_ascii=False))
    if r["sondes_lentes_ms"]:
        # Le cout mesure ici est celui d'un process NEUF, pas celui d'un tick. Les
        # deux se confondaient dans l'ancien libelle « appelees a chaque tick », qui
        # aurait fait imputer a l'arbitre une seconde d'amorce PDH qu'il ne paie
        # jamais (requete gardee ouverte : 0,3 ms par lecture). On separe donc ce
        # qu'une entree coute A CET AUDIT de ce qu'elle coute AU REGULATEUR.
        print("sondes LENTES (>=100 ms DANS CET AUDIT, process neuf) :",
              json.dumps(r["sondes_lentes_ms"], ensure_ascii=False))
        for _n in r["sondes_lentes_ms"]:
            _c = (CONTRAT.get(_n) or CONTRAT_OBSERVE.get(_n) or ("", "", ""))[2]
            if "AUCUNE consommation" in _c:
                print("   ^ %s n'est appelee par AUCUN tick : ce cout est celui de "
                      "l'amorce, pas d'une decision" % _n)
    print("verdict :", r["verdict"])
    return 0 if r["verdict"] == "COUVERTURE COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
