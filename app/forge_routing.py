"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:
#FORGE:[score:80|agent:unknown|temp:0.30|risk:0.00|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:80|agent:unknown|temp:0.30|risk:0.00|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

import logging
from typing import Optional, Any, Dict

from app.core.settings import get_settings as _forge_settings  # noqa: F401


class _SettingsProxy:
    """
    Proxy for accessing dynamic settings.

    Provides attribute-style access to settings returned by :func:`forge_settings.get_settings`.
    If the settings object is unavailable or the requested attribute does not exist,
    ``None`` is returned.

    Example:
        >>> proxy = _SettingsProxy()
        >>> value = proxy.some_setting

    Args:
        None

    Returns:
        _SettingsProxy instance

    Raises:
        None
    """

    def __init__(self) -> None:
        """Initialize the _SettingsProxy instance."""
        pass

    def __getattr__(self, k: str) -> object:
        """
        Get the attribute from the settings.

        Args:
            k (str): The attribute name.

        Returns:
            object: The attribute value or None if not found.

        Raises:
            None
        """
        s = _forge_settings()
        return getattr(s, k, None) if s else None


settings = _SettingsProxy()


logger = logging.getLogger(__name__)

# =============================================================================
# Ré-exports depuis forge_agents
# =============================================================================
try:
    from nokido_agent.app.forge_agents import (
        # Pipeline de routage
        SmartRouter,
        OllamaParallelRunner,
        PromptClassifier,
        AgentPlanner,
        AgentSynthesizer,
        # Types de données
        PromptCategory,
        RouteResult,
        AgentContrib,
        AGENT_BY_KEY,
        # Fonctions singleton
        init_router,
        get_router,
    )

    HAS_ROUTING = True
except ImportError as _e:
    logger.warning("[forge_routing] forge_agents indisponible : %s", _e)
    HAS_ROUTING = False
    AGENT_BY_KEY = {}

    # Stubs minimaux pour que Nokido.py reste importable
    class SmartRouter:  # type: ignore
        """
        Routeur.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        async def route(self, *a, **kw) -> None:
            """
            Route the request.

            Args:
                *a: Variable arguments.
                **kw: Keyword arguments.

            Returns:
                None

            Raises:
                None
            """
            return None

    class OllamaParallelRunner:  # type: ignore
        """
        Initialiseur.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        def __init__(self, *a, **kw) -> None:
            """
            Initialize the OllamaParallelRunner instance.

            Args:
                *a: Variable arguments.
                **kw: Keyword arguments.

            Returns:
                None

            Raises:
                None
            """
            pass

    class PromptClassifier:  # type: ignore
        """
        Initialiseur.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        def __init__(self, *a, **kw) -> None:
            """
            Initialize the PromptClassifier instance.

            Args:
                *a: Variable arguments.
                **kw: Keyword arguments.

            Returns:
                None

            Raises:
                None
            """
            pass

    class AgentPlanner:  # type: ignore
        """
        Initialiseur.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        def __init__(self, *a, **kw) -> None:
            """
            Initialize the AgentPlanner instance.

            Args:
                *a: Variable arguments.
                **kw: Keyword arguments.

            Returns:
                None

            Raises:
                None
            """
            pass

    class AgentContrib:  # type: ignore
        """
        Agent contribution.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        pass

    class PromptCategory:  # type: ignore
        """
        Prompt category.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        pass

    class RouteResult:  # type: ignore
        """
        Route result.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """

        pass

    def init_router(*a, **kw) -> None:
        """
        Initialize the router.

        Args:
            *a: Variable arguments.
            **kw: Keyword arguments.

        Returns:
            None

        Raises:
            None
        """
        return None  # type: ignore

    def get_router() -> None:
        """
        Get the router.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        return None  # type: ignore


# =============================================================================
# API simplifiée : build_router
# =============================================================================

_router_instance: Optional["SmartRouter"] = None


def build_router(
    settings: Any,
    web_engine: Optional[Any] = None,
    rag_engine: Optional[Any] = None,
    scorer: Optional[Any] = None,
    max_concurrent: int = 4,
) -> Optional["SmartRouter"]:
    """
    Construit (ou retourne) le SmartRouter singleton.

    Args:
        settings (Any): objet Settings de Nokido (ssh_host, ollama_url…)
        web_engine (Optional[Any]): instance WebSearchEngine (optionnel)
        rag_engine (Optional[Any]): instance RAGEngine (optionnel)
        scorer (Optional[Any]): instance ModelScorer (optionnel)
        max_concurrent (int): nb max d'appels Ollama parallèles

    Returns:
        SmartRouter configuré, ou None si forge_agents est absent.

    Raises:
        Exception: If an error occurs during initialization.
    """
    global _router_instance
    if not HAS_ROUTING:
        return None
    if _router_instance is not None:
        return _router_instance

    try:
        ollama_url = getattr(settings, "ollama_url", "http://localhost:11434/api/chat")
        _router_instance = init_router(
            ollama_url=ollama_url,
            max_concurrent=max_concurrent,
            web_engine=web_engine,
            rag_engine=rag_engine,
            scorer=scorer,
        )
        logger.info(
            "[forge_routing] SmartRouter initialisé (url=%s, parallel=%d)",
            ollama_url,
            max_concurrent,
        )
        return _router_instance
    except Exception as e:
        logger.warning("[forge_routing] build_router échec : %s", e)
        return None


def reset_router() -> None:
    """
    Réinitialise le singleton (utile pour les tests ou le hot-reload).

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    global _router_instance
    _router_instance = None

    try:
        from nokido_agent.app import forge_agents as _fa

        _fa._global_router = None
        _fa._global_runner = None
        _fa._global_classifier = None
        _fa._global_planner = None
    except Exception:
        pass

    logger.info("[forge_routing] SmartRouter reset")


def router_status() -> Dict[str, Any]:
    """
    Retourne un dict de statut du router (pour @status).

    Args:
        None

    Returns:
        Dict[str, Any]: The router status.

    Raises:
        None
    """
    r = get_router()
    if r is None:
        return {"available": False, "reason": "HAS_ROUTING=False" if not HAS_ROUTING else "non initialisé"}
    return {
        "available": True,
        "models_cached": len(getattr(r, "_models", [])),
        "has_web": r.web_engine is not None,
        "has_rag": r.rag_engine is not None,
        "has_scorer": r.scorer is not None,
    }


__all__ = [
    # Classes
    "SmartRouter",
    "OllamaParallelRunner",
    "PromptClassifier",
    "AgentPlanner",
    "AgentSynthesizer",
    "RouteResult",
    "PromptCategory",
    "AgentContrib",
    "AGENT_BY_KEY",
    # Fonctions
    "build_router",
    "get_router",
    "reset_router",
    "router_status",
    "init_router",
    # Flag
    "HAS_ROUTING",
]
