#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_regulation_loops.py — DEBIT MAXIMAL DE CASSE des effecteurs, confronte a
un budget par gravite.

__FORGE_COLOR__ = "vegetatif/anti-oscillation"

POURQUOI CE MODULE (et pourquoi il ne duplique rien)
----------------------------------------------------
Recon anti-dup 2026-07-26 :
  - `forge_inspector.ACTION_MATRIX` porte DEJA {action:{threshold,cooldown,safe}}
    applique par `_react()` (triple confirmation + cooldown). On le LIT.
  - `forge_auto_pilot._can_act(key, cooldown)` porte l'anti-repetition.
  - `forge_embed_router` porte un circuit breaker (3 echecs / 60 s).
  - `tools/forge_epistemic_simulator.py` = decroissance de confiance EPISTEMIQUE
    des chunks RAG. Autre domaine, intouche.
Ce qui MANQUAIT : les effecteurs VIOLENTS (kill, `wsl --shutdown`, evict, stop de
service) vivent hors de ces tables, chacun avec sa garde bricolee — ou sans garde —
et RIEN ne confrontait la violence d'un remede a sa frequence autorisee.

DEUX CRITERES ESSAYES ET REFUTES (garder la trace evite de les re-essayer)
-------------------------------------------------------------------------
1. Simulation temporelle discrete. ECHOUE sa propre validation : elle supposait que
   les echecs ne s'accumulent que pendant le contrecoup, ce qui ne peut pas produire
   la periode mesuree.
2. « garde >= fenetre_detection + recovery => stable ». REFUTE par la mesure : la
   variante d'avant correctif avait garde=120 s pour un requis de 102 s, donc
   declaree stable — alors qu'elle a tire TROIS fois a ~133 s d'intervalle le
   2026-07-26. Lecon : **un cooldown n'empeche pas l'oscillation, il en fixe la
   periode.** Ce qui arrete une oscillation, c'est que le remede guerisse vraiment
   la plainte du capteur — propriete EMPIRIQUE, pas arithmetique.

LE CRITERE QUI SURVIT
---------------------
Ce que les constantes permettent d'affirmer avec certitude, c'est une BORNE :

    intervalle_min = max(fenetre_detection, cooldown_relance, refractaire)
    debit_max      = 3600 / intervalle_min          (declenchements par heure)

Puis une regle de proportionnalite : plus un remede est destructeur, plus son debit
autorise doit etre bas. Un `wsl --shutdown` n'a rien a faire 12 fois par heure.
Budget par gravite -> SEVERITY_BUDGET_PER_HOUR. Un effecteur au-dessus de son budget
est en VIOLATION, avec la refractaire minimale a poser.

Note biologique : c'est le principe de la periode refractaire (frequence maximale de
decharge), pas celui de l'homeostasie. On ne prouve pas que la boucle converge ; on
garantit qu'elle ne peut pas tetaniser.

COUT SYSTEME
------------
Zero resident : aucun daemon, aucun thread, aucune dependance. Comparaisons
arithmetiques a la demande.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Debit maximal tolere selon la violence du remede (declenchements/heure).
SEVERITY_BUDGET_PER_HOUR = {
    "critical": 2.0,    # reset WSL, kill de tous les process d'un moteur
    "high": 6.0,        # kill de workers, eviction memoire
    "medium": 12.0,     # restart d'un service
    "low": 60.0,        # skip non destructif, kill d'un zombie isole
}

VALIDATE_TOLERANCE_S = 15.0
# Periode MESUREE le 2026-07-26 (boots 13:56:09 / 13:58:24 / 14:00:35).
MEASURED_DOCKER_SAWTOOTH_S = 133.0


# ── Urgence lue sur le corps (aucun capteur ajoute) ──────────────────────────
def _published_state() -> dict:
    """Etat publie par l'echantillonneur. On LIT, on ne sonde pas."""
    try:
        return json.loads((ROOT / "sandbox" / "resource_state.json").read_text(
            encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return {}


def _slope_per_s(metric: str, window_s: float = 180.0):
    """Pente de la metrique (unite/s) sur la serie DEJA ecrite. None si la serie ne
    permet pas de conclure : on ne fabrique pas une pente a partir d'un point."""
    try:
        from nokido_agent.app import forge_resource_manager as rm
        rows = rm.read_vitals_history(since_ts=time.time() - window_s, limit=400)
    except Exception:  # noqa: BLE001
        return None
    pts = sorted((float(r["ts"]), float(r[metric])) for r in (rows or [])
                 if r.get("ts") and r.get(metric) is not None)
    if len(pts) < 3:
        return None
    dt = pts[-1][0] - pts[0][0]
    if dt < 20.0:
        return None
    return (pts[-1][1] - pts[0][1]) / dt


def body_urgency(metric: str = "ram_pct", setpoint: float = 85.0,
                 critical: float = 95.0, horizon_s: float = 120.0) -> dict:
    """Urgence dans [0,1], avec le detail de ce qui l'a produite.

        pression  = (niveau - consigne) / (critique - consigne)
        imminence = 1 - temps_avant_critique / horizon      (si la pente MONTE)
        urgence   = max(pression, imminence)

    L'imminence est le point clef : une RAM a 88 % qui DESCEND ne justifie aucun
    kill, la meme qui monte de 0,5 pt/s est une urgence. Le niveau seul est aveugle
    a cette difference — c'est pour cela qu'un cooldown fixe ne sert jamais.
    """
    st = _published_state()
    level = st.get(metric)
    out = {"metric": metric, "level": level, "setpoint": setpoint, "critical": critical,
           "state_age_s": (round(time.time() - float(st["ts"]), 1) if st.get("ts") else None)}
    if level is None:
        out.update({"urgency": None, "reason": "metrique absente de l'etat publie"})
        return out
    level = float(level)
    span = max(1e-6, critical - setpoint)
    pressure = max(0.0, min(1.0, (level - setpoint) / span))
    slope = _slope_per_s(metric)
    out["slope_per_s"] = round(slope, 4) if slope is not None else None
    imminence = 0.0
    if slope is None:
        out["trend"] = "pente non mesurable — seule la pression joue"
    elif slope > 0 and level < critical:
        ttc = (critical - level) / slope
        out["time_to_critical_s"] = round(ttc, 1)
        imminence = max(0.0, min(1.0, 1.0 - ttc / horizon_s))
    else:
        out["trend"] = "stable ou en baisse — l'imminence ne joue pas"
    out.update({"pressure": round(pressure, 3), "imminence": round(imminence, 3),
                "urgency": round(max(pressure, imminence), 3)})
    return out


@dataclass
class Loop:
    """Capteur -> remede -> cible. Chaque valeur vient d'une CONSTANTE du code cite
    par `source` ou d'une MESURE datee. Aucune estimation."""

    name: str
    sensor: str
    remedy: str
    tick_s: float
    threshold_ticks: int
    refractory_s: float
    launch_cooldown_s: float
    severity: str            # low | medium | high | critical
    source: str
    # Refractaire ABSOLUE : plancher dur, aucun stimulus ne passe. Elle ne sert
    # qu'a couvrir le CONTRECOUP du remede. C'est elle qui interdit la tetanie.
    # `refractory_s` joue le role de la refractaire RELATIVE : franchissable par
    # une urgence forte, et c'est elle qui borne le debit SOUTENU.
    absolute_refractory_s: float = 0.0
    urgency_metric: str | None = None   # None = pas de pilotage par urgence
    note: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def detection_window_s(self) -> float:
        return self.tick_s * max(1, self.threshold_ticks)

    @property
    def min_interval_s(self) -> float:
        return max(self.detection_window_s, self.launch_cooldown_s, self.refractory_s)

    @property
    def max_rate_per_hour(self) -> float:
        return 3600.0 / self.min_interval_s if self.min_interval_s > 0 else float("inf")

    def required_urgency(self, elapsed_s: float) -> float:
        """Exigence DECROISSANTE dans la fenetre relative : juste apres un tir il
        faut une urgence maximale, en fin de fenetre plus rien. inf = interdit."""
        if elapsed_s < self.absolute_refractory_s:
            return float("inf")
        span = self.refractory_s - self.absolute_refractory_s
        if span <= 0 or elapsed_s >= self.refractory_s:
            return 0.0
        return 1.0 - (elapsed_s - self.absolute_refractory_s) / span

    def should_fire(self, elapsed_s: float, urgency: float | None) -> dict:
        """Tir autorise <=> ecoule >= absolue ET urgence >= exigence(ecoule)."""
        if elapsed_s < self.absolute_refractory_s:
            return {"fire": False, "required": None, "urgency": urgency,
                    "reason": "refractaire ABSOLUE, %.0fs restantes"
                              % (self.absolute_refractory_s - elapsed_s)}
        req = self.required_urgency(elapsed_s)
        if urgency is None:
            return {"fire": req <= 0.0, "required": round(req, 3), "urgency": None,
                    "reason": "urgence non mesurable, seule la fin de fenetre autorise"}
        ok = urgency >= req
        return {"fire": ok, "required": round(req, 3), "urgency": urgency,
                "reason": "urgence %.2f %s exigence %.2f"
                          % (urgency, ">=" if ok else "<", req)}

    def verdict(self) -> dict:
        budget = SEVERITY_BUDGET_PER_HOUR.get(self.severity, 12.0)
        rate = self.max_rate_per_hour
        over = rate > budget
        return {
            "loop": self.name,
            "status": "VIOLATION" if over else "OK",
            "severity": self.severity,
            "detection_window_s": self.detection_window_s,
            "launch_cooldown_s": self.launch_cooldown_s,
            "absolute_refractory_s": self.absolute_refractory_s,
            "relative_refractory_s": self.refractory_s,
            "urgency_metric": self.urgency_metric,
            "min_interval_s": self.min_interval_s,
            "max_rate_per_hour": round(rate, 1),
            "budget_per_hour": budget,
            "refractory_required_s": round(3600.0 / budget, 0) if over else None,
            "remedy": self.remedy,
            "source": self.source,
        }


LOOPS: list[Loop] = [
    Loop(
        name="docker.force_recycle (AVANT correctif 26/07)",
        sensor="docker info (npipe dockerDesktopLinuxEngine)",
        remedy="taskkill /F tous process Docker + wsl --shutdown + relance",
        tick_s=30.0,                 # TICK_S
        threshold_ticks=3,           # STUCK_FAILS
        refractory_s=0.0,            # aucune — le defaut corrige
        launch_cooldown_s=120.0,     # _LAUNCH_COOLDOWN_S
        severity="critical",
        source="tools/forge_docker_keeper.py",
        note="variante historique = TEST de non-regression",
        tags=["historique", "validate"],
    ),
    Loop(
        name="docker.force_recycle",
        sensor="docker info (npipe dockerDesktopLinuxEngine)",
        remedy="taskkill /F tous process Docker + wsl --shutdown + relance",
        tick_s=30.0,
        threshold_ticks=3,
        refractory_s=1800.0,         # _FORCE_RECYCLE_REFRACTORY_S — porte a 1800 s
                                     # apres que CET audit ait condamne les 300 s
                                     # initiaux (12/h pour un budget de 2/h).
        launch_cooldown_s=120.0,
        absolute_refractory_s=60.0,  # boot MESURE ~12 s, marge x5
        severity="critical",
        source="tools/forge_docker_keeper.py",
        tags=["violent"],
    ),
    Loop(
        name="docker.release",
        sensor="docker.wanted expire + chains_active == 0",
        remedy="docker stop des conteneurs Nokido puis docker desktop stop",
        tick_s=30.0,                 # TICK_S
        threshold_ticks=1,
        absolute_refractory_s=60.0,
        refractory_s=1800.0,         # _RELEASE_REFRACTORY_S
        launch_cooldown_s=0.0,
        severity="medium",           # reversible : le keeper redemarre a la demande
        source="tools/forge_docker_keeper.py:_maybe_release",
        note="grace = WANT_TTL_S + RELEASE_GRACE_S = 1800 s apres la derniere demande, "
             "donc jamais dans le dos d'un consommateur qui vient de finir",
        tags=["release"],
    ),
    Loop(
        name="inspector.oom",
        sensor="psutil RAM",
        remedy="kill workers Python",
        tick_s=30.0,
        threshold_ticks=2,
        refractory_s=600.0,          # ACTION_MATRIX["oom"]["cooldown"] — porte de 120 a
                                     # 600 s le 2026-07-26 (decision owner : « eviter le
                                     # spam de processus »). 30 tirs/h -> 6/h = le budget.
                                     # La reactivite est preservee par l'override
                                     # d'urgence cable dans forge_inspector._urgency_allows.
        launch_cooldown_s=0.0,
        absolute_refractory_s=45.0,  # temps pour que la RAM retombe apres un kill —
                                     # A CONFIRMER par la mesure post-kill que
                                     # forge_orphan_reaper enregistre deja (delta_pt).
        urgency_metric="ram_pct",    # pilote par l'urgence VIVANTE (niveau + pente)
        severity="high",
        source="app/forge_inspector.py:ACTION_MATRIX",
        tags=["violent", "dynamique"],
    ),
    Loop(
        name="inspector.service_down",
        sensor="netstat port",
        remedy="nssm start hub",
        tick_s=30.0,
        threshold_ticks=3,
        refractory_s=300.0,
        launch_cooldown_s=0.0,
        severity="medium",
        source="app/forge_inspector.py:ACTION_MATRIX",
    ),
    Loop(
        name="inspector.zombie",
        sensor="inventaire PID/cmd",
        remedy="kill process zombie",
        tick_s=30.0,
        threshold_ticks=1,
        refractory_s=60.0,
        launch_cooldown_s=0.0,
        severity="low",
        source="app/forge_inspector.py:ACTION_MATRIX",
        tags=["violent"],
    ),
    Loop(
        name="embed_router.circuit_breaker",
        sensor="echec d'appel provider",
        remedy="ouvrir le circuit (skip provider)",
        tick_s=1.0,
        threshold_ticks=3,           # _CB_THRESHOLD
        refractory_s=60.0,           # _CB_COOLDOWN_S
        launch_cooldown_s=0.0,
        severity="low",
        source="app/forge_embed_router.py:_CB_THRESHOLD",
    ),
]


def audit(loops: list[Loop] | None = None) -> dict:
    rows = [lp.verdict() for lp in (loops or LOOPS)]
    return {
        "loops": rows,
        "violations": [r["loop"] for r in rows if r["status"] == "VIOLATION"],
        "ok": [r["loop"] for r in rows if r["status"] == "OK"],
        "budgets_per_hour": SEVERITY_BUDGET_PER_HOUR,
    }


def validate() -> dict:
    """Deux exigences sur la variante historique :
    1. elle doit ressortir en VIOLATION (sinon l'outil ne detecte pas la panne connue) ;
    2. son intervalle minimal doit encadrer la periode MESUREE a la tolerance pres.
    """
    hist = [lp for lp in LOOPS if "validate" in lp.tags]
    if not hist:
        return {"ok": False, "reason": "aucune boucle taggee validate"}
    v = hist[0].verdict()
    delta = abs(v["min_interval_s"] - MEASURED_DOCKER_SAWTOOTH_S)
    detected = v["status"] == "VIOLATION"
    return {
        "ok": bool(detected and delta <= VALIDATE_TOLERANCE_S),
        "panne_detectee": detected,
        "intervalle_min_calcule_s": v["min_interval_s"],
        "periode_mesuree_s": MEASURED_DOCKER_SAWTOOTH_S,
        "ecart_s": round(delta, 1),
        "tolerance_s": VALIDATE_TOLERANCE_S,
        "debit_max_par_heure": v["max_rate_per_hour"],
        "budget_par_heure": v["budget_per_hour"],
        "detail": "max(detection %.0fs, cooldown %.0fs, refractaire relative %.0fs)"
                  % (v["detection_window_s"], v["launch_cooldown_s"],
                     v["relative_refractory_s"]),
    }


def explain_dynamic(loop_name: str = "inspector.oom") -> dict:
    """Ce que la boucle decide MAINTENANT, avec l'urgence reelle du corps, selon le
    temps ecoule depuis son dernier tir."""
    hits = [lp for lp in LOOPS if loop_name.lower() in lp.name.lower()]
    if not hits:
        return {"error": "boucle inconnue: %s" % loop_name}
    lp = hits[0]
    u = body_urgency(lp.urgency_metric or "ram_pct")
    urg = u.get("urgency")
    return {
        "loop": lp.name,
        "urgence_mesuree": u,
        "absolute_refractory_s": lp.absolute_refractory_s,
        "relative_refractory_s": lp.refractory_s,
        "decisions": [dict(elapsed_s=e, **lp.should_fire(e, urg))
                      for e in (10.0, 60.0, 90.0, 110.0, 130.0)],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Debit maximal de casse des effecteurs vs budget.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--validate", action="store_true",
                    help="verifier la detection de la panne mesuree le 2026-07-26")
    ap.add_argument("--dynamic", metavar="LOOP", nargs="?", const="inspector.oom",
                    help="decision courante d'une boucle pilotee par l'urgence vivante")
    args = ap.parse_args()

    if args.dynamic:
        print(json.dumps(explain_dynamic(args.dynamic), ensure_ascii=False, indent=2))
        return 0

    if args.validate:
        v = validate()
        print(json.dumps(v, ensure_ascii=False, indent=2))
        return 0 if v.get("ok") else 1

    rep = audit()
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 1 if rep["violations"] else 0

    print("DEBIT MAXIMAL DE CASSE vs BUDGET PAR GRAVITE\n" + "=" * 78)
    for r in rep["loops"]:
        mark = "!!" if r["status"] == "VIOLATION" else "ok"
        print("  [%s] %-44s %-8s %5.1f/h  (budget %.1f/h)"
              % (mark, r["loop"][:44], r["severity"], r["max_rate_per_hour"], r["budget_per_hour"]))
        if r["status"] == "VIOLATION":
            print("       -> refractaire minimale a poser : %.0fs   remede : %s"
                  % (r["refractory_required_s"], r["remedy"][:44]))
    print("-" * 78)
    print("  VIOLATION %d | OK %d" % (len(rep["violations"]), len(rep["ok"])))
    return 1 if rep["violations"] else 0


def verifier_implementations(racine: Path | None = None) -> list[dict]:
    """Verifie que chaque Loop declaree a bien du CODE derriere elle.

    Motif paye le 2026-08-14 : ce catalogue declarait toujours
    `Loop(name="docker.release", source="tools/forge_docker_keeper.py")` six
    semaines apres que `3aec1500` en eut supprime l'implementation. Un
    catalogue qui survit a son code ne signale rien — il RASSURE. C'est le
    defaut symetrique du PUSH ZMQ vers un port ferme : l'emetteur est content,
    personne n'ecoute. Toute inspection de la regulation lisait ici que Docker
    se relachait, alors que la fonction n'existait plus.

    La docstring de `Loop` promet deja que chaque valeur vient d'une CONSTANTE
    du code cite par `source`. Cette fonction ne fait que rendre cette promesse
    VERIFIABLE, au lieu de la laisser a la bonne foi du redacteur.

    Rend la liste des ANOMALIES : vide = sain (jamais un booleen, pour que
    l'appelant puisse DIRE ce qui manque).
    """
    base = racine or ROOT
    anomalies: list[dict] = []
    for boucle in LOOPS:
        for morceau in boucle.source.replace(";", ",").split(","):
            morceau = morceau.strip()
            if ".py" not in morceau:
                continue
            # Convention DEJA en usage dans ce catalogue :
            # "app/forge_inspector.py:ACTION_MATRIX" — le symbole apres ':' est
            # la preuve attendue. Sans lui, on retombe sur le dernier segment du
            # `name`, nettoye : certains noms portent un commentaire
            # ("docker.force_recycle (AVANT correctif 26/07)") dont on ne garde
            # que l'identifiant.
            chemin, _, symbole = morceau.partition(".py:")
            chemin = chemin + ".py" if symbole else morceau
            if not symbole:
                brut = boucle.name.split(".")[-1]
                garde = ""
                for c in brut:            # premier identifiant, sans importer `re`
                    if c.isalnum() or c == "_":
                        garde += c
                    else:
                        break
                symbole = garde or brut
            f = base / chemin
            if not f.exists():
                anomalies.append({"loop": boucle.name, "source": chemin,
                                  "defaut": "SOURCE_ABSENTE"})
                continue
            if symbole not in f.read_text(encoding="utf-8", errors="replace"):
                anomalies.append({"loop": boucle.name, "source": chemin,
                                  "defaut": "IMPLEMENTATION_INTROUVABLE",
                                  "cherche": symbole})
    return anomalies


if __name__ == "__main__":
    sys.exit(main())
