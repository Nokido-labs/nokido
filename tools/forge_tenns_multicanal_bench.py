"""TENNs multi-canal : la correlation entre canaux bat-elle un seuil par canal ?

La question laissee ouverte le 2026-08-04. Le banc mono-canal
(`forge_snn_vitals_baseline`) a conclu que sur la SEULE RAM, rien ne bat le seuil :
ni un LIF, ni un noyau polynomial. Mais les TENNs sont *spatio*temporels — leur
force n'est pas la dynamique d'un scalaire, c'est la SIGNATURE CONJOINTE de
plusieurs canaux. Une RAM a 83 % seule est banale ; une RAM a 83 % qui monte
PENDANT que le disque sature et que le CPU decroche ne l'est pas. Un seuil par
canal ne peut structurellement pas voir ca. C'est cette hypothese-la qu'on teste.

Architecture, fidele au principe de TENNs-PLEIADES (arXiv 2405.12179) :
  - noyaux temporels = projection de chaque canal sur une base de polynomes
    ORTHOGONAUX (Legendre, ordres 0 et 1 = niveau et tendance), sur fenetre
    glissante, la pente etant normalisee par la duree REELLE de la fenetre —
    d'ou l'insensibilite au pas de discretisation, decisive ici car le sampler
    a une periode irreguliere ;
  - tete = melange lineaire APPRIS entre canaux (c'est la partie « spatiale »).
    Sans apprentissage, un melange choisi a la main ne prouverait rien.

Ce qui protege la mesure de la complaisance :
  1. **Split TEMPOREL, jamais aleatoire.** Entrainement sur les premiers 60 % du
     temps, test sur les 40 % suivants. Un split aleatoire melangerait des
     echantillons voisins de quelques minutes entre train et test : le modele
     retrouverait au test ce qu'il a vu a l'entrainement, et le score serait
     flatteur sans rien prouver.
  2. **Le seuil de decision est choisi sur le TRAIN**, puis applique tel quel au
     test. Le choisir sur le test serait le regler sur la reponse.
  3. **Le temoin est evalue sur EXACTEMENT le meme test**, avec le meme
     refractaire. Comparer un modele sur une periode et son temoin sur une autre
     ne compare rien.
  4. Faux positifs rapportes A COTE de la couverture : un detecteur qui crie sans
     cesse attrape tout par construction.

Usage :
    run action=run_job script=tools/forge_tenns_multicanal_bench.py
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/meta-evaluation"

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app.forge_resource_manager import read_vitals_history  # noqa: E402
from nokido_agent.tools.forge_snn_vitals_baseline import episodes_detresse  # noqa: E402  (meme verite terrain)

# TEMOIN : les 4 scalaires d'origine, INCHANGES. C'est ce qu'on cherche a battre,
# donc il ne doit surtout pas beneficier du vecteur elargi.
CANAUX_TEMOIN = ("ram_pct", "cpu_pct", "gpu_pct", "disk_pct")
SEUILS_TEMOIN = {"ram_pct": 85.0, "cpu_pct": 90.0, "gpu_pct": 95.0, "disk_pct": 95.0}

# MODELE : candidats du vecteur ELARGI cable le 2026-08-05. La selection finale est
# MESUREE sur la serie (presence + variance), jamais decretee ici — cf selectionner_canaux.
CANAUX_CANDIDATS = (
    "ram_pct", "cpu_pct", "gpu_pct", "disk_pct",
    "cmax", "ctx", "irq", "nr", "ior", "iow", "np", "swp", "cect",
    "emax", "esum", "en", "q8091", "q8099", "q8100", "q8766", "q11434",
    "tdr_recent", "ram_free_gb",
    # Canaux EVENEMENTIELS (2026-08-23). Absents de l'historique ANTERIEUR a leur
    # cablage : selectionner_canaux les ecartera alors avec le motif « presence »,
    # ce qui est le comportement voulu — un canal jeune se voit, il ne se devine pas.
    "hth", "hhd", "hfd", "hrs", "hcp",
    "ln", "lp95", "lmax", "lerr", "lbi", "lbo",
)
# Compatibilite d'import : forge_snn_entraine_vitals_bench importe CANAUX.
CANAUX = CANAUX_CANDIDATS
PRESENCE_MIN = 0.98

# Renseigne par traits() : ce qui a REELLEMENT servi, pour que les rapports ne
# decrivent pas une selection theorique.
DERNIERE_SELECTION: dict = {}

REFRACTAIRE_S = 1800.0   # celui du capteur, calibre le 04/08
HORIZON_S = 1800.0       # « un episode commence dans la demi-heure qui vient »
FENETRE_N = 10           # echantillons par fenetre glissante


def _mediane(v: list[float]) -> float:
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def selectionner_canaux(hist: list[dict],
                        presence_min: float = PRESENCE_MIN) -> tuple[tuple, dict]:
    """Retient les canaux MESURES comme exploitables, et rend les ECARTES avec leur motif.

    Un filtre qui jette des donnees sans le dire fait surestimer la couverture.
    Mesure 2026-08-23 : q8091 est muet 64,8 % du temps et l'ancien traits() jetait
    la fenetre ENTIERE des qu'un seul canal manquait — inclure un canal muet aurait
    donc supprime les deux tiers des fenetres, en silence."""
    n = max(1, len(hist))
    retenus: list[str] = []
    ecartes: dict = {}
    for c in CANAUX_CANDIDATS:
        vus = [r[c] for r in hist if r.get(c) is not None]
        taux = len(vus) / n
        if taux < presence_min:
            ecartes[c] = "presence %.1f %% < %.0f %%" % (100.0 * taux, 100.0 * presence_min)
            continue
        vals = [float(x) for x in vus]
        if max(vals) - min(vals) <= 0:
            ecartes[c] = "constant sur toute la serie (aucune information)"
            continue
        retenus.append(c)
    return tuple(retenus), ecartes


def stats_robustes(hist: list[dict], canaux) -> dict:
    """Echelle PAR CANAL (mediane, ecart interquartile).

    Calculee sur les 60 % LES PLUS ANCIENS — la meme fraction que le split temporel,
    pour qu'aucune statistique de la periode de test ne fuite dans la normalisation.
    Remplace le `/100` global, correct pour un pourcentage mais absurde pour ctx
    (~95 000), irq (~44 000) ou nr (~730), qui ecraseraient tout le reste."""
    n60 = max(1, int(len(hist) * 0.6))
    out: dict = {}
    for c in canaux:
        v = [float(r[c]) for r in hist[:n60] if r.get(c) is not None]
        if not v:
            out[c] = (0.0, 1.0)
            continue
        s = sorted(v)
        q1 = s[int(len(s) * 0.25)]
        q3 = s[int(len(s) * 0.75)]
        ecart = (q3 - q1) or (max(s) - min(s)) or 1.0
        out[c] = (_mediane(v), ecart)
    return out


def traits(hist: list[dict], fenetre_n: int, canaux=None,
           stats=None) -> tuple[list[float], list[list[float]]]:
    """Rend (timestamps, X) ou X = [niveau, pente] pour CHAQUE canal retenu.

    `canaux` par defaut = selection MESUREE sur la serie. La normalisation est
    desormais PAR CANAL (mediane / ecart interquartile) : le `/100` d'origine
    supposait que tout canal etait un pourcentage, ce qui n'est plus vrai depuis
    l'elargissement du vecteur le 2026-08-05.

    Le nombre de fenetres SAUTEES est publie dans DERNIERE_SELECTION : une fenetre
    ecartee sans trace est une couverture surestimee en silence."""
    if canaux is None:
        canaux = selectionner_canaux(hist)[0]
    canaux = tuple(canaux)
    if stats is None:
        stats = stats_robustes(hist, canaux)
    ts_out: list[float] = []
    X: list[list[float]] = []
    fen: list[dict] = []
    sautees = 0
    for r in hist:
        fen.append(r)
        if len(fen) > fenetre_n:
            fen.pop(0)
        if len(fen) < fenetre_n:
            continue
        t0 = float(fen[0].get("ts") or 0)
        xs = [float(e.get("ts") or 0) - t0 for e in fen]
        mx = sum(xs) / len(xs)
        denom = sum((x - mx) ** 2 for x in xs)
        ligne: list[float] = []
        ok = True
        for c in canaux:
            ys = [e.get(c) for e in fen]
            if any(y is None for y in ys) or denom <= 0:
                ok = False
                break
            med, ecart = stats[c]
            ys = [(float(y) - med) / ecart for y in ys]
            my = sum(ys) / len(ys)
            pente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
            ligne.append(my)                 # Legendre ordre 0 : niveau
            ligne.append(pente * 60.0)       # ordre 1 : tendance par minute
        if not ok:
            sautees += 1
            continue
        ts_out.append(float(fen[-1].get("ts") or 0))
        X.append(ligne)
    DERNIERE_SELECTION.clear()
    DERNIERE_SELECTION.update({
        "canaux": list(canaux),
        "fenetres_retenues": len(X),
        "fenetres_sautees": sautees,
    })
    return ts_out, X


def cibles(ts: list[float], eps: list[tuple[float, float]], horizon: float) -> list[int]:
    debuts = [d for d, _f in eps]
    return [1 if any(t <= d <= t + horizon for d in debuts) else 0 for t in ts]


def entrainer(X: list[list[float]], y: list[int], iters: int = 400,
              lr: float = 0.5) -> tuple[list[float], float]:
    """Regression logistique, descente de gradient. Pondere la classe positive :
    les episodes sont rares, sans quoi le modele apprend a toujours dire non."""
    n_f = len(X[0])
    w = [0.0] * n_f
    b = 0.0
    pos = max(1, sum(y))
    neg = max(1, len(y) - pos)
    poids_pos = neg / pos
    for _ in range(iters):
        gw = [0.0] * n_f
        gb = 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            poids = poids_pos if yi else 1.0
            err = (p - yi) * poids
            for j in range(n_f):
                gw[j] += err * xi[j]
            gb += err
        m = len(X)
        for j in range(n_f):
            w[j] -= lr * gw[j] / m
        b -= lr * gb / m
    return w, b


def proba(w: list[float], b: float, xi: list[float]) -> float:
    z = b + sum(wj * xj for wj, xj in zip(w, xi))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def tirs_depuis_scores(ts: list[float], scores: list[float], seuil: float,
                       refractaire: float) -> list[float]:
    dernier = -1e18
    out: list[float] = []
    for t, s in zip(ts, scores):
        if s >= seuil and t - dernier >= refractaire:
            out.append(t)
            dernier = t
    return out


def tirs_temoin(hist: list[dict], refractaire: float) -> list[float]:
    """Seuil PAR CANAL, combines en OU — ce que fait le capteur aujourd'hui.

    Porte sur CANAUX_TEMOIN et non sur les canaux du modele : le temoin est la
    reference a battre, l'elargir reviendrait a deplacer la cible pendant le tir.
    (Et SEUILS_TEMOIN n'a de seuil que pour ces quatre-la : itérer sur les canaux
    du modele levait un KeyError.)"""
    dernier = {c: -1e18 for c in CANAUX_TEMOIN}
    out: list[float] = []
    for r in hist:
        t = float(r.get("ts") or 0)
        for c in CANAUX_TEMOIN:
            v = r.get(c)
            if v is None:
                continue
            if float(v) >= SEUILS_TEMOIN[c] and t - dernier[c] >= refractaire:
                out.append(t)
                dernier[c] = t
    return sorted(out)


def choisir_seuil(t_tr: list[float], s_tr: list[float],
                  eps: list[tuple[float, float]], alerte: float,
                  refractaire: float = REFRACTAIRE_S) -> tuple[float, str | None]:
    """Seuil retenu sur le TRAIN : celui qui minimise les faux positifs en gardant
    TOUTE la couverture d'entrainement. Rend (seuil, note) ; la note n'est presente
    que si aucun seuil ne couvre tout, et elle doit etre publiee telle quelle.

    EXTRAIT le 2026-08-23 parce que le cliquet de clones l'a signale : cette
    sequence etait recopiee dans le retro-join. Deux bancs qui portent chacun leur
    copie du choix de seuil divergeraient en silence, et le jour ou l'un des deux
    serait corrige, l'autre continuerait de rendre l'ancien chiffre."""
    meilleur, retenu = None, None
    for seuil in [i / 100.0 for i in range(30, 96, 5)]:
        r = evaluer(tirs_depuis_scores(t_tr, s_tr, seuil, refractaire),
                    eps, t_tr[0], t_tr[-1], alerte)
        if r["episodes_test"] and r["episodes_vus"] == r["episodes_test"]:
            if meilleur is None or r["faux_positifs"] < meilleur["faux_positifs"]:
                meilleur, retenu = r, seuil
    if retenu is None:
        return 0.5, ("aucun seuil ne couvre 100 % du train ; repli sur 0.5, a lire "
                     "comme un aveu de faiblesse du modele")
    return retenu, None


def evaluer(tirs: list[float], eps: list[tuple[float, float]], t_debut: float,
            t_fin: float, fenetre: float) -> dict:
    eps_test = [(d, f) for d, f in eps if t_debut <= d <= t_fin]
    tirs = [t for t in tirs if t_debut <= t <= t_fin]
    dur_j = max(1e-9, (t_fin - t_debut) / 86400.0)
    vus = sum(1 for (d, _f) in eps_test if any(d - fenetre <= t <= d for t in tirs))
    dans = {t for t in tirs for (d, f) in eps_test if d - fenetre <= t <= f}
    faux = len(tirs) - len(dans)
    return {
        "episodes_test": len(eps_test),
        "episodes_vus": vus,
        "tirs": len(tirs),
        "faux_positifs": faux,
        "faux_positifs_par_jour": round(faux / dur_j, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="TENNs multi-canal vs seuil par canal")
    ap.add_argument("--fenetre-n", type=int, default=FENETRE_N)
    ap.add_argument("--horizon", type=float, default=HORIZON_S)
    ap.add_argument("--alerte", type=float, default=3600.0)
    args = ap.parse_args()

    hist = read_vitals_history(0.0, 10**9)
    eps = episodes_detresse(hist)
    retenus, ecartes = selectionner_canaux(hist)
    ts, X = traits(hist, args.fenetre_n, canaux=retenus)
    if len(X) < 500 or not eps:
        print(json.dumps({"verdict": "PAS ASSEZ DE DONNEES",
                          "traits": len(X), "episodes": len(eps)},
                         ensure_ascii=False, indent=2))
        return 0
    y = cibles(ts, eps, args.horizon)

    # Split TEMPOREL : le futur ne doit jamais servir a predire le passe.
    coupe = ts[int(len(ts) * 0.6)]
    tr = [i for i, t in enumerate(ts) if t <= coupe]
    te = [i for i, t in enumerate(ts) if t > coupe]
    Xtr, ytr = [X[i] for i in tr], [y[i] for i in tr]

    rapport: dict = {
        "echantillons_traits": len(X),
        "canaux_retenus": list(retenus),
        "canaux_ecartes": ecartes,
        "canaux_temoin": list(CANAUX_TEMOIN),
        "fenetres_sautees": DERNIERE_SELECTION.get("fenetres_sautees"),
        "traits_par_echantillon": len(X[0]),
        "episodes_total": len(eps),
        "positifs_train_pct": round(100.0 * sum(ytr) / max(1, len(ytr)), 1),
        "coupe_temporelle": coupe,
    }
    if sum(ytr) < 10:
        rapport["verdict"] = ("PAS ASSEZ D'EPISODES DANS LE TRAIN pour apprendre "
                              "quoi que ce soit — %d positifs" % sum(ytr))
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    w, b = entrainer(Xtr, ytr)
    noms = [f"{c}_{k}" for c in retenus for k in ("niveau", "pente")]
    rapport["poids_appris"] = {n: round(v, 3) for n, v in zip(noms, w)}

    # Seuil choisi sur le TRAIN : celui qui minimise les faux positifs tout en
    # gardant toute la couverture d'entrainement.
    s_tr = [proba(w, b, X[i]) for i in tr]
    t_tr = [ts[i] for i in tr]
    meilleur_seuil, note = choisir_seuil(t_tr, s_tr, eps, args.alerte)
    if note:
        rapport["note_seuil"] = note
    rapport["seuil_choisi_sur_train"] = meilleur_seuil

    # ---- TEST : le seul chiffre qui compte ----
    s_te = [proba(w, b, X[i]) for i in te]
    t_te = [ts[i] for i in te]
    t0, t1 = t_te[0], t_te[-1]
    rapport["periode_test_jours"] = round((t1 - t0) / 86400.0, 2)
    rapport["tenns_multicanal"] = evaluer(
        tirs_depuis_scores(t_te, s_te, meilleur_seuil, REFRACTAIRE_S),
        eps, t0, t1, args.alerte)
    rapport["temoin_seuil_par_canal"] = evaluer(
        tirs_temoin(hist, REFRACTAIRE_S), eps, t0, t1, args.alerte)
    rapport["lecture"] = (
        "Les deux lignes portent sur la MEME periode de test, jamais vue a "
        "l'entrainement, avec le meme refractaire. Le modele ne gagne que s'il "
        "voit autant d'episodes AVEC MOINS de faux positifs. A couverture egale "
        "et bruit egal ou superieur, il ne sert a rien et il faut le dire."
    )
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
