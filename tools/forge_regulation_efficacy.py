#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Capteur META : la regulation elle-meme est-elle efficace, ou POMPE-t-elle ?

Le corps sait mesurer ses ressources (RAM, CPU, GPU) et il sait declencher des
remedes. Ce qu'il ne savait PAS mesurer, c'est si ses remedes SERVENT a quelque
chose. Un effecteur qui retire 2 Go toutes les 24 s ne regule pas : il pompe, et
son cout devient le probleme qu'il croit soigner. Personne ne le voyait.

Complementaire de `forge_regulation_loops`, PAS un doublon :

  forge_regulation_loops : debit MAXIMAL THEORIQUE, calcule depuis les parametres
                           DECLARES d'une boucle (tick, seuil, refractaire).
                           Repond a « ce cablage peut-il s'emballer ? »
  ce module              : debit REEL OBSERVE, lu dans le journal de cycle de vie.
                           Repond a « s'est-il emballe, en fait ? »

Un cablage sain sur le papier peut pomper en vrai (deux appelants, un respawn qui
recree la cible, un seuil qui oscille) ; l'inverse existe aussi. Les budgets par
gravite viennent de `forge_regulation_loops.SEVERITY_BUDGET_PER_HOUR` — un seul
bareme dans le corps, pas un second invente ici.

Deux pieges MESURES le 2026-07-30, qui dictent la forme du capteur :

1. **La moyenne all-time MENT.** `stop/llama-server:8091` : 73 tirs, intervalle
   MEDIAN 736 s, soit ~1/h — apparemment sous le budget de 6/h. Mais 14 de ses
   intervalles sont sous 300 s, le plus court a 32 s, soit 112/h en rafale. Une
   moyenne lisse exactement ce qu'on cherche. Le debit se mesure donc sur une
   fenetre par COMPTAGE (les N derniers tirs), jamais sur toute l'histoire.
2. **Une abstention n'est pas un tir.** `evict_skipped/*` revient toutes les
   ~122 s = le tick du sampler : c'est la boucle qui re-decide « non ». La
   compter comme un tir ferait crier au pompage sur un corps qui se retient
   precisement comme il faut. Seuls les ACTES sont comptes.

Usage :
    LAFORGE_PYTHON tools/forge_regulation_efficacy.py            # verdicts
    LAFORGE_PYTHON tools/forge_regulation_efficacy.py --json
    LAFORGE_PYTHON tools/forge_regulation_efficacy.py --cible reclaim/rag_dense_cache
"""

from __future__ import annotations

__FORGE_COLOR__ = "sn-vegetatif/meta-regulation"

import argparse
import collections
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

# Bareme unique du corps — importe, jamais recopie.
try:
    from nokido_agent.tools.forge_regulation_loops import SEVERITY_BUDGET_PER_HOUR, Loop
except Exception as exc:  # pragma: no cover - le capteur doit dire pourquoi il est aveugle
    print("[efficacy] bareme des budgets INJOIGNABLE : %s" % exc, file=sys.stderr)
    SEVERITY_BUDGET_PER_HOUR = {"critical": 2.0, "high": 6.0, "medium": 12.0, "low": 60.0}
    Loop = None  # type: ignore[assignment]

# -- Ce qui compte comme un ACTE (le corps change) vs une ABSTENTION (il decide) --
# Un acte a un cout et un contrecoup ; une abstention n'en a aucun. Les melanger
# est le faux positif n1 de ce capteur (mesure : 196 abstentions vs 122 actes).
ACTES = frozenset({
    "stop", "kill", "evict", "reclaim", "restart", "pause", "sleep", "start",
    "unpause", "resume", "force_recycle", "trim",
})
# Suffixes qui signent une NON-action, prefixes qui signent une observation.
SUFFIXES_ABSTENTION = ("_skipped", "_refused", "_deferred", "_noop")
PREFIXES_OBSERVATION = ("want", "test", "reboot_detected", "crash_detected", "detected")

SEVERITE_PAR_ACTION = {
    "kill": "critical",
    "force_recycle": "critical",
    "stop": "high",
    "evict": "high",
    "reclaim": "high",
    "trim": "high",
    "restart": "medium",
    "pause": "medium",
    "unpause": "low",
    "resume": "low",
    "sleep": "low",
    "start": "low",
}

# Fenetre par COMPTAGE : les N derniers tirs. Assez court pour voir une rafale,
# assez long pour ne pas crier sur deux tirs rapproches legitimes.
FENETRE_COMPTAGE = 6
# En dessous de ce nombre de tirs, on ne conclut RIEN (pas « c'est sain »).
MIN_TIRS_POUR_CONCLURE = 3


def _epoch(valeur) -> float:
    """ts du journal = ISO8601 avec offset. Rend 0.0 si illisible (jamais d'exception)."""
    if valeur is None:
        return 0.0
    if isinstance(valeur, (int, float)):
        return float(valeur)
    try:
        return datetime.fromisoformat(str(valeur)).timestamp()
    except Exception:
        return 0.0  # muet-ok : un ts illisible est ecarte plus bas, il ne doit pas tuer le capteur


def _nature(action: str) -> str:
    """acte | abstention | observation - determine si l'evenement se compte."""
    a = (action or "").strip().lower()
    if not a:
        return "observation"
    if a.endswith(SUFFIXES_ABSTENTION):
        return "abstention"
    if a in ACTES:
        return "acte"
    if a.startswith(PREFIXES_OBSERVATION) or a.endswith("_detected"):
        return "observation"
    return "observation"


def _verbe(action: str) -> str:
    """Racine de l'action, pour retrouver sa gravite ('evict_skipped' -> 'evict')."""
    a = (action or "").strip().lower()
    for suf in SUFFIXES_ABSTENTION:
        if a.endswith(suf):
            return a[: -len(suf)]
    return a


def journal(n: int = 5000) -> list[dict]:
    """Lit le journal de cycle de vie via son proprietaire, pas en re-parsant le fichier."""
    try:
        from nokido_agent.app import forge_lifecycle_audit as audit
        return [e for e in audit.tail(n, "") if isinstance(e, dict)]
    except Exception as exc:
        print("[efficacy] journal de cycle de vie INJOIGNABLE : %s" % exc, file=sys.stderr)
        return []


def _grouper(evenements: list[dict]) -> dict:
    """(action, cible) -> {nature, tirs: [epoch trie], volumes: [go]}"""
    par = collections.defaultdict(lambda: {"tirs": [], "volumes": []})
    for ev in evenements:
        action = str(ev.get("action") or "")
        extra = ev.get("extra") or {}
        cible = str(extra.get("target") or ev.get("domain") or "?")
        ts = _epoch(ev.get("ts"))
        if ts <= 0:
            continue
        clef = (action, cible)
        par[clef]["tirs"].append(ts)
        par[clef]["nature"] = _nature(action)
        try:
            par[clef]["volumes"].append(float(extra.get("ram_gb")))
        except (TypeError, ValueError):  # muet-ok : absence de Go = normale ici
            # Marqueur sur la ligne du `except`, seule inspectee par le detecteur du
            # gate. Tous les effecteurs ne rendent pas un volume ; ce n'est pas un
            # chemin d'erreur avale, c'est un champ optionnel.
            pass
    for v in par.values():
        v["tirs"].sort()
    return dict(par)


def cadence(action: str, cible: str, evenements=None, maintenant=None) -> dict:
    """Debit REEL de cet effecteur, mesure sur une fenetre par COMPTAGE.

    Rend toujours un dict exploitable, meme sans donnee : `mesurable=False` dit
    « je ne peux pas voir », ce qui n'est PAS « tout va bien ».
    """
    now = float(maintenant if maintenant is not None else time.time())
    evenements = journal() if evenements is None else evenements
    groupes = _grouper(evenements)
    entree = groupes.get((action, cible)) or {"tirs": [], "volumes": [], "nature": _nature(action)}
    tirs = entree["tirs"]

    verbe = _verbe(action)
    gravite = SEVERITE_PAR_ACTION.get(verbe, "medium")
    budget = float(SEVERITY_BUDGET_PER_HOUR.get(gravite, 12.0))
    refractaire_exigee = 3600.0 / budget if budget > 0 else float("inf")

    base = {
        "action": action, "cible": cible, "nature": entree.get("nature", "observation"),
        "gravite": gravite, "budget_par_heure": budget,
        "refractaire_exigee_s": round(refractaire_exigee, 0),
        "tirs_total": len(tirs), "tirs_1h": sum(1 for t in tirs if now - t < 3600.0),
        "tirs_24h": sum(1 for t in tirs if now - t < 86400.0),
        "dernier_il_y_a_s": round(now - tirs[-1], 1) if tirs else None,
    }

    if base["nature"] != "acte":
        base.update({"mesurable": False, "verdict": "HORS PERIMETRE",
                     "pourquoi": "%s n'est pas un acte : une abstention ou une observation "
                                 "n'a ni cout ni contrecoup" % action})
        return base

    if len(tirs) < MIN_TIRS_POUR_CONCLURE:
        base.update({"mesurable": False, "verdict": "SANS MESURE",
                     "pourquoi": "%d tir(s), il en faut %d pour distinguer une rafale d'un hasard"
                                 % (len(tirs), MIN_TIRS_POUR_CONCLURE)})
        return base

    # Fenetre par COMPTAGE - c'est ici que la moyenne all-time cesse de mentir.
    fenetre = tirs[-FENETRE_COMPTAGE:]
    duree = fenetre[-1] - fenetre[0]
    debit_rafale = ((len(fenetre) - 1) * 3600.0 / duree) if duree > 0 else float("inf")

    intervalles = [b - a for a, b in zip(tirs, tirs[1:])]
    trop_serres = [i for i in intervalles if i < refractaire_exigee]
    recidive = sum(1 for a, b in zip(fenetre, fenetre[1:]) if (b - a) < refractaire_exigee)

    pompage = debit_rafale > budget
    if pompage:
        verdict = "POMPE"
    elif recidive:
        verdict = "PROCHE DU POMPAGE"
    else:
        verdict = "REGULE"

    base.update({
        "mesurable": True,
        "verdict": verdict,
        "debit_rafale_par_heure": round(debit_rafale, 1),
        "intervalle_median_s": round(statistics.median(intervalles), 0) if intervalles else None,
        "intervalle_min_s": round(min(intervalles), 0) if intervalles else None,
        "intervalles_trop_serres": len(trop_serres),
        "recidive_fenetre": recidive,
        "volume_total_go": round(sum(entree["volumes"]), 2) if entree["volumes"] else None,
        "pourquoi": "%.1f tirs/h en rafale sur les %d derniers contre un budget de %.1f/h"
                    % (debit_rafale, len(fenetre), budget),
    })
    return base


def refractaire_verdict(action: str, cible: str, ecoule_s: float,
                        base_absolue_s: float, urgence=None, evenements=None) -> dict:
    """Le tir est-il autorise MAINTENANT ? Reponse par le modele du corps.

    La refractaire ABSOLUE (`base_absolue_s`) couvre le contrecoup du remede et
    reste INFRANCHISSABLE, urgence maximale comprise - sans elle, la tetanie.
    La refractaire RELATIVE, elle, S'ALLONGE avec la recidive mesuree : un
    effecteur qui vient de tirer trois fois trop vite doit fournir une urgence
    d'autant plus forte. C'est la seule partie « adaptative », et elle s'appuie
    sur `Loop.should_fire` deja ecrit et deja teste ailleurs dans le corps.
    """
    mesure = cadence(action, cible, evenements=evenements)
    exigee = float(mesure.get("refractaire_exigee_s") or base_absolue_s)
    recidive = int(mesure.get("recidive_fenetre") or 0)

    # Allongement geometrique borne : 1 recidive double la fenetre, 2 la triplent...
    # Borne a 8x pour qu'un effecteur puni reste rattrapable par une urgence reelle.
    facteur = min(1.0 + recidive, 8.0)
    relative = max(float(base_absolue_s), exigee * facteur)

    if Loop is None:
        autorise = (ecoule_s >= relative) if urgence is None else (
            ecoule_s >= base_absolue_s and (urgence >= 1.0 or ecoule_s >= relative))
        return {"fire": autorise, "relative_s": round(relative, 0),
                "absolue_s": float(base_absolue_s), "recidive": recidive,
                "reason": "modele Loop injoignable, repli conservateur",
                "cadence": mesure}

    boucle = Loop(
        name="reclaim.%s/%s" % (action, cible),
        sensor="forge_regulation_efficacy.cadence (journal de cycle de vie)",
        remedy="%s %s" % (action, cible),
        tick_s=1.0, threshold_ticks=1,
        refractory_s=relative,
        launch_cooldown_s=0.0,
        severity=mesure.get("gravite", "medium"),
        source="forge_regulation_efficacy.refractaire_verdict",
        absolute_refractory_s=float(base_absolue_s),
        urgency_metric="ram_pct entre les consignes reveil/sommeil",
    )
    tir = boucle.should_fire(ecoule_s, urgence)
    tir.update({"relative_s": round(relative, 0), "absolue_s": float(base_absolue_s),
                "recidive": recidive, "cadence": mesure})
    return tir


# ── CAUSALITE PAR FLUX DE RESSOURCE (revue AGY 2026-07-30, R2) ────────────────
# Le premier critere de correlation etait FAUX : il appariait un etat symptomatique
# STATIQUE (« RAM >= 85 % ») a tout effecteur qui pompait, ce qu'AGY a nomme un faux
# couplage. Sur trois propositions produites, une seule etait solide.
#
# Le critere juste tient en deux exigences, et la premiere est calculable sur
# l'HISTORIQUE quand la seconde ne l'est pas :
#   1. RECOUVREMENT TEMPOREL : l'effecteur doit avoir tire PENDANT la fenetre ou le
#      symptome persistait. Un effecteur au repos depuis deux jours n'explique pas un
#      soin qui dure depuis deux cycles, quelle que soit sa reputation.
#   2. MEME RESSOURCE : un soin qui parle de RAM ne se correle qu'a un effecteur qui a
#      REELLEMENT deplace des octets (volume mesure au journal), pas a un effecteur
#      dont le nom evoque la memoire.
#
# Le gradient de consommation synchrone qu'AGY demande en plus n'est PAS reconstituable
# a posteriori -- il l'a confirme : le journal est evenementiel et `resource_state.json`
# est ecrase, pas historise. Il se mesure donc EN DIRECT, et seulement dans une fenetre
# d'action bornee (voir `gradient_rss`).
RECOUVREMENT_MIN_S = 900.0


def gradient_rss(pid: int, duree_s: float = 6.0, pas_s: float = 1.5) -> dict:
    """Pente de consommation memoire d'un pid, mesuree EN DIRECT sur une rafale bornee.

    Resolution 1,5 s : AGY donne 1 a 2 s pendant la fenetre d'action -- sous 1 s c'est
    du bruit d'ordonnancement, au-dela de 5 s on manque les pics ephemeres.

    RAFALE SYNCHRONE ET BORNEE, PAS UN DAEMON. C'est deliberé et c'est mesure : le
    2026-07-26 un echantillonneur supplementaire a gele le poste, d'ou la regle du
    PROPRIETAIRE UNIQUE -- un seul echantillonneur permanent par machine, et c'est
    celui de `forge_resource_manager`. Une rafale de quelques secondes, ouverte et
    fermee par l'appelant autour de son action, ne cree aucun proprietaire concurrent.

    Rend `mesurable: False` si le pid disparait ou refuse la lecture : trois etats,
    « je ne peux pas voir » n'est pas « pente nulle ».
    """
    import time as _t
    try:
        import psutil
        p = psutil.Process(int(pid))
    except Exception as exc:
        return {"mesurable": False, "pourquoi": "pid injoignable (%s)" % type(exc).__name__}
    pts = []
    fin = _t.time() + max(pas_s * 2, float(duree_s))
    while _t.time() < fin:
        try:
            pts.append((_t.time(), p.memory_info().rss))
        except Exception:
            return {"mesurable": False, "pourquoi": "lecture RSS refusee en cours de rafale",
                    "points": len(pts)}
        _t.sleep(pas_s)
    if len(pts) < 2:
        return {"mesurable": False, "pourquoi": "moins de 2 points", "points": len(pts)}
    dt = pts[-1][0] - pts[0][0]
    d_octets = pts[-1][1] - pts[0][1]
    return {"mesurable": True, "points": len(pts), "duree_s": round(dt, 2),
            "delta_go": round(d_octets / 1e9, 4),
            "pente_go_par_min": round((d_octets / 1e9) / (dt / 60.0), 4) if dt > 0 else 0.0,
            "rss_go": round(pts[-1][1] / 1e9, 3)}


def croisement_flux(cadence_effecteur: dict, soin_age_s: float,
                    soin_texte: str, maintenant=None) -> dict:
    """Le symptome et l'effecteur sont-ils lies par un FLUX, ou seulement voisins ?

    Rend `lie: False` avec la raison quand un des deux criteres manque -- c'est ce
    refus qui distingue ce critere de l'ancien, qui appariait tout a tout.
    """
    now = float(maintenant if maintenant is not None else time.time())
    dernier = cadence_effecteur.get("dernier_il_y_a_s")
    volume = cadence_effecteur.get("volume_total_go")

    # 1. Recouvrement temporel : l'effecteur a-t-il tire PENDANT la persistance ?
    fenetre = max(float(soin_age_s or 0.0), RECOUVREMENT_MIN_S)
    if dernier is None:
        return {"lie": False, "raison": "effecteur sans tir date — recouvrement indecidable"}
    if float(dernier) > fenetre:
        return {"lie": False,
                "raison": "dernier tir il y a %.0f s, hors de la fenetre du symptome (%.0f s)"
                          % (float(dernier), fenetre)}

    # 2. Meme ressource : le soin parle-t-il de ce que l'effecteur a REELLEMENT deplace ?
    parle_ram = any(m in (soin_texte or "").lower() for m in ("ram", "memoire", "mémoire", "oom"))
    a_deplace = bool(volume)
    if parle_ram and not a_deplace:
        return {"lie": False,
                "raison": "symptome memoire mais effecteur sans volume mesure au journal"}
    if not parle_ram:
        return {"lie": False,
                "raison": "symptome hors ressource memoire — aucun couplage par flux etabli"}

    # STATUT : PLAUSIBLE, jamais CONFIRME (revue AGY tour 3, T3.1). Le recouvrement
    # temporel historique etablit la CREDIBILITE ; la confirmation exigerait un gradient
    # de consommation mesure EN MEME TEMPS que l'action, et cette mesure n'existe pas a
    # posteriori -- le journal est evenementiel et l'instantane de ressources est
    # ecrase, pas historise. Un pompage passe reste donc PLAUSIBLE et ne devient
    # CONFIRME qu'a sa prochaine occurrence, sous fenetre synchrone (`gradient_rss`).
    # Nommer ce plafond evite la derive ou une credibilite se met a circuler en preuve.
    return {"lie": True, "statut": "PLAUSIBLE",
            "promotion": "CONFIRME exige un gradient synchrone a la prochaine occurrence",
            "raison": "tir il y a %.0f s dans la fenetre du symptome (%.0f s) et %.2f Go "
                      "reellement deplaces" % (float(dernier), fenetre, float(volume)),
            "recouvrement_s": round(fenetre - float(dernier), 0),
            "volume_go": volume}


def verdicts(evenements=None) -> list:
    """Tous les effecteurs du journal, les plus emballes d'abord."""
    evenements = journal() if evenements is None else evenements
    now = time.time()
    out = [cadence(a, c, evenements=evenements, maintenant=now)
           for (a, c) in _grouper(evenements)]
    ordre = {"POMPE": 0, "PROCHE DU POMPAGE": 1, "REGULE": 2,
             "SANS MESURE": 3, "HORS PERIMETRE": 4}
    return sorted(out, key=lambda d: (ordre.get(d["verdict"], 9),
                                      -(d.get("debit_rafale_par_heure") or 0)))


# --- A0-4d : abstention -> detresse, ASSOCIATION TEMPORELLE (jamais efficacite) ---
#
# Question posee : « quand le corps s'abstient, une detresse survient-elle ensuite ? »
# Ce n'est PAS « la politique est-elle efficace » -- aucune action n'est observee ici,
# et le ledger du learner a deja montre le danger de l'amalgame (`recovered: true`
# n'etablit pas qu'une action a cause la recuperation).
#
# TROIS PRECAUTIONS, chacune contre une erreur qui a failli etre commise :
#
# 1. EPISODES, pas evenements. `evict_skipped` revient au rythme du tick (~122 s,
#    gap median mesure 301 s) : compter chaque ligne ferait passer une boucle qui
#    re-decide « non » pour une rafale d'abstentions.
# 2. TEMOIN APPARIE SUR LA PRESSION. Sans temoin, on mesure la densite des
#    detresses, pas une association. Et un temoin UNIFORME ne suffit pas : mesure
#    du 2026-09-05, il donne un ratio de 3,70 la ou l'appariement sur la RAM libre
#    (+-0,3 Go) le ramene a 1,31. Environ 60 % de l'association apparente n'etait
#    que le niveau de pression, commun aux deux evenements.
# 3. BOOTSTRAP. Un tirage unique de temoin n'est pas un resultat ; on rend un IC.
#
# Resultat du 2026-09-05, a rejouer quand le corpus aura grandi : sur 151 episodes,
# les IC de deux fenetres sur trois CONTIENNENT 1. L'association n'est donc PAS
# etablie apres ajustement. Consequence pratique : rien n'indique qu'une politique
# moins prudente reduirait les detresses.
FENETRES_S = (300, 900, 1800)
GAP_EPISODE_S = 300.0        # ~ le gap median mesure entre deux abstentions
TOLERANCE_RAM_GO = 0.3       # largeur de l'appariement en pression
MARGE_TEMOIN_S = 300.0       # un temoin ne doit pas voisiner une abstention
BOOTSTRAP_N = 200


def _episodes(instants: list, gap: float = GAP_EPISODE_S) -> list:
    """Suites d'instants separes de moins de `gap`. Une rafale = UN episode."""
    if not instants:
        return []
    out, cur = [], [instants[0]]
    for t in instants[1:]:
        if t - cur[-1] <= gap:
            cur.append(t)
        else:
            out.append((cur[0], cur[-1]))
            cur = [t]
    out.append((cur[0], cur[-1]))
    return out


def association_abstention_detresse(chemin_vitals: str = "",
                                    chemin_actions: str = "") -> dict:
    """Association temporelle entre abstentions et detresses. LECTURE SEULE.

    Rend les denominateurs SEPARES : le journal de cycle de vie couvre bien plus
    longtemps que la serie vitale (45 j contre 5,7 j au 2026-09-05), et
    l'appariement en pression n'est possible que sur leur INTERSECTION. Melanger
    les deux surestimerait la couverture.
    """
    import bisect
    import random

    p_act = Path(chemin_actions) if chemin_actions else ROOT / "sandbox" / "lifecycle_actions.jsonl"
    p_vit = Path(chemin_vitals) if chemin_vitals else ROOT / "sandbox" / "vitals_history.jsonl"
    out: dict = {"illisibles_actions": 0, "illisibles_vitals": 0,
                 "abstentions": 0, "detresses": 0, "fenetres": {}}
    skip: list = []
    detr: list = []
    if not p_act.exists():
        out["absent"] = str(p_act)      # ABSENT n'est pas VIDE
        return out
    with p_act.open(encoding="utf-8", errors="replace") as f:
        for ligne in f:
            try:
                d = json.loads(ligne)
            except Exception:  # noqa: BLE001
                out["illisibles_actions"] += 1
                continue
            t = _epoch(d.get("ts"))
            if t <= 0:
                out["illisibles_actions"] += 1
                continue
            if d.get("action") == "evict_skipped":
                skip.append(t)
            elif d.get("action") == "evict_detresse":
                detr.append(t)
    vit: list = []
    if p_vit.exists():
        with p_vit.open(encoding="utf-8", errors="replace") as f:
            for ligne in f:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    out["illisibles_vitals"] += 1
                    continue
                if isinstance(d.get("ts"), (int, float)) and d.get("ram_free_gb") is not None:
                    vit.append((d["ts"], float(d["ram_free_gb"])))
    skip.sort()
    detr.sort()
    vit.sort()
    out["abstentions"] = len(skip)
    out["detresses"] = len(detr)
    if not skip or not detr or not vit:
        out["verdict"] = "SANS MESURE (une des trois sources est vide)"
        return out
    vts = [t for t, _ in vit]
    debut, fin = max(vts[0], skip[0]), min(vts[-1], skip[-1])
    dans = [t for t in skip if debut <= t <= fin]
    out["fenetre_actions_j"] = round((skip[-1] - skip[0]) / 86400.0, 1)
    out["fenetre_vitals_j"] = round((vts[-1] - vts[0]) / 86400.0, 1)
    out["abstentions_appariables"] = len(dans)

    def _ram(t: float, tol: float = 180.0):
        i = bisect.bisect_left(vts, t)
        meilleur = None
        for j in (i - 1, i):
            if 0 <= j < len(vts) and abs(vts[j] - t) <= tol:
                if meilleur is None or abs(vts[j] - t) < abs(vts[meilleur] - t):
                    meilleur = j
        return vit[meilleur][1] if meilleur is not None else None

    eps = [(a, b, _ram(a)) for a, b in _episodes(dans)]
    # Un episode dont la pression est INCONNUE est ECARTE et COMPTE : sans le
    # denominateur, la couverture serait surestimee en silence.
    out["episodes_total"] = len(eps)
    eps = [e for e in eps if e[2] is not None]
    out["episodes_apparies"] = len(eps)
    if not eps:
        out["verdict"] = "SANS MESURE (aucun episode a pression connue)"
        return out

    def _suivi(a: float, b: float, w: float) -> bool:
        i = bisect.bisect_left(detr, a)
        return i < len(detr) and detr[i] <= b + w

    def _voisin(t: float) -> bool:
        i = bisect.bisect_left(dans, t)
        return any(0 <= j < len(dans) and abs(dans[j] - t) <= MARGE_TEMOIN_S
                   for j in (i - 1, i))

    cand: dict = {}
    for _a, _b, r in eps:
        clef = round(r, 1)
        if clef not in cand:
            cand[clef] = [t for t, g in vit
                          if abs(g - r) <= TOLERANCE_RAM_GO and not _voisin(t)]
    for w in FENETRES_S:
        obs = sum(1 for a, b, _ in eps if _suivi(a, b, w))
        ratios = []
        for graine in range(BOOTSTRAP_N):
            random.seed(graine)
            tem = tot = 0
            for a, b, r in eps:
                c = cand[round(r, 1)]
                if not c:
                    continue
                tot += 1
                t = random.choice(c)
                if _suivi(t, t + (b - a), w):
                    tem += 1
            if tem:
                ratios.append((obs / len(eps)) / (tem / tot))
        ratios.sort()
        bloc = {"observe_pct": round(100.0 * obs / len(eps), 1), "n": len(eps)}
        if ratios:
            bloc["ratio_median"] = round(statistics.median(ratios), 2)
            bloc["ic95"] = [round(ratios[int(0.025 * len(ratios))], 2),
                            round(ratios[int(0.975 * len(ratios))], 2)]
            # Un IC qui CONTIENT 1 ne dit pas « pas d'effet » : il dit que ces
            # donnees ne permettent pas de le distinguer de zero.
            bloc["conclut"] = not (bloc["ic95"][0] <= 1.0 <= bloc["ic95"][1])
        out["fenetres"][str(w)] = bloc
    concluantes = [w for w, b in out["fenetres"].items() if b.get("conclut")]
    out["verdict"] = ("ASSOCIATION NON ETABLIE apres ajustement sur la pression"
                      if len(concluantes) < len(FENETRES_S)
                      else "ASSOCIATION ETABLIE sur toutes les fenetres")
    out["avertissement"] = ("association temporelle, PAS une efficacite de politique : "
                            "aucune action n'est observee ici")
    return out


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="La regulation POMPE-t-elle ? Debit REEL vs budget par gravite.")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--cible", help="un seul effecteur, au format action/cible")
    ap.add_argument("--tout", action="store_true",
                    help="inclure abstentions et observations (hors perimetre par defaut)")
    ap.add_argument("--association", action="store_true",
                    help="A0-4d : abstention -> detresse, association temporelle "
                         "avec temoin apparie sur la pression (lecture seule)")
    args = ap.parse_args(argv)

    if args.association:
        r = association_abstention_detresse()
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
            return 0
        if r.get("absent"):
            print("journal de cycle de vie ABSENT (%s) -- pas VIDE" % r["absent"])
            return 2
        print("ABSTENTION -> DETRESSE : association temporelle (jamais une efficacite)")
        print("=" * 78)
        # Les denominateurs d'abord, et separes : le journal d'actions couvre plus
        # longtemps que la serie vitale, et seule leur intersection est appariable.
        print("  abstentions %d | detresses %d | illisibles %d actions / %d vitals"
              % (r["abstentions"], r["detresses"],
                 r["illisibles_actions"], r["illisibles_vitals"]))
        print("  fenetres : actions %.1f j | vitals %.1f j -> appariables %s abstentions"
              % (r.get("fenetre_actions_j", 0), r.get("fenetre_vitals_j", 0),
                 r.get("abstentions_appariables", "?")))
        print("  episodes : %s au total, %s a pression connue"
              % (r.get("episodes_total", "?"), r.get("episodes_apparies", "?")))
        for w, b in sorted(r.get("fenetres", {}).items(), key=lambda x: int(x[0])):
            print("  W=%5ss  observe %5.1f%%  ratio %4s  IC95 %s  n=%d  -> %s"
                  % (w, b["observe_pct"], b.get("ratio_median", "-"),
                     b.get("ic95", "-"), b["n"],
                     "conclut" if b.get("conclut") else "IC contient 1"))
        print("\n  verdict : %s" % r.get("verdict", "?"))
        print("  %s" % r.get("avertissement", ""))
        return 0

    ev = journal()
    if not ev:
        print("journal VIDE ou injoignable - je ne peux pas voir, ce n'est pas « tout va bien ».")
        return 2

    if args.cible:
        action, _, cible = args.cible.partition("/")
        res = [cadence(action, cible, evenements=ev)]
    else:
        res = verdicts(ev)
        if not args.tout:
            res = [r for r in res if r["verdict"] != "HORS PERIMETRE"]

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print("EFFICACITE DE LA REGULATION - debit REEL vs budget par gravite")
    print("=" * 92)
    print("%-32s %-18s %8s %8s %6s %s"
          % ("action / cible", "verdict", "rafale/h", "budget/h", "recid", "dernier"))
    print("-" * 92)
    for r in res:
        age = r.get("dernier_il_y_a_s")
        print("%-32s %-18s %8s %8.1f %6s %s"
              % (("%s/%s" % (r["action"], r["cible"]))[:32],
                 r["verdict"],
                 ("%.1f" % r["debit_rafale_par_heure"]) if r.get("debit_rafale_par_heure") else "-",
                 r["budget_par_heure"],
                 r.get("recidive_fenetre", "-"),
                 ("il y a %.1f h" % (age / 3600.0)) if age else "-"))
    pompe = [r for r in res if r["verdict"] == "POMPE"]
    if pompe:
        print("\nEFFECTEURS QUI POMPENT :")
        for r in pompe:
            print("  ! %s/%s - %s" % (r["action"], r["cible"], r["pourquoi"]))
            if r.get("volume_total_go"):
                print("      %s Go deplaces au total pour ce seul effecteur"
                      % r["volume_total_go"])
    sans = [r for r in res if r["verdict"] == "SANS MESURE"]
    if sans:
        print("\n%d effecteur(s) SANS MESURE - trop peu de tirs pour conclure. "
              "Ce n'est pas un satisfecit." % len(sans))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
