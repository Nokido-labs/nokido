"""
app/api_facade.py - Facade API unifiee pour Nokido (decouplage UI/backend).

CONTEXTE (audit Gemini 2026-04):
  Nokido.py (189KB, 4890 lignes) importe directement 40 modules backend :
  - security (forge_code, forge_conv_sanitizer)
  - agents (forge_agents, forge_orchestrator)
  - llm (forge_ollama, forge_llamacpp, forge_gemini_bridge)
  - rag (forge_rag_engine, forge_rag_warmup)
  - orchestration (forge_at_dispatch, forge_dispatch_ai, forge_compose)
  - ...

Cette facade expose une API STABLE et SIMPLE. Le nouveau code (tests, refacto UI,
scripts tiers) peut importer UNIQUEMENT cette facade, sans se soucier des
implementations sous-jacentes.

USAGE RECOMMANDE:
    from app.api_facade import NokidoFacade

    facade = NokidoFacade()
    answer = await facade.ask_llm("explique le code ci-dessous")
    results = facade.rag_query("comment fonctionne le routing")
    status = facade.agents_status()

ARCHITECTURE:
  - Lazy imports : la facade n initialise rien au import, tout est lazy-loaded
    pour eviter de tirer tout le backend inutilement
  - Retrocompat : si une methode echoue (module manquant), elle retourne
    un placeholder au lieu de crasher
  - Type hints : toutes les methodes sont typees pour IDE/mypy

Phase 1 (FAIT 2026-04) : facade vide avec signature complete et lazy imports
Phase 2 (TODO)         : brancher chaque methode sur le backend reel
Phase 3 (TODO)         : Nokido.py delegue a cette facade au lieu d importer
                         directement
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class NokidoFacade:
    """
    Facade d acces au cerveau souverain Nokido.

    Regroupe les APIs par domaine :
    - LLM : ask_llm, ask_cascade, list_models
    - RAG : rag_query, rag_index, rag_status
    - Agents : agents_status, agents_dispatch, agents_evolve
    - Security : scan_code, danger_check
    - Orchestration : dispatch, compose, run_mode

    Toutes les methodes sont synchrones pour la simplicite. Les versions
    async sont suffixees _async.
    """

    def __init__(self) -> None:
        """Initialise la facade (lazy : aucun import backend)."""
        self._modules_cache: Dict[str, Any] = {}

    def _lazy_import(self, module_name: str) -> Optional[Any]:
        """Import lazy d un module backend avec cache et tolerance aux erreurs."""
        if module_name in self._modules_cache:
            return self._modules_cache[module_name]
        try:
            import importlib

            mod = importlib.import_module(module_name)
            self._modules_cache[module_name] = mod
            return mod
        except ImportError:
            self._modules_cache[module_name] = None
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # LLM
    # ═══════════════════════════════════════════════════════════════════════

    def ask_llm(self, prompt: str, backend: str = "ollama", context: str = "", **kwargs: Any) -> str:
        """
        Envoie un prompt a un backend LLM specifique.

        Args:
            prompt: Le prompt utilisateur.
            backend: 'ollama', 'llamacpp', 'gemini', 'litellm', 'openrouter'.
            context: Contexte additionnel optionnel.
            **kwargs: Params backend-specific (temperature, max_tokens, etc).

        Returns:
            La reponse texte du LLM, ou message d erreur en str.
        """
        backend_map = {
            "ollama": "forge_ollama_bridge",
            "llamacpp": "forge_llamacpp",
            "gemini": "forge_gemini_bridge",
            "litellm": "forge_litellm_bridge",
            "openrouter": "forge_openrouter",
        }
        mod_name = backend_map.get(backend)
        if not mod_name:
            return f"[facade] backend inconnu: {backend}"
        mod = self._lazy_import(mod_name)
        if mod is None:
            return f"[facade] module indisponible: {mod_name}"
        # Essai d appel uniforme
        for fn_name in ("ask", "query", "generate", f"{backend}_ask"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    return fn(prompt, context=context, **kwargs) if context else fn(prompt, **kwargs)
                except TypeError:
                    # Signature differente, essayer sans kwargs
                    try:
                        return fn(prompt)
                    except Exception as e:
                        return f"[facade] erreur {backend}: {e}"
                except Exception as e:
                    return f"[facade] erreur {backend}: {e}"
        return f"[facade] aucune fonction ask/query/generate dans {mod_name}"

    def list_models(self, backend: str = "ollama") -> List[str]:
        """Liste les modeles disponibles d un backend."""
        mod = self._lazy_import("forge_ollama" if backend == "ollama" else f"forge_{backend}")
        if mod is None:
            return []
        fn = getattr(mod, "list_models", None) or getattr(mod, "get_models", None)
        if callable(fn):
            try:
                return list(fn())
            except Exception:
                return []
        return []

    # ═══════════════════════════════════════════════════════════════════════
    # RAG
    # ═══════════════════════════════════════════════════════════════════════

    def rag_query(self, text: str, k: int = 5) -> List[Dict]:
        """
        Recherche semantique dans le RAG.

        Args:
            text: Requete en langage naturel.
            k: Nombre de resultats top-k a retourner.

        Returns:
            Liste de dicts {score, text, meta}.
        """
        mod = self._lazy_import("forge_rag_engine")
        if mod is None:
            return []
        fn = getattr(mod, "query", None) or getattr(mod, "search", None)
        if callable(fn):
            try:
                return list(fn(text, k=k))
            except Exception:
                return []
        return []

    def rag_status(self) -> Dict[str, Any]:
        """Statut du moteur RAG (nb documents, derniere mise a jour, etc)."""
        mod = self._lazy_import("forge_rag_engine")
        if mod is None:
            return {"status": "unavailable"}
        fn = getattr(mod, "status", None)
        if callable(fn):
            try:
                return dict(fn())
            except Exception as e:
                return {"status": "error", "error": str(e)}
        return {"status": "unknown"}

    # ═══════════════════════════════════════════════════════════════════════
    # Agents
    # ═══════════════════════════════════════════════════════════════════════

    def agents_status(self) -> Dict[str, Any]:
        """Statut des agents (mode actif, roles assignes, etc)."""
        mod = self._lazy_import("app.agents")
        if mod is None:
            mod = self._lazy_import("forge_agents")
        if mod is None:
            return {"status": "unavailable"}
        try:
            router = None
            get_router = getattr(mod, "get_router", None)
            if callable(get_router):
                router = get_router()
            return {
                "status": "ok",
                "router_type": type(router).__name__ if router else None,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════
    # Security
    # ═══════════════════════════════════════════════════════════════════════

    def scan_code(self, code: str, language: str = "python") -> Dict[str, Any]:
        """
        Analyse un bloc de code pour detecter des patterns dangereux.

        Args:
            code: Source a analyser.
            language: Langage (python par defaut).

        Returns:
            Dict avec keys: safe (bool), issues (list), patterns_detected (list).
        """
        mod = self._lazy_import("forge_code_guard")
        if mod is None:
            mod = self._lazy_import("forge_code")
        if mod is None:
            return {"safe": True, "issues": [], "warning": "module indisponible"}
        scan_fn = getattr(mod, "scan", None) or getattr(mod, "check_code", None) or getattr(mod, "analyze", None)
        if callable(scan_fn):
            try:
                result = scan_fn(code)
                return dict(result) if hasattr(result, "keys") else {"result": result}
            except Exception as e:
                return {"safe": False, "error": str(e)}
        return {"safe": True, "issues": [], "warning": "fonction scan non trouvee"}

    # ═══════════════════════════════════════════════════════════════════════
    # Settings (utilise le nouveau split par domaine)
    # ═══════════════════════════════════════════════════════════════════════

    def settings_get(self, key: str, default: Any = None) -> Any:
        """Recupere une valeur de settings depuis forge_settings.Settings."""
        mod = self._lazy_import("forge_settings")
        if mod is None:
            return default
        fn = getattr(mod, "get_settings", None) or getattr(mod, "create_settings", None)
        if callable(fn):
            try:
                s = fn()
                return getattr(s, key, default)
            except Exception:
                return default
        return default

    def settings_domains(self) -> List[str]:
        """Liste les domaines de settings (ssh/ollama/rag/etc)."""
        mod = self._lazy_import("app.core.settings.fields")
        if mod is None:
            return []
        fn = getattr(mod, "list_domains", None)
        if callable(fn):
            try:
                return list(fn())
            except Exception:
                return []
        return []


# ═══════════════════════════════════════════════════════════════════════════
# Singleton global (pour simplifier les usages simples)
# ═══════════════════════════════════════════════════════════════════════════

_facade_instance: Optional[NokidoFacade] = None


def get_facade() -> NokidoFacade:
    """Retourne l instance singleton de la facade Nokido."""
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = NokidoFacade()
    return _facade_instance


# ═══════════════════════════════════════════════════════════════════════════
# VERSION ASYNC (Option F, audit Gemini 2026-04)
# ═══════════════════════════════════════════════════════════════════════════

import asyncio
from typing import Awaitable


class AsyncNokidoFacade:
    """
    Version async de NokidoFacade pour UI non-bloquantes et pipelines asyncio.

    Les backends LLM modernes sont souvent async (aiohttp, httpx AsyncClient,
    litellm acompletion). Cette facade expose leurs methodes sans bloquer
    l event loop.

    Pattern : wrap les fonctions sync via asyncio.to_thread() par defaut,
    mais detecte et prefere les methodes _async natives quand elles existent.

    Validation : utilise PayloadValidator injecte via le DIContainer.
    """

    def __init__(self, container=None) -> None:
        """Init sync facade as delegate and resolve validator."""
        self._sync = NokidoFacade()
        from app.core.di_container import get_container

        self._container = container or get_container()

    async def _run_in_thread(self, fn, *args, **kwargs):
        """Execute une fn sync dans un thread pour ne pas bloquer le loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _try_async_method(self, mod: Any, names: list, *args, **kwargs):
        """Cherche une methode _async sur le module, fallback sur sync via thread."""
        for name in names:
            fn = getattr(mod, name, None)
            if not callable(fn):
                continue
            try:
                # Si c est une coroutine function, await direct
                if asyncio.iscoroutinefunction(fn):
                    return await fn(*args, **kwargs)
                # Sinon wrap en thread
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as e:
                return f"[facade-async] erreur {name}: {e}"
        return None

    async def ask_llm_async(
        self, prompt_or_payload: str | Dict[str, Any], backend: str = "ollama", context: str = "", **kwargs: Any
    ) -> str:
        """
        Version async de ask_llm avec validation de payload.
        """
        # 1. Normalisation et Validation du payload
        if isinstance(prompt_or_payload, str):
            payload = {"messages": [{"role": "user", "content": prompt_or_payload}]}
            if context:
                payload["messages"].insert(0, {"role": "system", "content": context})
        else:
            payload = prompt_or_payload

        # Validation via DI
        if self._container.has("payload_validator"):
            validator = self._container.get("payload_validator")
            ok, err = validator.validate_payload(payload)
            if not ok:
                return f"[facade-async] payload invalide: {err}"

        # 2. Resolution du backend et appel
        backend_map = {
            "ollama": "forge_ollama_bridge",
            "llamacpp": "forge_llamacpp",
            "gemini": "forge_gemini_bridge",
            "litellm": "forge_litellm_bridge",
            "openrouter": "forge_openrouter",
        }
        mod_name = backend_map.get(backend)
        if not mod_name:
            return f"[facade-async] backend inconnu: {backend}"
        mod = self._sync._lazy_import(mod_name)
        if mod is None:
            return f"[facade-async] module indisponible: {mod_name}"

        # Extraction du prompt texte pour les bridges ne supportant pas le format messages complet
        prompt_text = payload["messages"][-1]["content"] if "messages" in payload else str(prompt_or_payload)

        # Essai : ask_async, aask, ask (wrap thread), query_async, generate_async
        for fn_name in (f"{backend}_ask_async", "ask_async", "aask", "query_async", "generate_async"):
            fn = getattr(mod, fn_name, None)
            if callable(fn) and asyncio.iscoroutinefunction(fn):
                try:
                    # Tenter avec le payload complet d'abord
                    try:
                        return await fn(payload, **kwargs)
                    except TypeError:
                        # Fallback signature classique (prompt, context)
                        return (
                            await fn(prompt_text, context=context, **kwargs)
                            if context
                            else await fn(prompt_text, **kwargs)
                        )
                except Exception as e:
                    return f"[facade-async] erreur {backend}: {e}"

        # Fallback sync in thread
        return await asyncio.to_thread(self._sync.ask_llm, prompt_text, backend=backend, context=context, **kwargs)

    async def rag_query_async(self, text: str, k: int = 5) -> List[Dict]:
        """Version async de rag_query."""
        mod = self._sync._lazy_import("forge_rag_engine")
        if mod is None:
            return []
        for fn_name in ("query_async", "aquery", "search_async"):
            fn = getattr(mod, fn_name, None)
            if callable(fn) and asyncio.iscoroutinefunction(fn):
                try:
                    return list(await fn(text, k=k))
                except Exception:
                    pass
        # Fallback
        return await asyncio.to_thread(self._sync.rag_query, text, k=k)

    async def agents_status_async(self) -> Dict[str, Any]:
        """Version async de agents_status."""
        return await asyncio.to_thread(self._sync.agents_status)

    async def rag_status_async(self) -> Dict[str, Any]:
        """Version async de rag_status."""
        return await asyncio.to_thread(self._sync.rag_status)

    async def scan_code_async(self, code: str, language: str = "python") -> Dict[str, Any]:
        """Version async de scan_code."""
        return await asyncio.to_thread(self._sync.scan_code, code, language)

    async def list_models_async(self, backend: str = "ollama") -> List[str]:
        """Version async de list_models."""
        return await asyncio.to_thread(self._sync.list_models, backend)


# ═══════════════════════════════════════════════════════════════════════════
# Singleton async
# ═══════════════════════════════════════════════════════════════════════════

_async_facade_instance: Optional[AsyncNokidoFacade] = None


def get_async_facade() -> AsyncNokidoFacade:
    """Retourne l instance singleton de la facade async."""
    global _async_facade_instance
    if _async_facade_instance is None:
        _async_facade_instance = AsyncNokidoFacade()
    return _async_facade_instance


__all__ = ["NokidoFacade", "AsyncNokidoFacade", "get_facade", "get_async_facade"]
