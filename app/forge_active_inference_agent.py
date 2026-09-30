"""app/forge_active_inference_agent.py - agent inference active Friston.

Wrap pymdp (inferactively-pymdp 1.0.2+) pour Nokido. Cas d usage primaire :
cyber-defense - modele generatif d un "reseau sain", chaque observation
qui devie = surprise (KL divergence elevee), declenche action de retour
a l etat predit (isoler conteneur, kill process, etc.).

API minimale :
  agent = build_cyber_agent(n_states=4, n_obs=3, n_actions=3)
  agent.observe(obs_idx) -> belief posterior
  agent.choose_action() -> action_idx (minimise expected free energy)
  agent.surprise(obs_idx) -> float (KL belief vs prior)

Le modele genere A/B/C/D matrices random au demarrage. Pour vrai
deployment, A (likelihood) doit etre appris depuis traces production.

Dependencies : inferactively-pymdp + jax + jaxtyping + equinox + multimethod + mctx.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import numpy as np
    from pymdp.agent import Agent as _PymdpAgent
    from pymdp import utils as _pymdp_utils

    _PYMDP_OK = True
except ImportError:  # noqa: F401
    _PYMDP_OK = False


@dataclass
class CyberAgent:
    """Wrap Friston Agent autour d un policy "monitoring -> action".
    pymdp 1.0+ Agent expose : infer_states(obs, empirical_prior=...) /
    infer_policies / sample_action. On porte l empirical_prior d un step
    a l autre via self._last_post (init = agent.D au demarrage)."""

    pymdp_agent: Any  # pymdp.agent.Agent
    n_states: int
    n_obs: int
    n_actions: int
    _last_post: Any = None

    def _prior(self) -> Any:
        if self._last_post is not None:
            return self._last_post
        # Init prior = D (initial state distrib) si disponible, sinon uniforme
        return getattr(self.pymdp_agent, "D", None)

    def observe(self, obs_idx: int) -> Any:
        """Pousse une observation et retourne le posterior sur les etats.
        pymdp 1.0+ jax attend list[list[int]] (batch x modality) :
        [[obs_idx]] = batch_size=1, modality=1, obs=obs_idx.
        Legacy numpy api accepte list[int]."""
        if obs_idx < 0 or obs_idx >= self.n_obs:
            raise ValueError(f"obs_idx {obs_idx} hors [0, {self.n_obs})")
        # Format JAX moderne : batch=1, modality=1
        try:
            post = self.pymdp_agent.infer_states([[obs_idx]], empirical_prior=self._prior())
        except TypeError:
            try:
                post = self.pymdp_agent.infer_states([[obs_idx]])
            except TypeError:
                # legacy numpy
                post = self.pymdp_agent.infer_states([obs_idx])
        self._last_post = post
        return post

    def choose_action(self) -> int:
        """Inference de policies + sampling action discrete."""
        try:
            self.pymdp_agent.infer_policies()
            action = self.pymdp_agent.sample_action()
            return int(np.asarray(action).flatten()[0])
        except Exception:  # noqa: BLE001
            # Fallback : tirage uniforme si API absente ou cassee
            return int(np.random.randint(0, self.n_actions))

    def surprise(self, obs_idx: int) -> float:
        """KL entre prior et posterior = surprise effective."""
        prior = self._prior()
        post = self.observe(obs_idx)
        try:
            p_arr = np.asarray(post[0]).flatten()
            p_arr = p_arr / (p_arr.sum() + 1e-8)
            if prior is not None:
                q_arr = np.asarray(prior[0] if isinstance(prior, (list, tuple)) else prior).flatten()
                q_arr = q_arr / (q_arr.sum() + 1e-8)
            else:
                q_arr = np.ones_like(p_arr) / len(p_arr)
            kl = float(np.sum(p_arr * np.log((p_arr + 1e-8) / (q_arr + 1e-8))))
            return kl
        except Exception:  # noqa: BLE001
            return 0.0


def build_cyber_agent(n_states: int = 4, n_obs: int = 3, n_actions: int = 3, seed: int = 42) -> CyberAgent:
    """Construit un agent pymdp avec A/B aleatoires (placeholders).
    A : likelihood obs|state. B : transition state'|state, action.
    Pour vrai deployement : A appris via baum-welch sur traces sain/anomalie."""
    if not _PYMDP_OK:
        raise RuntimeError(
            "inferactively-pymdp non installe. pip install inferactively-pymdp jax jaxtyping equinox multimethod mctx"
        )
    import jax

    np.random.seed(seed)
    key = jax.random.PRNGKey(seed)
    A = _pymdp_utils.random_A_array(num_obs=[n_obs], num_states=[n_states], key=key)
    key2 = jax.random.split(key)[0]
    B = _pymdp_utils.random_B_array(num_states=[n_states], num_controls=[n_actions], key=key2)
    ag = _PymdpAgent(A=A, B=B)
    return CyberAgent(pymdp_agent=ag, n_states=n_states, n_obs=n_obs, n_actions=n_actions)


def available() -> bool:
    return _PYMDP_OK
