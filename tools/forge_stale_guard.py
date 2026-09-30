#!/usr/bin/env python3
"""forge_stale_guard.py — un pouls perime, mesure sur le rythme DECLARE.

Un heartbeat vieux de 18 minutes n'est pas un defaut : `rss_watcher` declare
`interval_s = 21600`, il bat toutes les six heures. Le juger sur un seuil unique
de 300 s — le reflexe — l'aurait accuse a tort, comme il aurait absous un
`biblio_worker` (interval 30 s) muet depuis 4 minutes. Un seuil unique sur des
organes de rythmes differents ne mesure rien : il produit du bruit d'un cote et
de la cecite de l'autre.

D'ou la regle : chaque service est juge sur SON `interval_s`, et STALE signifie
« trois cycles manques ». Trois, pas un — un cycle rate arrive (charge, I/O),
trois d'affilee est un silence.

Quatre verdicts, jamais deux :
  VIVANT              bat dans les temps
  STALE               trois cycles manques -> le service est fige ou mort
  RYTHME_NON_DECLARE  le heartbeat n'annonce pas sa periode : INJUGEABLE. On ne
                      l'appelle pas sain pour autant — absence de mesure n'est
                      pas succes. C'est un defaut du service, a corriger la-bas.
  DORMANT             aucun battement depuis plus de 7 jours et pas de periode :
                      arret assume (on-demand), pas une panne.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
CYCLES_TOLERES = 3
DORMANT_S = 7 * 24 * 3600


def _periode(donnees: dict) -> float | None:
    for cle in ("interval_s", "tick_s", "period_s", "interval", "tick"):
        v = donnees.get(cle)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def scanner(base: Path | None = None) -> list[dict]:
    """`base` permet de viser un repertoire d'essai : un garde dont le verdict
    ne peut s'observer que sur l'etat vivant de la machine n'est pas verifiable,
    donc pas fiable."""
    out: list[dict] = []
    maintenant = time.time()
    for h in sorted((base or SANDBOX).glob("*.heartbeat")):
        try:
            age = maintenant - h.stat().st_mtime
            brut = h.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            out.append({"service": h.stem, "verdict": "ILLISIBLE",
                        "motif": type(e).__name__})
            continue
        try:
            donnees = json.loads(brut)
            donnees = donnees if isinstance(donnees, dict) else {}
        except json.JSONDecodeError:
            donnees = {}
        p = _periode(donnees)
        fiche = {"service": h.stem, "age_s": round(age),
                 "age_lisible": f"{age/60:.1f} min" if age < 7200 else f"{age/3600:.1f} h",
                 "periode_s": p}
        if p is not None:
            fiche["verdict"] = "STALE" if age > CYCLES_TOLERES * p else "VIVANT"
            fiche["cycles_manques"] = round(age / p, 1)
        elif age > DORMANT_S:
            fiche["verdict"] = "DORMANT"
        else:
            fiche["verdict"] = "RYTHME_NON_DECLARE"
        out.append(fiche)
    ordre = {"STALE": 0, "RYTHME_NON_DECLARE": 1, "ILLISIBLE": 2,
             "DORMANT": 3, "VIVANT": 4}
    return sorted(out, key=lambda f: (ordre.get(f["verdict"], 9), -f["age_s"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    fiches = scanner()
    if a.json:
        print(json.dumps(fiches, ensure_ascii=False, indent=2))
        return 0
    compte: dict[str, int] = {}
    for f in fiches:
        compte[f["verdict"]] = compte.get(f["verdict"], 0) + 1
    print(f"[stale] {len(fiches)} heartbeats — " +
          " · ".join(f"{k}={v}" for k, v in sorted(compte.items())))
    for f in fiches:
        if f["verdict"] == "VIVANT":
            continue
        detail = (f"{f['cycles_manques']} cycles (periode {f['periode_s']:.0f} s)"
                  if f.get("cycles_manques") else "periode inconnue")
        print(f"   {f['verdict']:20s} {f['service']:32s} {f['age_lisible']:>10s}  {detail}")
    # Le code de retour ne parle QUE du defaut ferme : un rythme non declare est
    # une dette de conception, pas une panne, et le confondre banaliserait l'un
    # ou paniquerait sur l'autre.
    return 1 if compte.get("STALE") else 0


if __name__ == "__main__":
    sys.exit(main())
