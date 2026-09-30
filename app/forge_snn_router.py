# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = routing/snn
ROUTEUR SNN pour le routage LLM - l'etage L1 de la cascade.

POURQUOI ce module (anti-dup) - il n'ecrit AUCUN substrat :
  - le LIF apprenable existe deja  -> forge_snn_core.SpikingMLP (surrogate gradient)
  - les 35 features existent deja  -> forge_llm_router_dt.TextFeatureExtractor
  - le dataset existe deja         -> forge_llm_router_dt._make_dataset()
  - le contrat de sortie existe    -> forge_routing_decision.RoutingDecision
  Ce module ne fait que les CABLER. Il ne remplace pas le DT : il se place AVANT
  lui et s'abstient des qu'il doute, ce qui rend la main a l'etage L3.

  CTFSpikeRouter (forge_spike_router) ne pouvait pas servir ici : il consomme des
  ChallengeFeatures CTF (31 dims, binaires ELF/pwn), un espace etranger au texte
  d'un prompt. Meme famille de reseau, corpus sans rapport.

DEUX PROPRIETES QUE CET ETAGE DOIT AVOIR, sinon il nuit :

  1. DETERMINISME. SpikingMLP encode l'entree en Poisson (torch.rand_like) :
     deux appels sur le MEME prompt ne donnent pas le meme train de spikes. Un
     routeur qui change d'avis sans que rien ne change est un defaut, pas une
     propriete neuromorphique. L'inference moyenne donc N_PASSES passes sous
     une graine fixe, et expose l'ecart-type inter-passes comme incertitude.

  2. ABSTENTION. Le corpus reel est de 55 exemples pour 9 classes, dont
     certaines a 2 exemples. A ce volume, un modele qui repond TOUJOURS ment.
     La valeur de cet etage est de savoir quand il ne sait pas : sous
     MIN_RATE ou sous MIN_MARGIN, il rend une abstention qui dit d'aller en L3.

  LAFORGE_PYTHON app/forge_snn_router.py              # selftest + validation croisee
  LAFORGE_PYTHON app/forge_snn_router.py --train      # entraine et persiste
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.SNNRouter")

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "snn_router.pt"

# Seuils d'abstention MESURES, pas poses a la main.
#
# La premiere version portait MIN_RATE=0.15 / MIN_MARGIN=0.05, choisis au juge :
# le SNN repondait alors "groq" a une entree VIDE avec un taux de 0.17, et le
# LOO donnait ZERO abstention. Un seuil qui ne separe rien n'est pas un seuil.
#
# calibrate_thresholds() (LOO 55 plis, 30 epochs, backend builtin, 2026-08-21) :
#     sans abstention          exactitude 0.655  couverture 1.000
#     min_rate 0.80/marge 0.15 exactitude 0.848  couverture 0.600   <- retenu
# soit +0.193 d'exactitude en rendant 40% des cas a l'etage L3.
#
# ATTENTION : une premiere calibration donnait 0.80/0.05 -> 0.857. Elle avait
# tourne AVANT que BACKEND soit fige, donc sous snn.Leaky. Changer de backend
# change les taux de spikes, donc les seuils : une calibration n'est valide que
# pour la structure sur laquelle elle a ete faite. Refaite sous builtin, 0.05
# ne rend plus que 0.811 et 0.15 devient l'optimum.
#
# A RE-CALIBRER quand router_decisions.jsonl grossit, ou a tout changement de
# BACKEND / STEPS / HIDDEN : ces valeurs decrivent un corpus de 55 exemples et
# une structure donnee, elles ne sont pas une constante de la nature.
MIN_RATE = 0.80      # taux de spikes du gagnant ; en dessous, le SNN n'a rien vu
MIN_MARGIN = 0.15    # ecart top1-top2 ; en dessous, deux providers sont a egalite
N_PASSES = 7         # passes moyennees a l'inference (voir DETERMINISME ci-dessus)
STEPS = 25
HIDDEN = 48

# Backend LIF FIXE, jamais "auto". SpikingMLP change de structure selon que
# snntorch est importable : snn.Leaky porte des parametres que LIFCell n'a pas.
# Mesure du 2026-08-21 : le modele ecrit par trusted_script (env sans snntorch)
# refusait de se charger cote sandbox (env avec), avec 8 cles manquantes. Des
# poids persistes doivent etre portables entre interpreteurs -> "builtin", qui
# ne depend que de torch.
BACKEND = "builtin"

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy est un socle
    np = None

try:
    import torch
    import torch.nn as nn

    _TORCH = True
    _TORCH_ERR = None
except Exception as e:  # noqa: BLE001
    _TORCH = False
    _TORCH_ERR = str(e)


def available() -> dict:
    """Trois etats, jamais deux - meme trilemme que forge_snn_core.available().

    Sous le sandbox du hub, l'import de torch echoue parce que dill ouvre
    os.devnull a l'import et que WORKSPACE_GUARD refuse nul. Rendre un simple
    False confondrait "torch absent" et "pas pu regarder", et ce faux negatif a
    deja oriente un plan entier sur une premisse fausse.
    """
    if _TORCH:
        etat = "present"
    elif _TORCH_ERR and "WORKSPACE_GUARD" in str(_TORCH_ERR):
        etat = "illisible_garde_sandbox"
    else:
        etat = "absent"
    return {"torch": _TORCH, "torch_etat": etat, "torch_err": _TORCH_ERR,
            "model_present": MODEL_PATH.exists()}


def decide_from_rates(rates, sigma, providers) -> Any:
    """Traduit des taux de spikes en RoutingDecision. Fonction PURE (numpy seul).

    Extraite de predict() pour etre testable sans torch : la regle d'abstention
    est la partie qui doit etre verifiee, et elle ne depend d'aucun reseau.
    """
    from nokido_agent.app.forge_routing_decision import RoutingDecision, abstention

    order = np.argsort(rates)[::-1]
    alts = [(providers[int(i)], round(float(rates[int(i)]), 4)) for i in order[:5]]
    top_i = int(order[0])
    top_rate = float(rates[top_i])
    second = float(rates[int(order[1])]) if len(order) > 1 else 0.0
    margin = top_rate - second
    # Incertitude = ce que le train de spikes laisse flotter (sigma) PLUS ce que
    # deux candidats proches laissent indecidable (marge).
    jitter = float(sigma[top_i]) / (top_rate + 1e-6) if top_rate > 0 else 1.0
    unc = 0.5 * min(jitter, 1.0) + 0.5 * (1.0 - min(margin / 0.5, 1.0))
    unc = max(0.0, min(1.0, unc))

    if top_rate < MIN_RATE:
        return abstention("L1", "L3",
                          f"taux de spikes trop bas ({top_rate:.3f} < {MIN_RATE})",
                          source="forge_snn_router", alternatives=alts)
    if margin < MIN_MARGIN:
        return abstention("L1", "L3",
                          f"marge insuffisante ({margin:.3f} < {MIN_MARGIN}) : "
                          f"{alts[0][0]} et {alts[1][0]} a egalite",
                          source="forge_snn_router", alternatives=alts)

    return RoutingDecision(
        route="provider",
        provider=providers[top_i],
        confidence=min(1.0, top_rate),
        uncertainty=unc,
        evidence=[f"taux={top_rate:.3f}", f"marge={margin:.3f}",
                  f"jitter_poisson={jitter:.3f}", f"passes={N_PASSES}"],
        alternatives=alts,
        reason="taux de spikes dominant et stable",
        level="L1",
        next_level="L3",
        source="forge_snn_router",
    )


def _deps():
    """Importe les briques existantes. Import tardif : ce module doit pouvoir
    etre charge (et rendre available()) meme quand torch manque."""
    app_dir = str(ROOT / "app")
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from nokido_agent.app.forge_snn_core import SpikingMLP
    from nokido_agent.app.forge_llm_router_dt import (
        FEATURE_DIM,
        PROVIDERS,
        I2P,
        P2I,
        TextFeatureExtractor,
        _make_dataset,
    )

    return (SpikingMLP, FEATURE_DIM, PROVIDERS, I2P, P2I, TextFeatureExtractor,
            _make_dataset)


class SNNRouter:
    """Etage L1 : SpikingMLP sur les 35 features textuelles, avec abstention."""

    def __init__(self, hidden: int = HIDDEN, steps: int = STEPS, seed: int = 0):
        if not _TORCH:
            raise RuntimeError(f"torch indisponible: {_TORCH_ERR}")
        (SpikingMLP, FEATURE_DIM, PROVIDERS, I2P, P2I, TextFeatureExtractor,
         make_dataset) = _deps()
        self.feature_dim = FEATURE_DIM
        self.providers = list(PROVIDERS)
        self._i2p, self._p2i = I2P, P2I
        self._ext = TextFeatureExtractor()
        self._make_dataset = make_dataset
        self.seed = seed
        torch.manual_seed(seed)
        try:
            self.net = SpikingMLP(FEATURE_DIM, hidden, len(PROVIDERS), steps=steps,
                                  backend=BACKEND)
        except TypeError:
            # forge_snn_core anterieur au parametre `backend` : on retombe sur
            # l'auto-detection, en le disant -- les poids ne seront alors
            # portables qu'entre interpreteurs identiques.
            logger.warning("[SNNRouter] forge_snn_core sans parametre backend : "
                           "poids non portables entre environnements")
            self.net = SpikingMLP(FEATURE_DIM, hidden, len(PROVIDERS), steps=steps)
        self.backend = getattr(self.net, "backend", "inconnu")
        self._trained = False

    def fit(self, X, Y, epochs: int = 80, lr: float = 0.01) -> dict:
        """Entraine par surrogate gradient. X doit tenir dans [0,1] : c'est un
        taux de spike, pas une amplitude libre."""
        xmin, xmax = float(X.min()), float(X.max())
        if xmin < 0.0 or xmax > 1.0:
            # Un rate-codage hors [0,1] produit des probabilites de spike
            # aberrantes que torch.rand_like ne signale pas.
            raise ValueError(f"features hors [0,1] (min={xmin}, max={xmax})")
        xt = torch.tensor(X, dtype=torch.float32)
        yt = torch.tensor(Y, dtype=torch.long)
        opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        lossf = nn.CrossEntropyLoss()
        loss = None
        self.net.train()
        for _ in range(epochs):
            opt.zero_grad()
            out, _spk = self.net(xt)
            loss = lossf(out, yt)
            loss.backward()
            opt.step()
        self._trained = True
        return {"ok": True, "epochs": epochs, "n": int(xt.shape[0]),
                "final_loss": round(float(loss.item()), 4) if loss is not None else None}

    def fit_from_corpus(self, epochs: int = 80) -> dict:
        X, Y = self._make_dataset()
        r = self.fit(X, Y, epochs=epochs)
        r["classes_vues"] = sorted({self._i2p[int(c)] for c in Y})
        return r

    def _rates(self, X):
        """Taux de spikes moyennes sur N_PASSES, graine fixe -> reproductible.

        Retourne (moyenne, ecart-type) par classe : l'ecart-type inter-passes
        EST la mesure de ce que l'encodage de Poisson laisse d'indetermine.
        """
        self.net.eval()
        xt = torch.tensor(X, dtype=torch.float32)
        passes = []
        with torch.no_grad():
            for k in range(N_PASSES):
                torch.manual_seed(self.seed * 1000 + k)
                out, _ = self.net(xt)
                passes.append(out.numpy())
        arr = np.stack(passes)  # (P, B, C)
        return arr.mean(axis=0), arr.std(axis=0)

    def predict(self, prompt: str, task_type: str = "") -> Any:
        """Rend une RoutingDecision de niveau L1 (provider ou abstention)."""
        from nokido_agent.app.forge_routing_decision import abstention

        if not self._trained:
            return abstention("L1", "L3", "SNN non entraine", source="forge_snn_router")

        vec = self._ext.extract(prompt, task_type).reshape(1, -1)
        mean, std = self._rates(vec)
        return decide_from_rates(mean[0], std[0], self.providers)

    def save(self, path: Optional[Path] = None) -> str:
        p = Path(path or MODEL_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state": self.net.state_dict(), "providers": self.providers,
                    "feature_dim": self.feature_dim, "seed": self.seed,
                    "backend": self.backend}, str(p))
        return str(p)

    def load(self, path: Optional[Path] = None) -> bool:
        p = Path(path or MODEL_PATH)
        if not p.exists():
            return False
        blob = torch.load(str(p), weights_only=False)
        if blob.get("feature_dim") != self.feature_dim:
            # Un modele entraine sur un autre espace de features rend des taux
            # qui ne veulent rien dire : refuser, ne pas "adapter".
            logger.warning(
                f"[SNNRouter] modele ignore: feature_dim={blob.get('feature_dim')} "
                f"!= {self.feature_dim}"
            )
            return False
        blob_backend = blob.get("backend")
        if blob_backend is not None and blob_backend != self.backend:
            # Deux backends = deux state_dict incompatibles. Sans cette garde,
            # load_state_dict LEVE, et l'appelant ne sait pas pourquoi.
            logger.warning(
                f"[SNNRouter] modele ignore: backend={blob_backend} != {self.backend} "
                "-> re-entrainer (forge_snn_router.py --train)"
            )
            return False
        try:
            self.net.load_state_dict(blob["state"])
        except RuntimeError as e:
            # Modele anterieur au champ `backend` : structure indeterminable.
            logger.warning(f"[SNNRouter] state_dict incompatible, modele ignore: {e}")
            return False
        self._trained = True
        return True


def cross_validate_loo(epochs: int = 40, seed: int = 0,
                       max_folds: Optional[int] = None) -> dict:
    """Leave-one-out sur le corpus reel. Rapporte ce qu'une accuracy seule cache.

    Pourquoi LOO et pas un simple train/test : a 55 exemples dont des classes a
    2, tout split stratifie laisse des classes absentes du train. LOO est le
    seul protocole qui n'invente pas de repartition.

    Le retour porte trois taux, jamais un seul :
      - accuracy_globale   : abstention comptee comme erreur (pessimiste)
      - accuracy_si_repond : sur les seuls cas ou le SNN s'est prononce
      - taux_abstention    : la part qu'il a rendue a l'etage suivant
    Un modele qui s'abstient partout aurait une accuracy_si_repond flatteuse et
    une accuracy_globale nulle : les lire ensemble est le seul usage honnete.
    """
    if not _TORCH:
        return {"ok": False, "reason": f"torch indisponible: {_TORCH_ERR}"}
    from nokido_agent.app.forge_llm_router_dt import _make_dataset, I2P

    X, Y = _make_dataset()
    n = int(X.shape[0])
    folds = n if max_folds is None else min(n, max_folds)
    bons = abstentions = faux = 0
    par_classe: dict = {}
    confusions: list = []

    for i in range(folds):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        r = SNNRouter(seed=seed)
        r.fit(X[mask], Y[mask], epochs=epochs)
        mean, _std = r._rates(X[i: i + 1])
        rates = mean[0]
        order = np.argsort(rates)[::-1]
        top, top_rate = int(order[0]), float(rates[int(order[0])])
        margin = (top_rate - float(rates[int(order[1])])) if len(order) > 1 else 1.0
        attendu = I2P[int(Y[i])]
        par_classe.setdefault(attendu, [0, 0, 0])  # [bon, abstention, faux]

        if top_rate < MIN_RATE or margin < MIN_MARGIN:
            abstentions += 1
            par_classe[attendu][1] += 1
        elif top == int(Y[i]):
            bons += 1
            par_classe[attendu][0] += 1
        else:
            faux += 1
            par_classe[attendu][2] += 1
            confusions.append((attendu, r.providers[top]))

    repondu = bons + faux
    res = {
        "ok": True,
        "protocole": f"leave-one-out, {folds} plis, {epochs} epochs",
        "n": folds,
        "bons": bons,
        "faux": faux,
        "abstentions": abstentions,
        "accuracy_globale": round(bons / folds, 3) if folds else 0.0,
        "accuracy_si_repond": round(bons / repondu, 3) if repondu else None,
        "taux_abstention": round(abstentions / folds, 3) if folds else 0.0,
        "par_classe": {k: {"bon": v[0], "abstention": v[1], "faux": v[2]}
                       for k, v in sorted(par_classe.items())},
        "confusions": confusions[:12],
    }
    # Le verdict fait partie de la mesure : une accuracy sans son domaine de
    # validite est exactement ce que reprochait le "12/12" du routeur CTF.
    if repondu == 0:
        res["verdict"] = ("s'abstient TOUJOURS : inutile en l'etat, mais inoffensif "
                          "(rend systematiquement la main a L3)")
    elif folds < 100:
        res["verdict"] = (
            f"corpus de {folds} exemples : ces chiffres decrivent CE corpus, ils ne "
            "permettent pas de conclure sur la generalisation. A relancer des que "
            "router_decisions.jsonl depasse quelques centaines de lignes."
        )
    else:
        res["verdict"] = "corpus suffisant pour une lecture de generalisation"
    return res


def calibrate_thresholds(epochs: int = 30, seed: int = 0,
                         max_folds: Optional[int] = None,
                         couverture_min: float = 0.30) -> dict:
    """Mesure les seuils d'abstention au lieu de les poser a la main.

    Un seuil ecrit au juge n'est pas une mesure : la premiere version de ce
    module portait MIN_RATE=0.15 / MIN_MARGIN=0.05, et le SNN repondait "groq"
    a une entree VIDE avec un taux de 0.17. Le seuil ne separait rien.

    Protocole : LOO, on collecte (taux_top, marge, correct) pour chaque pli,
    puis on balaie une grille. Pour chaque couple de seuils on lit DEUX chiffres
    indissociables - l'exactitude quand le routeur repond, et la part des cas
    qu'il accepte de traiter. Maximiser l'un seul est trivial et faux : un
    routeur qui ne repond qu'une fois a 100% d'exactitude et zero utilite.

    On retient donc le couple qui maximise l'exactitude SOUS une couverture
    plancher, et on rend la table complete pour que le choix reste inspectable.
    """
    if not _TORCH:
        return {"ok": False, "reason": f"torch indisponible: {_TORCH_ERR}"}
    from nokido_agent.app.forge_llm_router_dt import _make_dataset

    X, Y = _make_dataset()
    n = int(X.shape[0])
    folds = n if max_folds is None else min(n, max_folds)
    obs: list = []  # (taux_top, marge, correct)

    for i in range(folds):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        r = SNNRouter(seed=seed)
        r.fit(X[mask], Y[mask], epochs=epochs)
        mean, _std = r._rates(X[i: i + 1])
        rates = mean[0]
        order = np.argsort(rates)[::-1]
        top_rate = float(rates[int(order[0])])
        marge = (top_rate - float(rates[int(order[1])])) if len(order) > 1 else 1.0
        obs.append((top_rate, marge, int(order[0]) == int(Y[i])))

    table: list = []
    for seuil_rate in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        for seuil_marge in (0.0, 0.02, 0.05, 0.10, 0.15, 0.20):
            rep = [c for (t, m, c) in obs if t >= seuil_rate and m >= seuil_marge]
            couverture = len(rep) / len(obs) if obs else 0.0
            exactitude = (sum(rep) / len(rep)) if rep else None
            table.append({"min_rate": seuil_rate, "min_margin": seuil_marge,
                          "couverture": round(couverture, 3),
                          "exactitude_si_repond": None if exactitude is None
                          else round(exactitude, 3),
                          "n_repondus": len(rep)})

    eligibles = [t for t in table
                 if t["couverture"] >= couverture_min and t["exactitude_si_repond"]]
    # A exactitude egale, preferer la plus grande couverture : un etage L1 qui
    # renvoie tout en L3 ne coute rien mais n'apporte rien non plus.
    meilleur = max(eligibles,
                   key=lambda t: (t["exactitude_si_repond"], t["couverture"])) \
        if eligibles else None
    base = [t for t in table if t["min_rate"] == 0.0 and t["min_margin"] == 0.0]
    return {
        "ok": True,
        "protocole": f"LOO {folds} plis, {epochs} epochs, couverture_min={couverture_min}",
        "sans_abstention": base[0] if base else None,
        "meilleur": meilleur,
        "gain_exactitude": (round(meilleur["exactitude_si_repond"]
                                  - base[0]["exactitude_si_repond"], 3)
                            if meilleur and base and base[0]["exactitude_si_repond"]
                            else None),
        "seuils_actuels": {"MIN_RATE": MIN_RATE, "MIN_MARGIN": MIN_MARGIN},
        "table": sorted(table, key=lambda t: (-(t["exactitude_si_repond"] or 0),
                                              -t["couverture"]))[:14],
    }


def cross_validate_ctf_loo(epochs: int = 60, max_folds: Optional[int] = None) -> dict:
    """Meme protocole applique au CTFSpikeRouter, dont la docstring annoncait
    "12/12 routage parfait en test" - mesure faite sur build_training_set(),
    c'est-a-dire sur son PROPRE jeu d'entrainement. Ceci mesure autre chose."""
    if not _TORCH:
        return {"ok": False, "reason": f"torch indisponible: {_TORCH_ERR}"}
    from nokido_agent.app.forge_spike_router import CTFSpikeRouter, STRATEGIES, build_training_set

    X, Y = build_training_set()
    if not torch.is_tensor(X):
        X = torch.tensor(X, dtype=torch.float32)
    if not torch.is_tensor(Y):
        Y = torch.tensor(Y, dtype=torch.long)
    n = int(X.shape[0])
    folds = n if max_folds is None else min(n, max_folds)
    bons = faux = abstentions = 0
    confusions: list = []
    # forward() rend (logits, spikes) : train_router ET predict travaillent tous
    # deux sur `spikes`. Mesurer `logits` mesurerait un chemin que le routeur
    # n'emprunte jamais.
    seuil_skip = 0.15  # meme seuil que CTFSpikeRouter.predict -> "skip"

    for i in range(folds):
        idx = [j for j in range(n) if j != i]
        net = CTFSpikeRouter(input_dim=int(X.shape[1]),
                             num_strategies=len(STRATEGIES))
        opt = torch.optim.Adam(net.parameters(), lr=0.01)
        net.train()
        for _ in range(epochs):
            opt.zero_grad()
            _logits, spikes = net(X[idx])
            torch.nn.functional.cross_entropy(spikes, Y[idx]).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            _logits, spikes = net(X[i: i + 1])
            probs = torch.nn.functional.softmax(spikes.squeeze(0), dim=-1)
            conf = float(probs.max().item())
            pred = int(probs.argmax().item())
        if conf < seuil_skip:
            abstentions += 1
        elif pred == int(Y[i]):
            bons += 1
        else:
            faux += 1
            confusions.append((STRATEGIES[int(Y[i])], STRATEGIES[pred]))

    repondu = bons + faux
    return {
        "ok": True,
        "protocole": f"leave-one-out, {folds} plis, {epochs} epochs, chemin spikes",
        "n": folds,
        "bons": bons,
        "faux": faux,
        "abstentions": abstentions,
        "accuracy_loo": round(bons / folds, 3) if folds else 0.0,
        "accuracy_si_repond": round(bons / repondu, 3) if repondu else None,
        "taux_abstention": round(abstentions / folds, 3) if folds else 0.0,
        "confusions": confusions[:12],
        "verdict": ("a comparer au 12/12 historique, mesure sur le jeu "
                    "d'ENTRAINEMENT : l'ecart EST la part de memorisation."),
    }


def _selftest(quick: bool = True) -> int:
    av = available()
    print("available:", av)
    if not _TORCH:
        print(f"-> torch indisponible ({av['torch_etat']}), selftest impossible ici.")
        print("   Relancer via run trusted_script path=app/forge_snn_router.py")
        return 1

    print("\n--- entrainement sur le corpus reel ---")
    r = SNNRouter()
    print("  ", r.fit_from_corpus(epochs=60))

    print("\n--- inference : deterministe ? ---")
    d1 = r.predict("analyse ce module python et corrige les bugs", "analyze_code")
    d2 = r.predict("analyse ce module python et corrige les bugs", "analyze_code")
    print("   passe 1:", d1)
    print("   passe 2:", d2)
    stable = (d1.provider == d2.provider
              and abs(d1.confidence - d2.confidence) < 1e-6)
    print("   [%s] deux appels identiques -> meme decision"
          % ("OK" if stable else "FAIL"))

    print("\n--- abstention sur une entree vide ---")
    print("   ", r.predict("", ""))

    print("\n--- validation croisee LOO (le vrai chiffre) ---")
    cv = cross_validate_loo(epochs=30, max_folds=12 if quick else None)
    for k in ("protocole", "bons", "faux", "abstentions", "accuracy_globale",
              "accuracy_si_repond", "taux_abstention"):
        print(f"   {k:22s}: {cv.get(k)}")
    print("   verdict:", cv.get("verdict"))
    return 0 if stable else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("=== forge_snn_router ===")
    if "--train" in sys.argv:
        _r = SNNRouter()
        print(_r.fit_from_corpus(epochs=int(os.environ.get("SNN_EPOCHS", "80"))))
        print("modele:", _r.save())
        sys.exit(0)
    if "--calibrate" in sys.argv:
        import json as _json

        print(_json.dumps(calibrate_thresholds(epochs=30, max_folds=None),
                          indent=2, ensure_ascii=False))
        sys.exit(0)
    if "--cv-ctf" in sys.argv:
        print(cross_validate_ctf_loo(max_folds=None))
        sys.exit(0)
    if "--cv-full" in sys.argv:
        print(cross_validate_loo(epochs=40, max_folds=None))
        sys.exit(0)
    sys.exit(_selftest(quick="--full" not in sys.argv))
