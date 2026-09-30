"""Capteur de DERIVE MEMOIRE par service nomme — la grandeur qui manquait.

Pourquoi ce module existe. Le 2026-08-04, `NokidoLlamaEmbed` est passe de 2,69 Go
(sa taille au demarrage) a 10,92 Go, la machine est tombee a 0,03 Go libre, et le
garde d'admission a fini par refuser tout job. Quatre bancs successifs — LIF regle,
tete lineaire apprise, SpikingMLP entraine, traits reseau — avaient echoue a
anticiper quoi que ce soit sur les vitals, et pour une raison simple : **la grandeur
qui derivait n'etait mesuree nulle part**. Un seuil global sur la RAM totale voit la
consequence ; il ne voit jamais QUI derive.

Ce que ce capteur ajoute, et que rien d'autre ne couvre (verifie) :
  - `forge_orphan_reaper` tue des process ORPHELINS — question du parent, pas de la taille ;
  - `forge_regulation_efficacy.gradient_rss` mesure une pente sur ~6 s pour UN pid —
    instantane, et par pid, pas par service ;
  - `app/hardware/mem_watchdog` suit `tracemalloc` DANS un process Python — memoire
    intra-process, pas le RSS d'un service externe comme llama-server.

Le principe : la reference n'est pas un seuil absolu (10 Go est normal pour un LLM,
scandaleux pour un embedder) mais le **rapport a la taille observee du service
lui-meme**. Un service a 4x sa taille de demarrage est une anomalie qu'aucun seuil
global ne peut exprimer.

Deux choix qui evitent les pieges deja payes :
  1. **Etat COMPACT, pas un journal.** 54 services x 4 mesures/min feraient 311 000
     lignes par jour. On maintient un etat par service (min / max / dernier / n),
     reecrit en place : taille constante.
  2. **Le changement de PID REINITIALISE la reference.** Sans ca, le minimum
     d'avant-redemarrage servirait de base apres, et un service sain paraitrait
     derive a vie. C'est la lecon de « un PID n'est pas une identite » : ici le
     NOM porte l'identite, le PID signale la discontinuite.

Trois etats, jamais deux : un service est `derive`, `sain`, ou `sans_reference`
(pas encore assez d'echantillons). « Pas de reference » n'est pas « tout va bien ».

Usage :
    LAFORGE_PYTHON app/forge_service_rss_watch.py --once      # un echantillon
    LAFORGE_PYTHON app/forge_service_rss_watch.py --report    # etat + derives
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

__FORGE_COLOR__ = "sympathique/proprioception-memoire"

import json
import logging
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ETAT = ROOT / "sandbox" / "service_rss_state.json"
SUPERVISEUR = "http://127.0.0.1:8765/supervisor/status"

# En dessous, le bruit de mesure domine et un service qui passe de 20 a 60 Mo
# n'interesse personne.
PLANCHER_GO = 0.20
# Un service a plus de N fois sa taille de reference derive. 2.5 laisse passer la
# croissance normale d'un cache tout en attrapant le cas mesure (2,69 -> 10,92 = 4,1x).
RATIO_DERIVE = 2.5
# En dessous de ce nombre d'echantillons, on ne conclut RIEN.
MIN_ECHANTILLONS = 5
# Un process qui vient de demarrer n'a pas fini de charger : son RSS d'alors
# sous-estimerait la reference et ferait crier a la derive sur un service sain.
UPTIME_MIN_S = 90.0
# PART DE LA MACHINE — le ratio ne suffit pas (mesure 2026-08-25). Un service peut
# tenir le quart de la memoire du corps tout en restant a 1,2x SA propre reference,
# et passer ainsi pour « sain » : le ratio le compare a lui-meme, jamais au corps qui
# l'heberge. Au-dela de cette part, on le NOMME — sans rien decider a sa place :
# nommer un cout n'est pas ordonner une eviction.
PART_MACHINE_ALERTE = float(os.environ.get("LAFORGE_PART_MACHINE_ALERTE", "0.25"))

logger = logging.getLogger(__name__)

_CACHE_REGISTRE: dict = {"ts": 0.0, "services": {}}
_REGISTRE_TTL_S = 60.0


def _registre() -> dict:
    """{nom: pid} depuis le superviseur. {} si injoignable — et l'appelant le DIT."""
    if time.time() - _CACHE_REGISTRE["ts"] < _REGISTRE_TTL_S:
        return _CACHE_REGISTRE["services"]
    _CACHE_REGISTRE["ts"] = time.time()
    try:
        with urllib.request.urlopen(SUPERVISEUR, timeout=3) as r:
            d = json.loads(r.read())
        _CACHE_REGISTRE["services"] = {
            nom: s["pid"] for nom, s in (d.get("services") or {}).items() if s.get("pid")
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[rss_watch] superviseur injoignable (%s) — pas d'echantillon",
                       type(e).__name__)
        _CACHE_REGISTRE["services"] = {}
    return _CACHE_REGISTRE["services"]


def _charger() -> dict:
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ecrire(etat: dict) -> None:
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        tmp = ETAT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ETAT)
    except Exception as e:  # noqa: BLE001
        logger.warning("[rss_watch] etat non ecrit (%s)", type(e).__name__)


# Au-dela de ce delai SANS mesure ET hors du registre, une entree est un FOSSILE
# (service disparu, ou renomme). On ne purge jamais sur la seule absence du
# registre : un superviseur momentanement injoignable effacerait tout
# l'historique, et le capteur repartirait sans reference au pire moment.
FOSSILE_S = 6 * 3600


def echantillon() -> dict:
    """Un tour de mesure. Rend {mesures, ignores, raison_si_vide}."""
    try:
        import psutil
    except Exception:
        return {"mesures": 0, "raison": "psutil_absent"}

    services = _registre()
    if not services:
        return {"mesures": 0, "raison": "superviseur_injoignable"}

    etat = _charger()
    now = time.time()
    vus = ignores = 0
    sous_plancher: list = []
    for nom, pid in services.items():
        try:
            p = psutil.Process(pid)
            mi = p.memory_info()
            # MESURE 2026-08-19 : `rss` est le WORKING SET sous Windows, donc une
            # grandeur PAGINABLE. Le hub engageait 6,53 Go de memoire privee
            # pendant que son rss retombait a 0,85 Go, et ce capteur le classait
            # « sain » (dernier/min = 1,06) alors que son propre `rss_max` avait
            # vu 5,28 Go. Autrement dit : plus l'OS paginait un process gourmand,
            # plus il paraissait sain -- le capteur devenait aveugle exactement
            # dans le cas qu'il existe pour voir.
            # On mesure donc l'ENGAGEMENT PRIVE quand la plateforme l'expose
            # (Windows), qui ne retombe pas sous pagination ; ailleurs `rss`
            # reste la meilleure approximation disponible.
            prive = getattr(mi, "private", None)
            grandeur = "private" if prive else "rss"
            rss = (prive or mi.rss) / 1e9
            uptime = now - p.create_time()
        except Exception:
            ignores += 1
            continue
        if rss < PLANCHER_GO:
            # ECART DELIBERE, mais COMPTE. Mesure 2026-09-19 : ce `continue` etait
            # muet, donc 45 services sur 57 sortaient du perimetre sans laisser de
            # trace -- ni dans `mesures`, ni dans `ignores`. Le rapport annoncait
            # « 0 derive, 7 sains » pour 12 % du corps, et rien ne disait les 88 %
            # restants. Un filtre qui ecarte sans le dire surestime la couverture
            # en silence : on retient le meme critere, on rend son denominateur.
            sous_plancher.append(nom)
            continue
        e = etat.get(nom)
        # Changement de PID = nouveau processus : la reference d'avant ne vaut plus.
        # Changement de GRANDEUR non plus : comparer un engagement prive a une
        # reference construite en working set fabriquerait une fausse derive le
        # jour de la bascule, et un faux capteur coute plus cher que pas de capteur.
        if e is None or e.get("pid") != pid or e.get("grandeur") != grandeur:
            e = {"pid": pid, "grandeur": grandeur, "rss_min": None,
                 "rss_max": rss, "n": 0, "depuis": now}
            etat[nom] = e
        # Fenetre glissante, PAS la derniere valeur seule. Mesure 2026-08-04 :
        # NokidoLlamaEmbed lu a 8,12 Go puis a 7,99 Go 25 s plus tard — le RSS
        # d'un serveur sous charge OSCILLE. Conclure sur un echantillon unique
        # ferait crier a la fuite sur un cache qui travaille, et c'est
        # exactement l'erreur que je venais de commettre en le rapportant.
        fen = list(e.get("fenetre") or [])
        fen.append(round(rss, 3))
        e["fenetre"] = fen[-7:]
        e["rss_dernier"] = round(sorted(e["fenetre"])[len(e["fenetre"]) // 2], 3)
        e["rss_max"] = round(max(e.get("rss_max") or rss, rss), 3)
        # PIC HISTORIQUE fourni par l'OS. `peak_pagefile` cumule le maximum
        # d'engagement depuis le demarrage du process : contrairement a une
        # fenetre glissante, il ne peut pas passer ENTRE deux echantillons.
        # MESURE 2026-08-19 : le hub oscillait entre 1,7 et 6,5 Go et avait
        # atteint 13,8 Go de pic -- sur une machine qui n'expose que 23,67 Go.
        # Sept mesures espacees d'une minute ne pouvaient pas le voir : elles
        # echantillonnent, un pic est un EVENEMENT. Or c'est l'amplitude, pas la
        # moyenne, qui declenche pagination et compression memoire.
        pic = getattr(mi, "peak_pagefile", None) or getattr(mi, "peak_wset", None)
        if pic:
            e["pic_engage"] = round(pic / 1e9, 3)
        e["dernier_ts"] = now
        # La reference ne se construit qu'une fois le chargement termine.
        if uptime >= UPTIME_MIN_S:
            ref = e.get("rss_min")
            e["rss_min"] = round(rss if ref is None else min(ref, rss), 3)
            e["n"] = int(e.get("n") or 0) + 1
        vus += 1
    # Purge des FOSSILES. `LaForgeMCP` (nom d'avant le renommage, pid mort)
    # figurait encore dans l'etat avec des mesures de la VEILLE, et le rapport le
    # presentait comme un service surveille : un inventaire qui compte des morts
    # fait croire a une couverture qu'on n'a pas.
    perimees = [n for n, v in etat.items()
                if n not in services
                and (now - float(v.get("dernier_ts") or 0)) > FOSSILE_S]
    for n in perimees:
        etat.pop(n, None)
    _ecrire(etat)
    return {"declares": len(services), "mesures": vus, "ignores": ignores,
            "sous_plancher": len(sous_plancher), "plancher_go": PLANCHER_GO,
            "sous_plancher_noms": sorted(sous_plancher),
            "services_suivis": len(etat), "fossiles_purges": len(perimees)}


def derives(ratio: float = RATIO_DERIVE) -> list[dict]:
    """Services dont la taille a derive par rapport a LEUR propre reference."""
    # Part de machine : lue UNE fois pour toute la passe, pas par service.
    try:
        import psutil

        _total_go = float(psutil.virtual_memory().total) / 1e9
    except Exception:  # noqa: BLE001
        _total_go = None
    out = []
    for nom, e in _charger().items():
        ref, cur, n = e.get("rss_min"), e.get("rss_dernier"), int(e.get("n") or 0)
        if cur is None:
            continue
        if ref is None or n < MIN_ECHANTILLONS:
            out.append({"service": nom, "etat": "sans_reference",
                        "rss_go": cur, "echantillons": n,
                        "pourquoi": "moins de %d mesures apres chargement — "
                                    "ne rien conclure" % MIN_ECHANTILLONS})
            continue
        r = cur / max(ref, 1e-6)
        pic = e.get("pic_engage")
        r_pic = (pic / max(ref, 1e-6)) if pic else None
        part = round(cur / _total_go, 3) if _total_go else None
        if r >= ratio:
            etat_svc = "derive"
        elif r_pic is not None and r_pic >= ratio:
            # Revenu a sa taille, mais il a DEJA occupe bien plus. Le taire fait
            # passer pour sain un service qui sature la machine par a-coups, et
            # c'est precisement l'amplitude qui la fait tomber, pas la moyenne.
            etat_svc = "pic_transitoire"
        elif part is not None and part >= PART_MACHINE_ALERTE:
            # ANGLE MORT DU RATIO, mesure 2026-08-25. Le hub tenait 7,66 Go
            # d'engagement prive sur 23,67 — 32 % du corps — pour une reference de
            # 6,24, soit x1,23 : tres loin du seuil, donc classe « sain », et le
            # rapport rendait `derive: []` pendant qu'un seul service tenait le
            # quart de la memoire. La cause est dans la reference elle-meme : prise
            # 90 s apres le demarrage, elle inclut deja l'index charge, donc le
            # capteur se recale sur le plancher gonfle. Aucun reglage de ratio ne
            # rattrape ca ; un critere absolu, si. Il COMPLETE le ratio, il ne le
            # remplace pas.
            etat_svc = "part_machine"
        else:
            etat_svc = "sain"
        out.append({
            "service": nom,
            "etat": etat_svc,
            # `rss_go` est la MEDIANE de la fenetre, pas la derniere lecture.
            "rss_go": cur, "reference_go": ref, "ratio": round(r, 2),
            "pic_go": pic, "ratio_pic": round(r_pic, 2) if r_pic else None,
            "part_machine": part,
            "echantillons": n, "fenetre": e.get("fenetre"),
        })
    # ANGLE MORT DU PERIMETRE, mesure 2026-09-19. Cette boucle parcourait l'ETAT
    # PERSISTE (7 entrees) et jamais le REGISTRE (51 services avec un pid). Les
    # services que `psutil` ne peut pas ouvrir -- ceux d'un AUTRE COMPTE -- ne
    # sont jamais echantillonnes, donc n'entraient dans aucune categorie : ni
    # derive, ni sans_reference. Le rapport rendait « 0 derive, 7 sains » sans
    # dire qu'il ne parlait que de 7 services sur 59.
    #
    # Un capteur qui tait son perimetre fabrique du FAUX CALME : « rien a
    # signaler » devient indistinguable de « je n'ai pas pu regarder ».
    # Trois etats, jamais deux : mesure / sans reference / JAMAIS MESURE.
    connus = {x["service"] for x in out}
    for nom in _registre():
        if nom in connus:
            continue
        out.append({
            "service": nom, "etat": "jamais_mesure", "rss_go": None,
            "echantillons": 0,
            "pourquoi": "declare au superviseur mais jamais echantillonne — "
                        "process illisible (autre compte) ou disparu avant la passe. "
                        "ETAT INCONNU, ce n'est PAS une preuve de sante",
        })
    out.sort(key=lambda x: -(x.get("ratio") or 0))
    return out


def alerter(ratio: float = RATIO_DERIVE) -> list[dict]:
    """Journalise les derives comme OBSERVATIONS (pas des actes)."""
    mauvais = [d for d in derives(ratio)
               if d["etat"] in ("derive", "part_machine")]
    # ANTI-BRUIT (mesure 2026-08-20) : `rss_derive_detected` pesait 1645 des 2111
    # evenements du journal de cycle de vie sur 7 jours — 78 %, ~235 par jour, la
    # MEME observation reemise a chaque passage. Un capteur qui repete noie le
    # signal qu'il porte : la vraie derive (le hub a x9,9, pic engage 15,9 Go)
    # etait indistinguable du bruit de fond. On ne journalise donc QUE sur
    # transition : premiere detection, ou aggravation nette (+25 % de ratio),
    # ou apres une accalmie de 6 h. L'observation reste rendue a l'appelant
    # dans tous les cas — on change ce qu'on ECRIT, jamais ce qu'on MESURE.
    etat = _charger()
    change = False
    for d in mauvais:
        e = etat.get(d["service"]) or {}
        vu_ts = float(e.get("alerte_ts") or 0)
        vu_ratio = float(e.get("alerte_ratio") or 0)
        r = float(d.get("ratio") or 0)
        neuf = (vu_ts <= 0) or (r >= vu_ratio * 1.25) or ((time.time() - vu_ts) > 6 * 3600)
        if not neuf:
            continue
        try:
            from nokido_agent.app.forge_lifecycle_audit import record

            _part = d.get("part_machine")
            record("rss_derive_detected", domain="regulation",
                   reason="%s a %.2f Go pour une reference de %.2f Go (x%.1f)%s"
                          % (d["service"], d["rss_go"], d["reference_go"], d["ratio"],
                             "" if _part is None else
                             " — %.0f %% du corps [%s]" % (100.0 * _part, d["etat"])),
                   target=d["service"])
            if d["service"] in etat:
                etat[d["service"]]["alerte_ts"] = time.time()
                etat[d["service"]]["alerte_ratio"] = r
                change = True
        except Exception as e:  # noqa: BLE001
            logger.warning("[rss_watch] derive non journalisee (%s)", type(e).__name__)
    if change:
        try:
            _ecrire(etat)
        except Exception as e:  # noqa: BLE001
            logger.warning("[rss_watch] etat d'alerte non persiste (%s)", type(e).__name__)
    return mauvais


def _main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Derive memoire par service nomme")
    ap.add_argument("--once", action="store_true", help="un echantillon puis sortie")
    ap.add_argument("--report", action="store_true", help="etat courant + derives")
    ap.add_argument("--ratio", type=float, default=RATIO_DERIVE)
    a = ap.parse_args(argv)
    if a.once or not a.report:
        print(json.dumps(echantillon(), ensure_ascii=False))
    if a.report:
        d = derives(a.ratio)
        jamais = [x["service"] for x in d if x["etat"] == "jamais_mesure"]
        declares = len(_registre())
        couverts = len([x for x in d if x["etat"] != "jamais_mesure"])
        print(json.dumps({
            # DENOMINATEUR D'ABORD : sans lui, « 0 derive » ne se distingue pas
            # de « je n'ai pas pu regarder » (mesure 2026-09-19).
            "couverture": {
                "declares_au_superviseur": declares,
                "effectivement_suivis": couverts,
                "jamais_mesures": len(jamais),
                "verdict_porte_sur": "%d/%d services" % (couverts, declares),
            },
            "seuil_ratio": a.ratio,
            "derive": [x for x in d if x["etat"] == "derive"],
            "pic_transitoire": [x for x in d if x["etat"] == "pic_transitoire"],
            "part_machine": [x for x in d if x["etat"] == "part_machine"],
            "sans_reference": [x["service"] for x in d if x["etat"] == "sans_reference"],
            "jamais_mesures": jamais,
            "sains": len([x for x in d if x["etat"] == "sain"]),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
