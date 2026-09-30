"""Le SNN ENTRAINE bat-il le seuil sur les vitals reels ? (mesure manquante)

Ce que les bancs precedents ont fait, et pourquoi ca ne suffisait pas. Le banc
mono-canal balayait des parametres LIF (beta, seuil) en grille : c'est du REGLAGE,
pas de l'apprentissage. Le banc multi-canal apprenait, mais avec une tete LINEAIRE
sur des traits polynomiaux. Dans les deux cas le seuil gagnait — et j'en ai conclu
trop vite que « le neuromorphique n'apporte rien sur ce signal ».

Or `forge_snn_core.SpikingMLP` est un reseau spiking COMPLET et entrainable
(LIFCell differentiable, gradient de substitution arctan, 25 pas de temps), et son
selftest prouve qu'il apprend (0.848 -> 1.0). Il n'avait jamais vu les vitals.
Conclure sur un LIF non entraine, c'etait juger l'architecture sur un reglage.

Ce banc comble ce trou : MEME modele que la production, entraine sur les vitals
REELS, evalue contre le meme temoin et sur la meme periode.

Garde-fous, identiques aux bancs precedents (une mesure qui arrange se verifie) :
  - split TEMPOREL 60/40, jamais aleatoire : des echantillons distants de quelques
    minutes se ressemblent, un split aleatoire ferait retrouver au test ce qui a
    ete vu a l'entrainement ;
  - seuil de decision choisi sur le TRAIN, applique tel quel au test ;
  - temoin (seuil par canal) evalue sur EXACTEMENT la meme periode, meme
    refractaire ;
  - faux positifs rapportes A COTE de la couverture ;
  - classe positive ponderee : les episodes sont rares, sans quoi le reseau
    apprend a toujours dire non et affiche une belle exactitude qui ne detecte rien.

Usage :
    run action=run_job script=tools/forge_snn_entraine_vitals_bench.py
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/meta-evaluation"

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app.forge_resource_manager import read_vitals_history  # noqa: E402
from nokido_agent.tools.forge_snn_vitals_baseline import episodes_detresse  # noqa: E402
from nokido_agent.tools.forge_tenns_multicanal_bench import (  # noqa: E402
    CANAUX, DERNIERE_SELECTION, REFRACTAIRE_S, cibles, evaluer, tirs_temoin, traits,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="SNN entraine vs seuil, vitals reels")
    ap.add_argument("--fenetre-n", type=int, default=10)
    ap.add_argument("--horizon", type=float, default=1800.0)
    ap.add_argument("--alerte", type=float, default=3600.0)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--hidden", type=int, default=16)
    ap.add_argument("--steps", type=int, default=25)
    args = ap.parse_args()

    t0 = time.time()
    rapport: dict = {"modele": "forge_snn_core.SpikingMLP (production)",
                     "canaux_candidats": list(CANAUX)}

    from nokido_agent.app import forge_snn_core as core
    dispo = core.available()
    rapport["snn_core"] = {k: v for k, v in dispo.items() if k != "torch_err"}
    if not dispo.get("torch"):
        rapport["verdict"] = (
            "MESURE IMPOSSIBLE : torch illisible ici (%s). Relancer hors du "
            "sandbox — le WORKSPACE_GUARD bloque `open(os.devnull)` que dill "
            "execute a l'import." % dispo.get("torch_etat"))
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    import torch  # noqa: PLC0415
    import torch.nn as nn  # noqa: PLC0415

    hist = read_vitals_history(0.0, 10**9)
    eps = episodes_detresse(hist)
    ts, X = traits(hist, args.fenetre_n)
    # `CANAUX` n'est que la liste des CANDIDATS : traits() ecarte ceux que la serie
    # ne porte pas assez. Publier la selection REELLE, sinon le rapport decrit une
    # mesure qui n'a pas eu lieu (2026-08-23).
    rapport.update(dict(DERNIERE_SELECTION))
    y = cibles(ts, eps, args.horizon)
    if len(X) < 500 or not eps:
        rapport["verdict"] = "PAS ASSEZ DE DONNEES"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    coupe = ts[int(len(ts) * 0.6)]
    tr = [i for i, t in enumerate(ts) if t <= coupe]
    te = [i for i, t in enumerate(ts) if t > coupe]
    rapport.update({"echantillons": len(X), "traits": len(X[0]),
                    "episodes_total": len(eps),
                    "positifs_train_pct": round(100.0 * sum(y[i] for i in tr) / max(1, len(tr)), 1)})
    if sum(y[i] for i in tr) < 10:
        rapport["verdict"] = "PAS ASSEZ D'EPISODES DANS LE TRAIN"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    # Normalisation MIN-MAX vers [0, 1], calculee sur le TRAIN seul.
    # Deux raisons, et la premiere est une correction : l'entree de SpikingMLP est
    # RATE-CODEE — `(torch.rand_like(x) < x)`, encodage de Poisson — donc une
    # valeur hors [0, 1] est soit toujours muette (negatif), soit toujours
    # spikante (>1). Une normalisation z-score, qui produit des negatifs, aurait
    # entraine le reseau sur des entrees invalides et rendu un « le SNN perd »
    # qui n'aurait mesure que mon erreur d'encodage.
    # Seconde raison : les bornes viennent du TRAIN seul, sinon des statistiques
    # du futur fuient dans le passe.
    Xtr = torch.tensor([X[i] for i in tr], dtype=torch.float32)
    ytr = torch.tensor([y[i] for i in tr], dtype=torch.long)
    bas = Xtr.min(0).values
    haut = Xtr.max(0).values
    etendue = (haut - bas).clamp_min(1e-6)
    Xtr = ((Xtr - bas) / etendue).clamp(0.0, 1.0)
    Xte = (((torch.tensor([X[i] for i in te], dtype=torch.float32) - bas)
            / etendue).clamp(0.0, 1.0))

    torch.manual_seed(20260804)
    net = core.SpikingMLP(in_dim=len(X[0]), hidden=args.hidden, out_dim=2,
                          steps=args.steps)
    opt = torch.optim.Adam(net.parameters(), lr=0.01)
    n_pos = int(ytr.sum())
    poids = torch.tensor([1.0, max(1.0, (len(ytr) - n_pos) / max(1, n_pos))])
    perte = nn.CrossEntropyLoss(weight=poids)

    lots = torch.split(torch.arange(len(Xtr)), 512)
    for _ep in range(args.epochs):
        for idx in lots:
            opt.zero_grad()
            # forward rend (taux de spikes de sortie, nombre total de spikes)
            out, _spk = net(Xtr[idx])
            loss = perte(out, ytr[idx])
            loss.backward()
            opt.step()
    rapport["perte_finale"] = round(float(loss.item()), 4)
    rapport["duree_entrainement_s"] = round(time.time() - t0, 1)

    with torch.no_grad():
        _o_tr, _n_tr = net(Xtr)
        _o_te, _n_te = net(Xte)
        s_tr = torch.softmax(_o_tr, dim=1)[:, 1].tolist()
        s_te = torch.softmax(_o_te, dim=1)[:, 1].tolist()
    # Le nombre de spikes est la preuve que le substrat a REELLEMENT emis :
    # un reseau spiking a zero spike aurait « appris » sans rien encoder.
    rapport["spikes_inference_train"] = _n_tr
    rapport["spikes_inference_test"] = _n_te

    from nokido_agent.tools.forge_tenns_multicanal_bench import tirs_depuis_scores  # noqa: PLC0415

    t_tr = [ts[i] for i in tr]
    meilleur_seuil, meilleur_fp = None, None
    for seuil in [i / 100.0 for i in range(20, 96, 5)]:
        r = evaluer(tirs_depuis_scores(t_tr, s_tr, seuil, REFRACTAIRE_S),
                    eps, t_tr[0], t_tr[-1], args.alerte)
        if r["episodes_test"] and r["episodes_vus"] == r["episodes_test"]:
            if meilleur_fp is None or r["faux_positifs"] < meilleur_fp:
                meilleur_fp, meilleur_seuil = r["faux_positifs"], seuil
    if meilleur_seuil is None:
        meilleur_seuil = 0.5
        rapport["note_seuil"] = ("aucun seuil ne couvre 100 % du train ; repli sur "
                                 "0.5, a lire comme une faiblesse du modele")
    rapport["seuil_choisi_sur_train"] = meilleur_seuil

    t_te = [ts[i] for i in te]
    t0e, t1e = t_te[0], t_te[-1]
    rapport["periode_test_jours"] = round((t1e - t0e) / 86400.0, 2)
    rapport["snn_entraine"] = evaluer(
        tirs_depuis_scores(t_te, s_te, meilleur_seuil, REFRACTAIRE_S),
        eps, t0e, t1e, args.alerte)
    rapport["temoin_seuil_par_canal"] = evaluer(
        tirs_temoin(hist, REFRACTAIRE_S), eps, t0e, t1e, args.alerte)
    rapport["lecture"] = (
        "Meme periode de test, jamais vue a l'entrainement, meme refractaire. Le "
        "SNN ne gagne que s'il voit autant d'episodes AVEC MOINS de faux positifs. "
        "S'il perd encore, la conclusion devient solide : ce n'est plus un defaut "
        "de reglage ni de tete lineaire, c'est que le signal ne porte pas "
        "l'information — et c'est alors les CAPTEURS qu'il faut changer."
    )
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
