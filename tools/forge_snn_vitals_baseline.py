"""Baseline : un LIF integrateur detecte-t-il la detresse RAM plus TOT qu'un seuil ?

Question. `forge_snn_monitor` tourne aujourd'hui en mode SEUIL (snnTorch absent :
`enabled=False`), avec `_THRESHOLDS['ram']=0.85` et 60 s de refractaire. Or la
machine vit entre 75 et 83 % et le gel du 2026-08-02 est monte a 99,3 % : un seuil
a 85 % se declenche tard, quand la marge est deja mangee. Un LIF, lui, INTEGRE —
une montee soutenue sous le seuil charge la membrane et finit par emettre. C'est
cette avance-la qu'on mesure, sur des donnees REELLES.

Donnees : `forge_resource_manager.read_vitals_history()` — 30 122 echantillons du
26/07 au 04/08, l'episode de gel inclus. Aucun jeu synthetique.

Verite terrain, empruntee au corps et non inventee : la DETRESSE VITALE telle que
`forge_resource_manager` la definit lui-meme, `0 < ram_free_gb < 1.5`. Les
echantillons consecutifs sont groupes en episodes (coupure au-dela de 5 min).

Ce qui est mesure, pour CHAQUE detecteur :
  - `avance_s` : combien de secondes AVANT le debut d'un episode il a emis ;
  - `episodes_vus` : combien d'episodes il a annonces (dans la fenetre d'alerte) ;
  - `faux_positifs_par_jour` : ses emissions hors de toute fenetre d'episode.
Un detecteur qui gagne en avance en criant sans cesse n'a rien gagne — les deux
chiffres se lisent ENSEMBLE, sinon la mesure flatte celui qui spike le plus.

Honnetete d'implementation : le LIF est ici une reimplementation SCALAIRE de
l'equation de `forge_snn_core.LIFCell` (`mem = beta*mem + I`, spike si `mem>thr`,
reset soustractif), et non l'objet torch. Raison : rejouer un historique demande
un temps SIMULE et aucun autograd. Les seuils du detecteur temoin, eux, sont
IMPORTES de `forge_snn_monitor` — pas recopies : si le corps change ses seuils,
la comparaison suit.

Usage :
    run action=run_job script=tools/forge_snn_vitals_baseline.py
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/meta-evaluation"

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app.forge_resource_manager import read_vitals_history  # noqa: E402
from nokido_agent.app.forge_snn_monitor import _REFRACTORY_S, _SNN_GAIN as _SNN_GAIN_INITIAL, _THRESHOLDS  # noqa: E402

# Seuil de detresse du corps lui-meme (forge_resource_manager,
# LAFORGE_DETRESSE_LIBRE_GB). On ne fabrique pas notre propre definition.
DETRESSE_LIBRE_GB = 1.5
COUPURE_EPISODE_S = 300.0   # au-dela, deux episodes distincts
# Fenetre d'alerte : au-dela, une emission n'a rien "annonce". Mesure 2026-08-04 :
# avec 900 s, TOUS les reglages rendaient une avance_max de 897-899 s — la borne
# elle-meme etait mesuree, pas les detecteurs. Elargie et rendue reglable ;
# `avance_saturee` signale le cas ou l'artefact reviendrait.
FENETRE_ALERTE_S = 3600.0


def episodes_detresse(hist: list[dict]) -> list[tuple[float, float]]:
    """Rend [(debut_ts, fin_ts)] des episodes de detresse RAM reelle."""
    eps: list[tuple[float, float]] = []
    debut = fin = None
    for r in hist:
        libre = r.get("ram_free_gb")
        ts = float(r.get("ts") or 0)
        # Trois etats : une valeur absente n'est PAS une detresse (cf. le meme
        # raisonnement dans forge_resource_manager).
        en_detresse = libre is not None and 0.0 < float(libre) < DETRESSE_LIBRE_GB
        if en_detresse:
            if debut is None:
                debut = fin = ts
            elif ts - fin > COUPURE_EPISODE_S:
                eps.append((debut, fin))
                debut = fin = ts
            else:
                fin = ts
        # un echantillon sain n'interrompt pas : c'est la COUPURE qui tranche
    if debut is not None:
        eps.append((debut, fin))
    return eps


def detecteur_seuil(hist: list[dict]) -> list[float]:
    """Reproduit le mode actuel de forge_snn_monitor, en temps SIMULE."""
    seuil = _THRESHOLDS["ram"]
    dernier = -1e18
    tirs: list[float] = []
    for r in hist:
        v = r.get("ram_pct")
        ts = float(r.get("ts") or 0)
        if v is None:
            continue
        if (float(v) / 100.0) >= seuil and (ts - dernier) >= _REFRACTORY_S:
            tirs.append(ts)
            dernier = ts
    return tirs


def detecteur_lif(hist: list[dict], beta: float, thr: float) -> list[float]:
    """LIF scalaire : mem = beta*mem + entree ; spike si mem > thr ; reset soustractif.

    L'entree est le ratio charge/seuil, comme dans forge_snn_monitor : a 85 % de
    RAM l'entree vaut 1.0. Une charge SOUS le seuil charge donc quand meme la
    membrane, lentement — c'est tout l'interet par rapport a une comparaison.
    """
    seuil = _THRESHOLDS["ram"]
    mem = 0.0
    dernier = -1e18
    tirs: list[float] = []
    for r in hist:
        v = r.get("ram_pct")
        ts = float(r.get("ts") or 0)
        if v is None:
            continue
        mem = beta * mem + (float(v) / 100.0) / seuil
        if mem > thr:
            mem -= thr  # reset soustractif
            if (ts - dernier) >= _REFRACTORY_S:
                tirs.append(ts)
                dernier = ts
    return tirs


def _backend_prod() -> str:
    """Backend REELLEMENT charge par le capteur de prod dans cet interpreteur."""
    from nokido_agent.app.forge_snn_monitor import SNNMonitor

    return "snntorch" if SNNMonitor().enabled else "repli-seuil"


def detecteur_monitor_prod(hist: list[dict], gain: float | None = None) -> list[float]:
    """Le chemin de PRODUCTION lui-meme, rejoue — pas une reimplementation.

    `detecteur_lif` ci-dessus simule l'entree `v/100/seuil`, qui etait celle du
    capteur JUSQU'AU 2026-08-28 : strictement positive, donc le Leaky integrait
    toute mesure et finissait par tirer sur des vitaux normaux. Elle est devenue
    l'ECART AU SEUIL (nul en dessous). Les deux fonctions ne mesurent donc plus la
    meme chose, et c'est le point : la simulation garde la trace de l'ancien
    reglage, celle-ci mesure ce qui tourne.

    L'horloge de l'historique est passee a `feed(..., now=ts)` — sans quoi le
    refractaire courrait en temps mural et le rejeu rendrait un seul tir.
    """
    import importlib
    import os as _os

    from nokido_agent.app import forge_snn_monitor as _mod

    if gain is not None:
        # `_SNN_GAIN` est fige a l'import : balayer le reglage EXIGE un reload,
        # sinon les N passes mesurent toutes le meme gain et la grille ment.
        _os.environ["FORGE_SNN_GAIN"] = str(gain)
        _mod = importlib.reload(_mod)
    mon = _mod.SNNMonitor()
    tirs: list[float] = []
    for r in hist:
        v = r.get("ram_pct")
        ts = float(r.get("ts") or 0)
        if v is None:
            continue
        spikes = mon.feed(
            {"ram_pct": float(v), "cpu_pct": r.get("cpu_pct"), "gpu_pct": r.get("gpu_pct")},
            now=ts,
        )
        if spikes.get("ram"):
            tirs.append(ts)
    return tirs


def detecteur_polynomial(hist: list[dict], fenetre_n: int, seuil_pente: float,
                         refractaire: float) -> list[float]:
    """Premier pas vers les TENNs : un noyau temporel POLYNOMIAL, pas un seuil.

    Principe emprunte a TENNs-PLEIADES (arXiv 2405.12179, ingere en RAG le
    2026-08-04) : au lieu d'apprendre un noyau temporel libre, on projette la
    fenetre sur une base de polynomes ORTHOGONAUX. Ici, la base de Legendre
    discrete d'ordre 1 sur une fenetre glissante — le coefficient obtenu est la
    TENDANCE (pente) du signal, independamment de son niveau.

    Ce que ca change : le detecteur actuel emet quand la RAM est HAUTE. Celui-ci
    emet quand elle MONTE. Une machine qui vit a 83 % de facon stable est saine ;
    la meme qui passe de 70 a 83 % en quelques minutes ne l'est pas. C'est cette
    distinction-la qu'un seuil ne peut pas faire, et c'est la seule ou un modele
    temporel peut encore gagner : la couverture est deja de 50/50 pour le seuil,
    donc le gain ne peut venir que du BRUIT.

    Deux proprietes de PLEIADES qu'on herite gratuitement : tres peu de
    parametres (un coefficient par ordre), et une insensibilite au pas de
    discretisation — la pente est normalisee par la duree REELLE de la fenetre,
    ce qui compte pour un sampler dont la periode varie (~122 s, irreguliere).
    """
    dernier = -1e18
    tirs: list[float] = []
    fen: list[tuple[float, float]] = []  # (ts, ram_ratio)
    for r in hist:
        v = r.get("ram_pct")
        ts = float(r.get("ts") or 0)
        if v is None:
            continue
        fen.append((ts, float(v) / 100.0))
        if len(fen) > fenetre_n:
            fen.pop(0)
        if len(fen) < fenetre_n:
            continue
        # Legendre d'ordre 1 sur la fenetre = pente des moindres carres, mais
        # exprimee sur l'axe TEMPS reel et non sur l'index : deux echantillons
        # espaces de 2 min et de 20 min ne disent pas la meme chose.
        t0 = fen[0][0]
        xs = [t - t0 for t, _ in fen]
        ys = [y for _, y in fen]
        n = len(fen)
        mx = sum(xs) / n
        my = sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom <= 0:
            continue
        pente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom  # ratio/s
        pente_par_min = pente * 60.0
        if pente_par_min >= seuil_pente and (ts - dernier) >= refractaire:
            tirs.append(ts)
            dernier = ts
    return tirs


def evaluer(tirs: list[float], eps: list[tuple[float, float]],
            duree_j: float, fenetre: float) -> dict:
    avances: list[float] = []
    vus = 0
    for debut, _fin in eps:
        precoces = [t for t in tirs if debut - fenetre <= t <= debut]
        if precoces:
            vus += 1
            avances.append(debut - min(precoces))
    dans_fenetre = {
        t for t in tirs
        for (d, f) in eps
        if d - fenetre <= t <= f
    }
    faux = len(tirs) - len(dans_fenetre)
    a_max = max(avances) if avances else None
    return {
        "tirs": len(tirs),
        "episodes_vus": vus,
        "episodes_total": len(eps),
        "avance_moyenne_s": round(sum(avances) / len(avances), 1) if avances else None,
        "avance_max_s": round(a_max, 1) if a_max is not None else None,
        # Si l'avance max colle a la fenetre, c'est la BORNE qu'on mesure : le
        # chiffre ne dit alors rien du detecteur.
        "avance_saturee": bool(a_max is not None and a_max >= fenetre * 0.98),
        "faux_positifs": faux,
        "faux_positifs_par_jour": round(faux / duree_j, 2) if duree_j > 0 else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Baseline seuil vs LIF sur vitals reels")
    ap.add_argument("--limit", type=int, default=10**9)
    ap.add_argument("--gains", type=lambda s: [float(x) for x in s.split(",") if x],
                    default=None, help="balayage FORGE_SNN_GAIN, ex: 2,4,6,8,12")
    ap.add_argument("--brief", action="store_true",
                    help="n'imprime que temoin + chemin arme + balayage (les "
                         "grilles simulees ne bougent pas d'une passe a l'autre)")
    ap.add_argument("--fenetre", type=float, default=FENETRE_ALERTE_S)
    args = ap.parse_args()

    hist = read_vitals_history(0.0, args.limit)
    if len(hist) < 100:
        print(json.dumps({"verdict": "PAS ASSEZ DE DONNEES",
                          "echantillons": len(hist)}, ensure_ascii=False, indent=2))
        return 0

    t0, t1 = float(hist[0]["ts"]), float(hist[-1]["ts"])
    duree_j = max(1e-9, (t1 - t0) / 86400.0)
    eps = episodes_detresse(hist)

    rapport: dict = {
        "echantillons": len(hist),
        "duree_jours": round(duree_j, 2),
        "seuil_ram_utilise": _THRESHOLDS["ram"],
        "refractaire_s": _REFRACTORY_S,
        "detresse_libre_gb": DETRESSE_LIBRE_GB,
        "episodes_detresse": len(eps),
        "fenetre_alerte_s": args.fenetre,
        "temoin_seuil": evaluer(detecteur_seuil(hist), eps, duree_j, args.fenetre),
        # Le capteur TEL QU'IL TOURNE. A lire AVANT la grille : une grille de
        # reglages simules ne dit rien de ce qui est arme en production.
        "prod_backend": _backend_prod(),
        "prod_monitor": evaluer(detecteur_monitor_prod(hist), eps, duree_j, args.fenetre),
    }
    if args.gains:
        # Le gain est le SEUL parametre libre du chemin arme. Le balayer sur les
        # memes donnees dit s'il existe un reglage qui n'est pas plus sourd que le
        # repli statique — sinon c'est l'entree elle-meme qu'il faut revoir.
        rapport["prod_gain_balayage"] = [
            {"gain": g, **evaluer(detecteur_monitor_prod(hist, gain=g), eps,
                                  duree_j, args.fenetre)}
            for g in args.gains
        ]
        detecteur_monitor_prod(hist[:1], gain=_SNN_GAIN_INITIAL)  # remet l'env en etat
    if not eps:
        rapport["verdict"] = (
            "AUCUN episode de detresse dans la fenetre : rien a detecter, donc "
            "aucune comparaison possible. Ce n'est pas un resultat en faveur d'un "
            "detecteur ou de l'autre."
        )
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    if args.brief:
        print(json.dumps({k: rapport[k] for k in (
            "echantillons", "duree_jours", "episodes_detresse", "fenetre_alerte_s",
            "temoin_seuil", "prod_backend", "prod_monitor", "prod_gain_balayage",
        ) if k in rapport}, ensure_ascii=False, indent=2))
        return 0

    grille = []
    for beta in (0.80, 0.90, 0.95, 0.98):
        for thr in (1.0, 1.5, 2.0, 3.0):
            grille.append({"beta": beta, "thr": thr,
                           **evaluer(detecteur_lif(hist, beta, thr), eps,
                                     duree_j, args.fenetre)})
    rapport["lif_grille"] = grille

    # Meilleur LIF = celui qui voit le PLUS d'episodes, puis le moins de faux
    # positifs, puis la plus grande avance. Jamais l'avance seule : un detecteur
    # qui crie en permanence "anticipe" tout par construction.
    # Detecteur a noyau polynomial : meme protocole, meme verite terrain.
    poly = []
    for fen_n in (5, 10, 20):
        for seuil in (0.005, 0.01, 0.02, 0.05):
            poly.append({"fenetre_n": fen_n, "seuil_pente_par_min": seuil,
                         **evaluer(detecteur_polynomial(hist, fen_n, seuil,
                                                        _REFRACTORY_S),
                                   eps, duree_j, args.fenetre)})
    rapport["polynomial_grille"] = poly
    poly_utiles = [g for g in poly if g["episodes_vus"] > 0]
    rapport["polynomial_meilleur"] = sorted(
        poly_utiles,
        key=lambda g: (-g["episodes_vus"], g["faux_positifs"],
                       -(g["avance_moyenne_s"] or 0)),
    )[0] if poly_utiles else None

    utiles = [g for g in grille if g["episodes_vus"] > 0]
    if utiles:
        meilleur = sorted(
            utiles,
            key=lambda g: (-g["episodes_vus"], g["faux_positifs"],
                           -(g["avance_moyenne_s"] or 0)),
        )[0]
        rapport["lif_meilleur"] = meilleur
    else:
        rapport["lif_meilleur"] = None
    rapport["lecture"] = (
        "Comparer temoin_seuil et lif_meilleur sur les TROIS colonnes a la fois : "
        "episodes_vus (a-t-il annonce ?), avance_moyenne_s (combien de temps "
        "avant ?), faux_positifs_par_jour (au prix de quel bruit ?). Un gain "
        "d'avance paye par une explosion de faux positifs n'est pas un gain. Si "
        "le temoin fait aussi bien, le dire : le LIF ne serait alors pas justifie "
        "sur CE signal."
    )
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
