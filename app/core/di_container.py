"""
app/core/di_container.py - Dependency Injection Container pour Nokido.

VISION (Gemini audit 2026-04):
  "Un module dedie serait le seul endroit ou les dependances sont instanciees
  et assemblees. Il gererait le cycle de vie des objets (singleton, transient,
  scoped)."

OBJECTIF :
  Centraliser l instanciation et l assemblage des services Nokido.
  Permettre une migration progressive depuis les imports directs vers la DI.

USAGE DE BASE:
    from app.core.di_container import get_container

    container = get_container()
    facade = container.get("facade")
    afacade = container.get("async_facade")
    settings = container.get("settings")

USAGE AVANCE (injection):
    class MyFeature:
        def __init__(self, container=None):
            self._c = container or get_container()

        def run(self):
            return self._c.get("facade").rag_query("...")

TESTING (swap):
    container = DIContainer()
    container.register("facade", lambda: MyMockFacade())

PATTERN :
  - Services enregistres via factories (lazy instantiation)
  - Singleton par defaut (memoise au premier get())
  - transient=True pour forcer une nouvelle instance a chaque get()
  - reset() pour tests

NON-BREAKING :
  - Container est un NOUVEAU mecanisme. Pas de modification du code existant.
  - Les modules peuvent GRADUELLEMENT passer des imports directs au container.
  - Tant que le container n est pas utilise, rien ne change.
"""

import asyncio
from typing import Any, Callable, Dict, Optional, Awaitable


class DIContainer:
    """
    Container simple de dependency injection pour Nokido.

    Supporte :
    - Services synchrones (singleton ou transient)
    - Services asynchrones (register_async / get_async)
    - Cycle de vie (startup pour warm-up, shutdown pour cleanup)
    """

    def __init__(self) -> None:
        """Initialise un container vide avec caches separes."""
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._singletons: Dict[str, Any] = {}
        self._transient: set[str] = set()

        # Support async
        self._async_factories: Dict[str, Callable[[], Awaitable[Any]]] = {}
        self._async_singletons: Dict[str, Any] = {}
        self._lock = asyncio.Lock()  # Pour thread-safety/coro-safety sur l'init async

    def register(self, name: str, factory: Callable[[], Any], transient: bool = False) -> None:
        """Enregistre un service via sa factory.

        Args:
            name: Cle unique du service (ex: "facade", "settings").
            factory: Callable sans args qui retourne l instance.
            transient: Si True, nouvelle instance a chaque get(). Sinon singleton.
        """
        self._factories[name] = factory
        if transient:
            self._transient.add(name)
        # Invalider le singleton si register a nouveau
        self._singletons.pop(name, None)

    def register_async(self, name: str, coro_factory: Callable[[], Awaitable[Any]]) -> None:
        """Enregistre une factory asynchrone (coroutine def)."""
        self._async_factories[name] = coro_factory
        self._async_singletons.pop(name, None)

    def get(self, name: str) -> Any:
        """Recupere un service par nom (version synchrone).

        Returns:
            L instance du service (singleton memoise sauf si transient).

        Raises:
            KeyError: Si le service n est pas enregistre.
        """
        if name not in self._factories:
            raise KeyError(f"Service '{name}' non enregistre (sync) dans le container")
        if name in self._transient:
            return self._factories[name]()
        if name not in self._singletons:
            self._singletons[name] = self._factories[name]()
        return self._singletons[name]

    async def get_async(self, name: str) -> Any:
        """Recupere un service async (singleton avec lock d'init).

        Args:
            name: Nom du service.

        Returns:
            L instance du service async (memoisee).
        """
        if name not in self._async_factories:
            # Fallback sur get sync si non trouve en async
            if name in self._factories:
                import logging

                logging.getLogger("Nokido.DI").warning(
                    f"Fallback sync pour le service async '{name}'. "
                    "Risque de blocage de l'event loop si le service est I/O-bound."
                )
                return self.get(name)
            raise KeyError(f"Service '{name}' non enregistre (async/sync) dans le container")

        if name not in self._async_singletons:
            async with self._lock:
                # Double check pattern
                if name not in self._async_singletons:
                    self._async_singletons[name] = await self._async_factories[name]()
        return self._async_singletons[name]

    async def startup(self) -> None:
        """Warm-up : initialise tous les singletons async enregistres."""
        for name in list(self._async_factories.keys()):
            await self.get_async(name)

    async def shutdown(self) -> None:
        """Fermeture propre des services (aclose/close).

        Tente d'appeler aclose() ou close() sur tous les singletons (sync et async).
        """
        all_svcs = list(self._singletons.items()) + list(self._async_singletons.items())
        for name, svc in all_svcs:
            try:
                if hasattr(svc, "aclose") and callable(svc.aclose):
                    await svc.aclose()
                elif hasattr(svc, "close") and callable(svc.close):
                    if asyncio.iscoroutinefunction(svc.close):
                        await svc.close()
                    else:
                        svc.close()
            except Exception:
                pass  # Erreur de fermeture ignoree silencieusement

    def has(self, name: str) -> bool:
        """Verifie si un service est enregistre."""
        return name in self._factories or name in self._async_factories

    def list_services(self) -> list[str]:
        """Liste les noms des services enregistres."""
        return list(self._factories.keys())

    def reset(self, name: Optional[str] = None) -> None:
        """Reset les singletons memoises.

        Args:
            name: Si fourni, reset uniquement ce service. Sinon, tout.
        """
        if name is None:
            self._singletons.clear()
        else:
            self._singletons.pop(name, None)

    def clear(self) -> None:
        """Remove tous les services (factories + singletons)."""
        self._factories.clear()
        self._singletons.clear()
        self._transient.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Factory par defaut : assemblage canonique Nokido
# ═══════════════════════════════════════════════════════════════════════════


def _build_default_container() -> DIContainer:
    """Construit le container par defaut avec tous les services Nokido."""
    c = DIContainer()

    # Facade (sync) - singleton
    def _facade_factory():
        from app.api_facade import get_facade

        return get_facade()

    c.register("facade", _facade_factory)

    # Facade (async) - singleton
    def _async_facade_factory():
        from app.api_facade import get_async_facade

        return get_async_facade()

    c.register("async_facade", _async_facade_factory)

    # Settings - singleton via app.core.settings
    def _settings_factory():
        from app.core.settings import get_settings

        return get_settings()

    c.register("settings", _settings_factory)

    # Circuit breakers snapshot - transient (etat courant change)
    def _breakers_factory():
        try:
            from nokido_agent.app.forge_llm_router import get_circuit_breakers_snapshot

            return get_circuit_breakers_snapshot()
        except ImportError:
            return {}

    c.register("breakers_snapshot", _breakers_factory, transient=True)

    # Settings domains - singleton (statique)
    def _domains_factory():
        from app.core.settings.fields import list_domains

        return list_domains()

    c.register("settings_domains", _domains_factory)

    # Protocols - singleton
    def _protocols_factory():
        from app import protocols

        return {
            "LLMBridgeProtocol": protocols.LLMBridgeProtocol,
            "AppContextProtocol": protocols.AppContextProtocol,
            "VersionManagerProtocol": protocols.VersionManagerProtocol,
            "WebSearchProtocol": protocols.WebSearchProtocol,
            "RAGEngineProtocol": protocols.RAGEngineProtocol,
        }

    c.register("protocols", _protocols_factory)

    # Payload Validator - singleton
    def _payload_validator_factory():
        from app.core.payload_validator import PayloadValidator

        return PayloadValidator()

    c.register("payload_validator", _payload_validator_factory)

    # PowerShell Sandbox -- transient (nouvelle instance par appel)
    def _ps_runner_factory():
        from nokido_agent.app.forge_ps_sandbox import PowerShellSandbox

        return PowerShellSandbox(mode="CLM", timeout=15)

    c.register("ps_runner", _ps_runner_factory, transient=True)

    # Intent Router (circuit-court semantique v18.5)
    def _intent_router_factory():
        from app.services.intent_router import IntentRouter

        return IntentRouter()

    c.register("intent_router", _intent_router_factory)

    # Circadian Loop — daemon background processing
    def _circadian_factory():
        from nokido_agent.app.forge_circadian_loop import get_circadian_loop

        return get_circadian_loop()

    c.register("circadian_loop", _circadian_factory)

    return c


# ═══════════════════════════════════════════════════════════════════════════
# Singleton global du container par defaut
# ═══════════════════════════════════════════════════════════════════════════


_global_container: Optional[DIContainer] = None


def get_container() -> DIContainer:
    """Retourne le container global Nokido (build au premier appel)."""
    global _global_container
    if _global_container is None:
        _global_container = _build_default_container()
    return _global_container


def set_container(container: DIContainer) -> None:
    """Remplace le container global (pour tests ou config custom)."""
    global _global_container
    _global_container = container


def reset_container() -> None:
    """Reset le container global (force reconstruction au prochain get_container)."""
    global _global_container
    _global_container = None


__all__ = [
    "DIContainer",
    "get_container",
    "set_container",
    "reset_container",
]
