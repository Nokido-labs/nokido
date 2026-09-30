"""Le flux RESEAU ajoute-t-il ce que les 4 scalaires n'ont pas ?

Trois bancs ont montre que rien ne bat le seuil sur les vitals : ni un LIF regle,
ni une tete lineaire apprise, ni le SpikingMLP de production entraine (perte finale
0,677 pour ln(2)=0,693 — il converge vers le hasard). Le verdict ne porte plus sur
l'architecture mais sur le SIGNAL : 4 scalaires toutes les 15 s ne contiennent pas
de quoi anticiper.

Avant de CABLER un capteur dense, on mesure s'il apporte. `network_log` compte
257 000 evenements (~7/min) avec latence, statut, outil, agent, ring — c'est le
seul flux dense dont Nokido dispose. La question posee ici, et une seule :

    a cible identique et protocole identique, ajouter les traits RESEAU aux traits
    VITALS fait-il gagner quelque chose ?

Trois modeles compares sur la MEME periode de test :
    vitals seuls · reseau seul · vitals + reseau
Si « vitals + reseau » ne bat pas « vitals seuls », le flux dense n'apporte pas
pour cette cible, et il faut le dire plutot que de le cabler par principe.

Garde-fous inchanges : split TEMPOREL, seuil choisi sur le TRAIN, temoin sur la
meme periode, faux positifs rapportes a cote de la couverture, classe positive
ponderee.

Piege de jointure a ne pas rater : `network_log.ts` est du TEXTE ISO en heure
LOCALE, `vitals.ts` un epoch. Melanger les deux decalerait tout de deux heures et
produirait une correlation nulle qu'on lirait comme « le reseau n'apporte rien ».

Usage :
    run action=run_job script=tools/forge_capteur_dense_apport_bench.py
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/meta-evaluation"

import argparse
import datetime as _dt
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app.forge_db_path import db_path  # noqa: E402
from nokido_agent.app.forge_resource_manager import read_vitals_history  # noqa: E402
from nokido_agent.tools.forge_snn_vitals_baseline import episodes_detresse  # noqa: E402
from nokido_agent.tools.forge_tenns_multicanal_bench import (  # noqa: E402
    REFRACTAIRE_S, cibles, entrainer, evaluer, proba, tirs_depuis_scores,
    tirs_temoin, traits,
)

FENETRE_RESEAU_S = 300.0  # 5 min glissantes


def charger_reseau() -> list[tuple[float, float, int]]:
    """[(epoch, latency_ms, est_erreur)] — ts LOCAL converti en epoch."""
    con = sqlite3.connect(db_path(), timeout=20)
    try:
        rows = con.execute(
            "SELECT ts, latency_ms, status FROM network_log "
            "WHERE ts >= '2026-07-26' ORDER BY ts"
        ).fetchall()
    finally:
        con.close()
    out = []
    for ts, lat, statut in rows:
        try:
            e = _dt.datetime.fromisoformat(str(ts)).timestamp()
        except Exception:
            continue
        out.append((e, float(lat) if lat is not None else -1.0,
                    1 if (statut or "").startswith("ERR") else 0))
    return out


def traits_reseau(ts_cibles: list[float], evts: list[tuple[float, float, int]],
                  fenetre: float) -> list[list[float]]:
    """Par instant cible : debit, latence moyenne, latence max, taux d'erreur.

    Deux pointeurs sur des listes triees : O(n+m), pas de jointure quadratique.
    """
    res: list[list[float]] = []
    i_debut = i_fin = 0
    n = len(evts)
    for t in ts_cibles:
        while i_fin < n and evts[i_fin][0] <= t:
            i_fin += 1
        while i_debut < i_fin and evts[i_debut][0] < t - fenetre:
            i_debut += 1
        tranche = evts[i_debut:i_fin]
        if not tranche:
            res.append([0.0, 0.0, 0.0, 0.0])
            continue
        lats = [l for _e, l, _x in tranche if l >= 0]
        err = sum(x for _e, _l, x in tranche)
        res.append([
            len(tranche) / (fenetre / 60.0),                    # appels/min
            (sum(lats) / len(lats) / 1000.0) if lats else 0.0,  # latence moy (s)
            (max(lats) / 1000.0) if lats else 0.0,              # latence max (s)
            err / len(tranche),                                 # taux d'erreur
        ])
    return res


def mesurer(nom, Xall, y, ts, tr, te, eps, alerte, rapport) -> dict:
    Xtr, ytr = [Xall[i] for i in tr], [y[i] for i in tr]
    w, b = entrainer(Xtr, ytr)
    t_tr = [ts[i] for i in tr]
    s_tr = [proba(w, b, Xall[i]) for i in tr]
    seuil, fp_min = None, None
    for s in [i / 100.0 for i in range(20, 96, 5)]:
        r = evaluer(tirs_depuis_scores(t_tr, s_tr, s, REFRACTAIRE_S),
                    eps, t_tr[0], t_tr[-1], alerte)
        if r["episodes_test"] and r["episodes_vus"] == r["episodes_test"]:
            if fp_min is None or r["faux_positifs"] < fp_min:
                fp_min, seuil = r["faux_positifs"], s
    if seuil is None:
        seuil = 0.5
    t_te = [ts[i] for i in te]
    s_te = [proba(w, b, Xall[i]) for i in te]
    r = evaluer(tirs_depuis_scores(t_te, s_te, seuil, REFRACTAIRE_S),
                eps, t_te[0], t_te[-1], alerte)
    r["seuil_train"] = seuil
    r["traits"] = len(Xall[0])
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="Apport du flux reseau")
    ap.add_argument("--fenetre-n", type=int, default=10)
    ap.add_argument("--horizon", type=float, default=1800.0)
    ap.add_argument("--alerte", type=float, default=3600.0)
    ap.add_argument("--fenetre-reseau", type=float, default=FENETRE_RESEAU_S)
    args = ap.parse_args()

    t0 = time.time()
    hist = read_vitals_history(0.0, 10**9)
    eps = episodes_detresse(hist)
    ts, Xv = traits(hist, args.fenetre_n)
    y = cibles(ts, eps, args.horizon)
    evts = charger_reseau()
    rapport: dict = {"vitals": len(hist), "traits_vitals": len(Xv[0]) if Xv else 0,
                     "evenements_reseau": len(evts), "episodes": len(eps),
                     "fenetre_reseau_s": args.fenetre_reseau}
    if not evts:
        rapport["verdict"] = ("MESURE IMPOSSIBLE : aucun evenement reseau lu — "
                              "ne pas lire ce vide comme « le reseau n'apporte rien »")
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    Xr = traits_reseau(ts, evts, args.fenetre_reseau)
    couverts = sum(1 for x in Xr if any(v != 0.0 for v in x))
    rapport["instants_avec_trafic_pct"] = round(100.0 * couverts / max(1, len(Xr)), 1)

    coupe = ts[int(len(ts) * 0.6)]
    tr = [i for i, t in enumerate(ts) if t <= coupe]
    te = [i for i, t in enumerate(ts) if t > coupe]
    if sum(y[i] for i in tr) < 10:
        rapport["verdict"] = "PAS ASSEZ D'EPISODES DANS LE TRAIN"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    Xvr = [a + b for a, b in zip(Xv, Xr)]
    rapport["vitals_seuls"] = mesurer("vitals", Xv, y, ts, tr, te, eps, args.alerte, rapport)
    rapport["reseau_seul"] = mesurer("reseau", Xr, y, ts, tr, te, eps, args.alerte, rapport)
    rapport["vitals_plus_reseau"] = mesurer("v+r", Xvr, y, ts, tr, te, eps, args.alerte, rapport)
    t_te = [ts[i] for i in te]
    rapport["temoin_seuil"] = evaluer(tirs_temoin(hist, REFRACTAIRE_S), eps,
                                      t_te[0], t_te[-1], args.alerte)
    rapport["duree_s"] = round(time.time() - t0, 1)
    rapport["lecture"] = (
        "Comparer vitals_plus_reseau a vitals_seuls : c'est le seul ecart qui "
        "mesure l'APPORT du flux dense. S'il est nul ou negatif, cabler un capteur "
        "reseau n'aiderait pas pour CETTE cible — le dire au lieu de le cabler par "
        "principe. Et comparer les trois au temoin : un modele qui ne bat meme pas "
        "un `if ram > 85` ne merite pas d'aller en production."
    )
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
