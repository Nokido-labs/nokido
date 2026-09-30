# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "regulation/canaux-vitaux"
SONDE DES CANAUX VITAUX -- mesurer AVANT d'elargir le vecteur de capteurs.

POURQUOI
========
Le blocage mesure le 2026-08-04 n'est pas le modele mais le SIGNAL : quatre bancs
(LIF regle, tete lineaire, SpikingMLP entraine, noyau polynomial facon TENNs) ont
tous perdu contre `if ram > 85`, sur un vecteur de 4 scalaires globaux. Les TENNs
sont *spatio*temporels : leur force est la CORRELATION ENTRE CANAUX. Tant que la
serie n'a qu'un canal utile, le seuil gagne par construction.

Elargir au hasard couterait cher pour rien : mesure du 2026-07-28, 4 cablages sur 6
se sont reveles inutiles faute d'avoir mesure d'abord. Cette sonde tranche AVANT le
cablage : un canal n'entre dans la serie que s'il est (a) LISIBLE, (b) VARIABLE,
(c) BON MARCHE -- le sampler passe toutes les 15 s.

SOURCE UNIQUE
=============
Les canaux ne sont PAS definis ici : ils vivent dans `app/forge_vitals_channels.py`,
d'ou `forge_resource_manager` les journalise. Deux definitions du meme canal
divergeraient, et la sonde jugerait autre chose que ce qui tourne.

CE QUE LA SONDE REFUSE DE FAIRE
===============================
Conclure d'un silence. Trois etats par canal, jamais deux : `lisible` /
`illisible` (avec la RAISON) / `absent`. Un canal qui rend None parce que le compte
n'a pas le droit de lire le process n'est PAS un canal a zero -- le confondre
fabriquerait un faux negatif indetectable une fois dans la serie.

USAGE
=====
    LAFORGE_PYTHON tools/forge_vitals_channel_probe.py --n 10 --intervalle 15
    LAFORGE_PYTHON tools/forge_vitals_channel_probe.py --n 3 --intervalle 2 --json

Duree = n * intervalle : au-dela de 70 s, la lancer en `run_job` detache. Rapport
ecrit dans sandbox/vitals_channel_probe.json (etat vivant) et resume sur stdout.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from nokido_agent.app import forge_vitals_channels as CANAUX  # noqa: E402  (apres l'ajout de app/ au path)

SORTIE = ROOT / "sandbox" / "vitals_channel_probe.json"

# Un canal doit rester bon marche : le sampler passe 4x/minute et ne doit pas
# devenir lui-meme une charge. Seuil par GROUPE, en millisecondes.
COUT_MAX_MS = 60.0
# Moins de 3 valeurs distinctes = pas de dynamique a apprendre. Le canal peut
# rester utile comme drapeau evenementiel : le verdict le DIT au lieu de le jeter.
DISTINCT_MIN = 3


def _aplatir(vals: dict) -> dict:
    """La carte des services arrive sous une seule cle `s` (compacite de la serie).
    La sonde juge canal par canal : on l'ouvre en svc.<nom>.go / svc.<nom>.ratio."""
    plat = {}
    for k, v in vals.items():
        if k == "s" and isinstance(v, dict):
            for nom, paire in v.items():
                go, ratio = (paire + [None, None])[:2] if isinstance(paire, list) else (None, None)
                plat["svc.%s.go" % nom] = go
                plat["svc.%s.ratio" % nom] = ratio
        else:
            plat[CANAUX.SCHEMA.get(k, k)] = v
    return plat


def echantillonner(n: int, intervalle: float) -> dict:
    """N tours sur TOUS les paliers (serie + sonde), en mesurant le cout par groupe."""
    prev: dict = {}
    series: dict[str, list] = {}
    couts: dict[str, list] = {}
    notes: dict[str, str] = {}
    for i in range(n):
        for nom, (fn, palier) in CANAUX.GROUPES.items():
            t0 = time.perf_counter()
            try:
                vals, note = fn(prev)
            except Exception as e:  # noqa: BLE001
                vals, note = {}, "EXCEPTION %s: %s" % (type(e).__name__, str(e)[:80])
            couts.setdefault(nom, []).append((time.perf_counter() - t0) * 1000.0)
            notes[nom] = "[palier %s] %s" % (palier, note)
            for k, v in _aplatir(vals).items():
                series.setdefault("%s|%s" % (nom, k), []).append(v)
        if i < n - 1:
            time.sleep(intervalle)
    return {"series": series, "couts": couts, "notes": notes}


def _couts_froid_chaud(mesures: list) -> tuple[float, float]:
    """Separe le PREMIER appel (imports a froid) du regime etabli. Sans cette
    separation, le smoke test du 2026-08-05 attribuait 7 435 ms au groupe cognitif
    alors que le prix paye 4x/minute est celui du regime etabli -- et inversement,
    un import lent reste un cout REEL au demarrage : on garde les deux."""
    if not mesures:
        return 0.0, 0.0
    froid = mesures[0]
    chaud = statistics.median(mesures[1:]) if len(mesures) > 1 else froid
    return froid, chaud


def juger(brut: dict, n: int) -> dict:
    canaux = []
    for cle, vals in sorted(brut["series"].items()):
        groupe, nom = cle.split("|", 1)
        lus = [v for v in vals if v is not None]
        distinct = len(set(lus))
        froid, cout = _couts_froid_chaud(brut["couts"].get(groupe) or [])
        # Un canal de DEBIT (nom en _s) derive de deux compteurs : le premier
        # echantillon n'a pas de reference et rend None par CONCEPTION. Attendre
        # n lectures le classerait PARTIEL a tort a chaque campagne.
        attendu = (n - 1) if nom.endswith("_s") else n
        fiche = {
            "canal": nom,
            "groupe": groupe,
            "lus": len(lus),
            "sur": attendu,
            "distinct": distinct,
            "min": min(lus) if lus else None,
            "max": max(lus) if lus else None,
            "ecart_type": round(statistics.pstdev(lus), 4) if len(lus) > 1 else None,
            "cout_groupe_ms": round(cout, 2),
            "cout_froid_ms": round(froid, 2),
        }
        if not lus:
            fiche["verdict"] = "ILLISIBLE"
            fiche["raison"] = brut["notes"].get(groupe) or "aucune valeur"
        elif len(lus) < attendu:
            fiche["verdict"] = "PARTIEL"
            fiche["raison"] = "%d/%d lectures manquantes -- %s" % (
                attendu - len(lus), attendu, brut["notes"].get(groupe) or "")
        elif cout > COUT_MAX_MS:
            fiche["verdict"] = "TROP CHER"
            fiche["raison"] = "groupe a %.1f ms > %.0f ms" % (cout, COUT_MAX_MS)
        elif distinct < DISTINCT_MIN:
            fiche["verdict"] = "CONSTANT"
            fiche["raison"] = ("%d valeur(s) distincte(s) sur %d -- pas de dynamique a "
                               "apprendre ; utile seulement comme drapeau" % (distinct, n))
        else:
            fiche["verdict"] = "RETENIR"
        canaux.append(fiche)
    retenus = [c for c in canaux if c["verdict"] == "RETENIR"]
    return {
        "n_echantillons": n,
        "canaux": canaux,
        "resume": {
            "total": len(canaux),
            "retenir": len(retenus),
            "constant": sum(1 for c in canaux if c["verdict"] == "CONSTANT"),
            "illisible": sum(1 for c in canaux if c["verdict"] == "ILLISIBLE"),
            "partiel": sum(1 for c in canaux if c["verdict"] == "PARTIEL"),
            "trop_cher": sum(1 for c in canaux if c["verdict"] == "TROP CHER"),
            "cout_total_ms": round(sum(
                _couts_froid_chaud(v)[1] for v in brut["couts"].values()), 2),
            "cout_froid_total_ms": round(sum(
                _couts_froid_chaud(v)[0] for v in brut["couts"].values()), 2),
        },
        "couts_par_groupe": {
            g: {"froid_ms": round(_couts_froid_chaud(v)[0], 2),
                "chaud_ms": round(_couts_froid_chaud(v)[1], 2),
                "palier": CANAUX.GROUPES[g][1] if g in CANAUX.GROUPES else "?"}
            for g, v in sorted(brut["couts"].items())
        },
        "notes_groupes": brut["notes"],
        "palier_cable": list(CANAUX.PALIER_SERIE),
    }


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Mesure quels canaux meritent d'entrer dans la serie vitals")
    ap.add_argument("--n", type=int, default=10, help="nombre d'echantillons")
    ap.add_argument("--intervalle", type=float, default=15.0,
                    help="secondes entre echantillons (cadence du sampler)")
    ap.add_argument("--json", action="store_true", help="rapport JSON complet sur stdout")
    a = ap.parse_args(argv)

    debut = time.time()
    rapport = juger(echantillonner(a.n, a.intervalle), a.n)
    rapport["duree_s"] = round(time.time() - debut, 1)
    rapport["ts"] = round(debut, 1)
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps(rapport, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    except OSError as e:
        print("[probe] rapport non ecrit (%s)" % e, file=sys.stderr)

    if a.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0
    r = rapport["resume"]
    print("=== Canaux vitaux : %d echantillons / %.0f s ===" % (a.n, rapport["duree_s"]))
    print("total %d | RETENIR %d | CONSTANT %d | PARTIEL %d | ILLISIBLE %d | "
          "TROP CHER %d | cout/tick %.1f ms (a froid %.1f ms)"
          % (r["total"], r["retenir"], r["constant"], r["partiel"], r["illisible"],
             r["trop_cher"], r["cout_total_ms"], r["cout_froid_total_ms"]))
    print("cout par groupe (froid -> chaud) : " + " | ".join(
        "%s[%s] %.0f->%.0f" % (g, c["palier"], c["froid_ms"], c["chaud_ms"])
        for g, c in rapport["couts_par_groupe"].items()))
    print("deja cable dans la serie : " + ", ".join(rapport["palier_cable"]))
    for etat in ("RETENIR", "PARTIEL", "CONSTANT", "TROP CHER", "ILLISIBLE"):
        fiches = [c for c in rapport["canaux"] if c["verdict"] == etat]
        if not fiches:
            continue
        print("\n-- %s (%d)" % (etat, len(fiches)))
        for c in fiches:
            detail = ""
            if c["verdict"] == "RETENIR":
                detail = " [%s .. %s] sd=%s" % (c["min"], c["max"], c["ecart_type"])
            elif c.get("raison"):
                detail = " -- %s" % c["raison"]
            print("   %-34s %2d/%-2d distinct=%-3d%s"
                  % (c["canal"], c["lus"], c["sur"], c["distinct"], detail))
    print("\nrapport: %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
