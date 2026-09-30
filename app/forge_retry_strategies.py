"""
app/forge_retry_strategies.py — Strategies de retry LLM-aware pour Nokido
===========================================================================
Trois additions a tenacity pour les appels cloud (Groq/Gemini/OpenRouter) :

  wait_retry_after    : lit le header HTTP Retry-After de la reponse 429
  wait_rpm_budget     : budget RPM partage cross-coroutines par provider
  retry_if_rate_limited : predicate detectant RateLimitError / httpx 429 / patterns

Usage dans forge_llm_router.py :
  from forge_retry_strategies import (
      wait_retry_after, wait_rpm_budget, retry_if_rate_limited
  )

  @retry(
      retry=retry_if_rate_limited(),
      wait=wait_rpm_budget("groq", rpm_limit=30),
      stop=stop_after_attempt(4),
  )
  async def call_groq(...): ...
"""

from __future__ import annotations

import time as _time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # RetryCallState importe en lazy pour eviter circulaire

try:
    from tenacity import wait_base, wait_exponential, retry_if_exception

    _TENACITY_OK = True
except ImportError:
    _TENACITY_OK = False

    class wait_base:  # type: ignore[misc]
        def __call__(self, retry_state: object) -> float:
            return 0.0

    class wait_exponential(wait_base):
        pass  # type: ignore[misc]

    class _FakeRetry:
        def __init__(self, fn):
            self.predicate = fn

        def __call__(self, rs):
            return self.predicate(getattr(rs, "outcome", rs))

    def retry_if_exception(fn):
        return _FakeRetry(fn)  # type: ignore[misc]


class wait_retry_after(wait_base):
    """Lit le header HTTP Retry-After de la reponse 429, fallback exponentiel.

    Args:
        fallback_wait: Duree d'attente si header absent (secondes).

    Example:
        @retry(wait=wait_retry_after(fallback_wait=2.0))
        async def call_api(): ...
    """

    def __init__(self, fallback_wait: float = 1.0) -> None:
        self.fallback_wait = fallback_wait

    def __call__(self, retry_state: object) -> float:
        """Calcule le temps d'attente depuis le header ou via fallback.

        Args:
            retry_state: Etat courant du retry tenacity.

        Returns:
            Nombre de secondes a attendre.
        """
        if retry_state.outcome is not None:
            exc = retry_state.outcome.exception()
            resp = getattr(exc, "response", None)
            if resp is not None:
                headers = getattr(resp, "headers", {}) or {}
                after = headers.get("Retry-After") or headers.get("retry-after")
                if after is not None:
                    try:
                        return float(after)
                    except (TypeError, ValueError):
                        pass
        return wait_exponential()(retry_state)

    def __repr__(self) -> str:
        return f"wait_retry_after(fallback_wait={self.fallback_wait})"


class wait_rpm_budget(wait_base):
    """Budget RPM partage entre toutes les coroutines du meme provider.

    Surveille le nombre d'appels dans la derniere minute.
    Si le seuil de 85% est atteint, attend la prochaine fenetre d'1 minute.

    Args:
        provider_key: Cle unique du provider (ex: "groq", "gemini").
        rpm_limit:    Limite RPM du provider (ex: 30 pour Groq gratuit).

    Example:
        wait = wait_rpm_budget("groq", rpm_limit=30)
        @retry(wait=wait, stop=stop_after_attempt(5))
        async def call_groq(): ...
    """

    _calls: "dict[str, list[float]]" = {}

    def __init__(self, provider_key: str = "default", rpm_limit: int = 30) -> None:
        self.provider_key = provider_key
        self.rpm_limit = rpm_limit

    def __call__(self, retry_state: object) -> float:
        """Calcule le delai pour respecter le budget RPM.

        Args:
            retry_state: Etat courant du retry tenacity.

        Returns:
            0.0 si sous le seuil, sinon secondes jusqu'a la prochaine fenetre.
        """
        now = _time.time()
        bucket = self._calls.setdefault(self.provider_key, [])
        self._calls[self.provider_key] = [t for t in bucket if now - t < 60]
        self._calls[self.provider_key].append(now)
        if len(self._calls[self.provider_key]) >= self.rpm_limit * 0.85:
            oldest = self._calls[self.provider_key][0]
            return min(60.0, max(1.0, oldest + 60.0 - now))
        return 0.0

    @classmethod
    def reset(cls, provider_key: str = "default") -> None:
        """Reinitialise le compteur RPM d'un provider.

        Args:
            provider_key: Cle du provider a reinitialiser.
        """
        cls._calls.pop(provider_key, None)

    def __repr__(self) -> str:
        return f"wait_rpm_budget(provider_key={self.provider_key}, rpm_limit={self.rpm_limit})"


def retry_if_rate_limited():
    """Predicate tenacity detectant les erreurs de rate limit LLM cloud.

    Detecte :
    - litellm.RateLimitError
    - httpx.HTTPStatusError avec status 429
    - Exception dont le message contient 'rate_limit', '429', 'quota', 'slow down'
    - TimeoutError (builtin Python 3.11+)

    Returns:
        retry_if_exception predicate utilisable avec @retry(retry=...)

    Example:
        @retry(
            retry=retry_if_rate_limited(),
            wait=wait_rpm_budget("groq", rpm_limit=30),
            stop=stop_after_attempt(4),
        )
        async def call_api(): ...
    """

    def _is_rate_limited(exc: Exception) -> bool:
        try:
            import litellm as _ll

            if isinstance(exc, _ll.RateLimitError):
                return True
        except ImportError:
            pass
        try:
            import httpx as _hx

            if isinstance(exc, _hx.HTTPStatusError):
                return exc.response.status_code == 429
        except ImportError:
            pass
        if isinstance(exc, TimeoutError):
            return True
        return any(kw in str(exc).lower() for kw in ("rate_limit", "429", "quota", "too many", "slow down"))

    return retry_if_exception(_is_rate_limited)


# ═══════════════════════════════════════════════════════════════════════════
# EXTENSIONS 2026-04 (PRIORITE 5 audit Gemini)
# ═══════════════════════════════════════════════════════════════════════════

import random as _random


class wait_exp_jitter(wait_base):
    """Backoff exponentiel avec jitter (AWS 'Full Jitter' algorithm).

    Evite le thundering herd quand plusieurs clients se reconnectent en meme temps
    apres une panne. Recommandee pour TOUS les appels cloud Nokido.

    Formule : sleep = random.uniform(0, min(cap, base * 2^attempt))

    Args:
        base: Delai de base en secondes (defaut 1.0).
        cap:  Delai max capture en secondes (defaut 60.0).
        jitter_ratio: Fraction de jitter 0..1 (defaut 1.0 = full jitter).

    Example:
        @retry(wait=wait_exp_jitter(base=1.0, cap=30.0), stop=stop_after_attempt(5))
        async def call_gemini(): ...
    """

    def __init__(self, base: float = 1.0, cap: float = 60.0, jitter_ratio: float = 1.0) -> None:
        self.base = base
        self.cap = cap
        self.jitter_ratio = max(0.0, min(1.0, jitter_ratio))

    def __call__(self, retry_state: object) -> float:
        """Calcule delai exponentiel avec jitter aleatoire.

        Args:
            retry_state: Etat courant du retry tenacity.

        Returns:
            Delai en secondes.
        """
        attempt = getattr(retry_state, "attempt_number", 1)
        exp = min(self.cap, self.base * (2 ** (attempt - 1)))
        if self.jitter_ratio <= 0.0:
            return exp
        min_wait = exp * (1.0 - self.jitter_ratio)
        return _random.uniform(min_wait, exp)

    def __repr__(self) -> str:
        return f"wait_exp_jitter(base={self.base}, cap={self.cap}, jitter={self.jitter_ratio})"


class CircuitBreaker:
    """State machine pour isoler un provider defaillant.

    Etats :
      - CLOSED : operations normales.
      - OPEN : provider suppose KO, echec immediat sans appel reseau.
      - HALF_OPEN : apres cooldown, 1 essai pour voir si recupere.

    Utilisation dans forge_llm_router pour sauter les providers down.

    Args:
        provider_key: Identifiant du provider (ex: "groq", "gemini").
        fail_threshold: Nb d'echecs consecutifs avant passage OPEN (defaut 5).
        recovery_time: Temps avant tentative HALF_OPEN en secondes (defaut 30).

    Example:
        cb = CircuitBreaker("gemini", fail_threshold=3, recovery_time=60)
        if cb.allow():
            try:
                result = call_gemini(...)
                cb.record_success()
            except Exception:
                cb.record_failure()
                raise
        else:
            # Skip ce provider, tenter suivant
            ...
    """

    _state: "dict[str, dict]" = {}

    def __init__(self, provider_key: str, fail_threshold: int = 5, recovery_time: float = 30.0) -> None:
        self.provider_key = provider_key
        self.fail_threshold = fail_threshold
        self.recovery_time = recovery_time
        if provider_key not in self._state:
            self._state[provider_key] = {
                "status": "CLOSED",
                "failures": 0,
                "open_since": 0.0,
            }

    @property
    def status(self) -> str:
        """Retourne l'etat courant ('CLOSED', 'OPEN', 'HALF_OPEN')."""
        st = self._state[self.provider_key]
        if st["status"] == "OPEN" and _time.time() - st["open_since"] >= self.recovery_time:
            st["status"] = "HALF_OPEN"
        return st["status"]

    def allow(self) -> bool:
        """True si un appel peut etre tente (CLOSED ou HALF_OPEN), False si OPEN."""
        return self.status != "OPEN"

    def record_success(self) -> None:
        """Enregistre un succes: reset compteur echecs, repasse en CLOSED."""
        st = self._state[self.provider_key]
        st["failures"] = 0
        st["status"] = "CLOSED"

    def record_failure(self) -> None:
        """Enregistre un echec. Ouvre le circuit si seuil atteint."""
        st = self._state[self.provider_key]
        st["failures"] += 1
        if st["failures"] >= self.fail_threshold:
            st["status"] = "OPEN"
            st["open_since"] = _time.time()

    @classmethod
    def reset(cls, provider_key: str) -> None:
        """Force un reset complet du circuit pour un provider."""
        cls._state[provider_key] = {
            "status": "CLOSED",
            "failures": 0,
            "open_since": 0.0,
        }

    @classmethod
    def snapshot(cls) -> dict:
        """Snapshot de l'etat de tous les providers (monitoring)."""
        now = _time.time()
        out = {}
        for k, v in cls._state.items():
            out[k] = {
                "status": v["status"],
                "failures": v["failures"],
                "open_since": v["open_since"],
                "time_since_open": (now - v["open_since"]) if v["open_since"] else None,
            }
        return out

    def __repr__(self) -> str:
        st = self._state[self.provider_key]
        return f"CircuitBreaker({self.provider_key}, status={st['status']}, failures={st['failures']})"
