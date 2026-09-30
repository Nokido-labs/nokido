# -*- coding: utf-8 -*-
"""
forge_continual_backprop.py — Continual Backpropagation (Dohare et al., Nature 2024).
======================================================================================
Prévient la perte de plasticité dans les réseaux NumPy entraînés en continu
(value_net, policy_net, cost_net, world_model).

Algorithme : utilité neuronale = EMA(|W_in| × |W_out|).
Réinitialisation périodique des neurones sous le seuil ψ × mean_utility.
Poids entrants → He, poids sortants → 0, utilité → mean_utility.
"""

__FORGE_COLOR__ = "CYAN"

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class ContinualBackprop:
    """
    Continual Backpropagation pour réseaux NumPy SGD.

    Usage dans chaque net :
        # __init__ :
        self._cbp = ContinualBackprop(rng=rng)

        # backward(), après mise à jour des poids :
        self._cbp.update_utility("h1", self.W1, self.W2)
        self._cbp.update_utility("h2", self.W2, self.W3)  # si 3 couches

        # train(), fin de chaque itération :
        self._cbp.maybe_reinit([
            ("h1", self.W1, self.b1, self.W2),
            ("h2", self.W2, self.b2, self.W3),  # si 3 couches
        ])
    """

    def __init__(
        self,
        rng: Optional[np.random.Generator] = None,
        reinit_interval: int = 1000,
        utility_decay: float = 0.99,
        threshold_frac: float = 0.01,
    ) -> None:
        self._rng = rng if rng is not None else np.random.default_rng(0)
        self._interval = reinit_interval
        self._decay = utility_decay
        self._thresh = threshold_frac
        self._step = 0
        self._utility: dict = {}
        self.total_reinit: int = 0

    # ------------------------------------------------------------------

    def update_utility(self, name: str, W_in: np.ndarray, W_out: np.ndarray) -> None:
        """
        Met à jour l'EMA d'utilité pour une couche cachée.
        W_in  : [d_in, n_hidden]   — colonnes = poids entrants par neurone
        W_out : [n_hidden, d_out]  — lignes   = poids sortants par neurone
        """
        u = np.abs(W_in).mean(axis=0) * np.abs(W_out).mean(axis=1)
        if name not in self._utility:
            self._utility[name] = u.copy().astype(np.float64)
        else:
            self._utility[name] = self._decay * self._utility[name] + (1.0 - self._decay) * u

    def maybe_reinit(
        self,
        layers: List[Tuple[str, np.ndarray, np.ndarray, np.ndarray]],
    ) -> int:
        """
        Réinitialise les neurones morts tous les `interval` appels.

        layers : [(name, W_in, b_in, W_out), ...]
            W_in  [d_in, n]   modifié in-place → He init
            b_in  [n]         modifié in-place → 0
            W_out [n, d_out]  modifié in-place → 0 (stabilité aval)

        Retourne le nombre de neurones réinitialisés.
        """
        self._step += 1
        if self._step % self._interval != 0:
            return 0

        n_reinit = 0
        for name, W_in, b_in, W_out in layers:
            if name not in self._utility:
                continue
            u = self._utility[name]
            mean_u = float(u.mean())
            if mean_u == 0.0:
                continue
            dead = u < self._thresh * mean_u
            n_dead = int(dead.sum())
            if n_dead == 0:
                continue

            fan_in = W_in.shape[0]
            scale = float(np.sqrt(2.0 / fan_in))
            W_in[:, dead] = self._rng.standard_normal((fan_in, n_dead)).astype(W_in.dtype) * scale
            b_in[dead] = 0.0
            W_out[dead, :] = 0.0
            self._utility[name][dead] = mean_u
            n_reinit += n_dead

        self.total_reinit += n_reinit
        if n_reinit:
            logger.info("[CBP] step=%d reinit=%d total=%d", self._step, n_reinit, self.total_reinit)
        return n_reinit

    @property
    def stats(self) -> dict:
        return {
            "step": self._step,
            "total_reinit": self.total_reinit,
            "layers": {k: float(v.mean()) for k, v in self._utility.items()},
        }
