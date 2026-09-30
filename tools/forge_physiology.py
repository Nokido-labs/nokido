#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_physiology.py — constantes physiologiques de l'organisme.

CADRAGE (etape A du pivot metabolisme, 2026-08-15). La critique du jour : Nokido
mesure « le code passe-t-il les tests ? » mais pas « sa capacite a s'autoreguler
s'est-elle amelioree ou degradee ? ». Ce module definit et CALCULE les premieres
constantes physiologiques -- deterministes, tirees de signaux DEJA enregistres
(`sandbox/vitals_history.jsonl`, 36 000+ lignes / ~16 jours a 15 s), jamais
inventees. Une constante qui se degrade est une regression COGNITIVE/CAPACITAIRE
au sens de la vision biomimetique, distincte d'un pytest rouge.

Regle appliquee : MESURER avant de cabler le learner (etape B). On prouve que ces
constantes sont reelles et calculables AVANT de construire l'organe qui les
optimise.

Les cinq constantes (chacune 0..1 sauf temps ; direction = sens du MIEUX) :
  homeostasis_stability  (haut=mieux) : 1 - dispersion de ram_pct. Un corps qui
      oscille peu se regule mieux. (Le RSS oscille -- mesure connue 2026-08-04.)
  resource_recovery_score(haut=mieux) : fraction des episodes de STRESS RAM
      (ram_pct >= HIGH) qui reviennent sous RELEASE dans la fenetre. « Revient-il
      a l'equilibre apres un choc ? »
  recovery_time_p50_s    (bas=mieux)  : mediane du temps de retour a l'equilibre.
  pressure_fraction      (bas=mieux)  : part du temps passe en pression RAM haute.
  cpu_calm               (haut=mieux) : 1 - part du temps a CPU sature.

INDETERMINE, jamais un faux chiffre : pas de serie -> None ; zero episode de
stress -> recovery = None (on ne fabrique ni 1.0 ni 0.0).

Usage :
    forge_physiology.py                 # affiche les constantes courantes
    forge_physiology.py --baseline      # fige la reference (constantes physiologiques)
    forge_physiology.py --check         # 0 stable / 1 degrade au-dela de tolerance / 2 indetermine
    forge_physiology.py --json
"""
from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/physiologie : constantes physiologiques de l'organisme"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIE = os.path.join(ROOT, "sandbox", "vitals_history.jsonl")
BASELINE = os.path.join(ROOT, "tests", "nr", "physiology_baseline.json")

# Fenetre par defaut : ~12 h a 15 s. On mesure la physiologie RECENTE, pas
# l'histoire ancienne. Baseline et check comparent deux instants du corps.
FENETRE = int(os.environ.get("LAFORGE_PHYSIO_WINDOW", "2880"))
HIGH, RELEASE = 85.0, 75.0          # seuils de stress / retour a l'equilibre RAM
CPU_SATURE = 85.0

# (sens_du_mieux, tolerance). Une constante n'est DEGRADEE que si elle bouge dans
# le sens du pire AU-DELA de la tolerance -- sinon le bruit naturel du corps
# (le RSS oscille) ferait crier le cliquet en permanence.
DIRECTIONS = {
    "homeostasis_stability": ("high", 0.10),
    "resource_recovery_score": ("high", 0.15),
    "recovery_time_p50_s": ("low", 120.0),
    "pressure_fraction": ("low", 0.10),
    "cpu_calm": ("high", 0.10),
}


def _lire_serie(fenetre: int) -> list[dict]:
    if not os.path.exists(SERIE):
        return []
    lignes: list[str] = []
    with open(SERIE, encoding="utf-8", errors="replace") as fh:
        for ligne in fh:
            ligne = ligne.strip()
            if ligne:
                lignes.append(ligne)
    rows = []
    for ligne in lignes[-fenetre:]:
        try:
            rows.append(json.loads(ligne))
        except json.JSONDecodeError:
            continue
    return rows


def _stabilite(rows: list[dict]) -> float | None:
    vals = [r.get("ram_pct") for r in rows if isinstance(r.get("ram_pct"), (int, float))]
    if len(vals) < 4:
        return None
    ecart = statistics.pstdev(vals)
    # normalise : un ecart-type de 20 points de % est deja tres instable.
    return round(max(0.0, 1.0 - ecart / 20.0), 3)


def recovery_episodes(rows: list[dict]) -> list[dict]:
    """Un episode par franchissement de HIGH. Detail : t0, ETAT au declenchement
    (ram/cpu), pic RAM, recupere (retour sous RELEASE), temps de retour. Source
    UNIQUE de detection d'episode, reutilisee par _recovery (agregat) et par le
    regulation-learner (qui cle son apprentissage sur l'etat -- etape #1)."""
    ts = [r.get("ts") for r in rows]
    ram = [r.get("ram_pct") for r in rows]
    cpu = [r.get("cpu_pct") for r in rows]
    episodes: list[dict] = []
    i, n = 0, len(rows)
    while i < n:
        if isinstance(ram[i], (int, float)) and ram[i] >= HIGH:
            debut = ts[i]
            pic = ram[i]
            cpu0 = cpu[i] if isinstance(cpu[i], (int, float)) else None
            j = i + 1
            revenu = None
            while j < n:
                if isinstance(ram[j], (int, float)):
                    pic = max(pic, ram[j])
                    if ram[j] < RELEASE:
                        revenu = ts[j]
                        break
                j += 1
            episodes.append({
                "t0": debut,
                "ram_at_trigger": round(ram[i], 1),
                "cpu_at_trigger": round(cpu0, 1) if cpu0 is not None else None,
                "ram_peak": round(pic, 1),
                "recovered": revenu is not None,
                "recovery_s": (round(revenu - debut, 1)
                               if revenu is not None and isinstance(debut, (int, float))
                               else None),
            })
            i = j  # sauter jusqu'a la sortie de l'episode
        else:
            i += 1
    return episodes


def _recovery(rows: list[dict]) -> tuple[float | None, float | None]:
    """(score, temps_p50). None si aucun episode (surtout pas 0.0 ou 1.0)."""
    eps = recovery_episodes(rows)
    if not eps:
        return None, None
    temps = [e["recovery_s"] for e in eps if e["recovered"] and e["recovery_s"] is not None]
    score = round(sum(1 for e in eps if e["recovered"]) / len(eps), 3)
    p50 = round(statistics.median(temps), 1) if temps else None
    return score, p50


def _pressure_fraction(rows: list[dict]) -> float | None:
    vals = [r.get("ram_pct") for r in rows if isinstance(r.get("ram_pct"), (int, float))]
    if not vals:
        return None
    return round(sum(1 for v in vals if v >= HIGH) / len(vals), 3)


def _cpu_calm(rows: list[dict]) -> float | None:
    vals = [r.get("cpu_pct") for r in rows if isinstance(r.get("cpu_pct"), (int, float))]
    if not vals:
        return None
    return round(1.0 - sum(1 for v in vals if v >= CPU_SATURE) / len(vals), 3)


def constantes(fenetre: int = FENETRE) -> dict:
    rows = _lire_serie(fenetre)
    if len(rows) < 4:
        return {"echantillons": len(rows), "constantes": {}, "indetermine": True}
    rec, p50 = _recovery(rows)
    return {
        "echantillons": len(rows),
        "constantes": {
            "homeostasis_stability": _stabilite(rows),
            "resource_recovery_score": rec,
            "recovery_time_p50_s": p50,
            "pressure_fraction": _pressure_fraction(rows),
            "cpu_calm": _cpu_calm(rows),
        },
    }


def _verdict(courant: dict) -> tuple[int, dict]:
    try:
        with open(BASELINE, encoding="utf-8") as fh:
            ref = json.load(fh).get("constantes", {})
    except (OSError, json.JSONDecodeError) as exc:
        return 3, {"etat": "INDETERMINE", "raison": f"baseline illisible ({exc})"}
    if courant.get("indetermine"):
        return 3, {"etat": "INDETERMINE", "raison": "serie vitals trop courte"}
    cur = courant["constantes"]
    degrades = []
    for cle, (sens, tol) in DIRECTIONS.items():
        a, b = ref.get(cle), cur.get(cle)
        if a is None or b is None:  # une des deux mesures manque (0 episode...) : on ne juge pas
            continue
        if sens == "high" and b < a - tol:
            degrades.append({"constante": cle, "de": a, "a": b, "sens": "baisse"})
        elif sens == "low" and b > a + tol:
            degrades.append({"constante": cle, "de": a, "a": b, "sens": "hausse"})
    if degrades:
        return 1, {"etat": "DEGRADE", "degrades": degrades, "courant": cur}
    return 0, {"etat": "STABLE", "courant": cur}


def main() -> int:
    ap = argparse.ArgumentParser(description="Constantes physiologiques de l'organisme")
    ap.add_argument("--baseline", action="store_true", help="fige la reference")
    ap.add_argument("--check", action="store_true",
                    help="0 stable / 1 degrade / 2 indetermine")
    ap.add_argument("--window", type=int, default=FENETRE)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    courant = constantes(a.window)

    if a.baseline:
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w", encoding="utf-8") as fh:
            json.dump({"genere_par": "tools/forge_physiology.py --baseline",
                       "echantillons": courant.get("echantillons"),
                       "constantes": courant.get("constantes", {})},
                      fh, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"[physiologie] baseline ecrite ({courant.get('echantillons')} echantillons) : "
              f"{os.path.relpath(BASELINE, ROOT)}")
        for k, v in courant.get("constantes", {}).items():
            print(f"   {k:<26} {v}")
        return 0

    if a.check:
        code, rap = _verdict(courant)
        if a.json:
            print(json.dumps(rap, ensure_ascii=False, indent=2))
            return code
        print(f"[physiologie] {rap['etat']}")
        for d in rap.get("degrades", []):
            print(f"   DEGRADE  {d['constante']:<26} {d['de']} -> {d['a']} ({d['sens']})")
        if rap.get("raison"):
            print(f"   {rap['raison']}")
        return code

    if a.json:
        print(json.dumps(courant, ensure_ascii=False, indent=2))
        return 0
    print(f"[physiologie] {courant.get('echantillons')} echantillons")
    for k, v in courant.get("constantes", {}).items():
        print(f"   {k:<26} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
