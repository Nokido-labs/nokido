"""
app/protocols.py - Interfaces (typing.Protocol) pour casser les cycles d'import.

PATTERN DETECTE (audit Gemini 2026-04):
  Plusieurs modules Nokido ont des imports circulaires "lazy" (dans fonctions) :
    - forge_collab_modes <-> forge_gemini_bridge  (gemini_ask/_nokido_ask)
    - forge_litellm_bridge <-> forge_ollama_bridge  (get_bridge/ask)
    - forge_app_context <-> forge_versioning  (VersionManager/app_ctx)
    - forge_app_context <-> forge_web  (is_web_search_enabled/app_ctx)

Ces cycles ne bloquent pas a l'execution (imports dans fonctions), mais ils
indiquent un couplage excessif. Les Protocols ci-dessous permettent une
migration progressive vers la dependency injection.

USAGE :
  # Dans forge_collab_modes.py (au lieu de from forge_gemini_bridge import gemini_ask):
  from app.protocols import LLMBridgeProtocol

  class Orchestrator:
      def __init__(self, gemini: LLMBridgeProtocol, ollama: LLMBridgeProtocol):
          self.gemini = gemini
          self.ollama = ollama

  # Dans forge_gemini_bridge.py (on continue d'exposer gemini_ask):
  def gemini_ask(prompt: str, context: str = "") -> str:
      ...  # impl concrete, respecte le Protocol par duck typing

Les Protocols ne sont PAS obligatoires. Ils documentent l'interface attendue
et permettent au type-checker (mypy/pyright) de valider les assemblages.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/base : interfaces typing.Protocol contre les cycles d'import"  # organe declare le 2026-09-06 (audit de raccordement)

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMBridgeProtocol(Protocol):
    """Interface commune pour tous les bridges LLM (Gemini, Ollama, LiteLLM, LLamacpp)."""

    def ask(self, prompt: str, context: str = "", **kwargs: Any) -> str:
        """Envoie un prompt au backend et retourne la reponse."""
        ...


@runtime_checkable
class AppContextProtocol(Protocol):
    """Interface du contexte applicatif global (forge_app_context.app_ctx)."""

    def get(self, key: str, default: Any = None) -> Any:
        """Retourne une valeur du contexte."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Definit une valeur dans le contexte."""
        ...


@runtime_checkable
class VersionManagerProtocol(Protocol):
    """Interface de gestion de version (forge_versioning.VersionManager)."""

    def current_version(self) -> str:
        """Retourne la version active."""
        ...

    def bump(self, level: str = "patch") -> str:
        """Incremente la version (major/minor/patch) et retourne la nouvelle."""
        ...


@runtime_checkable
class WebSearchProtocol(Protocol):
    """Interface de recherche web (forge_web)."""

    def is_enabled(self) -> bool:
        """True si le web search est active."""
        ...

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Execute une recherche web."""
        ...


@runtime_checkable
class RAGEngineProtocol(Protocol):
    """Interface du moteur RAG (forge_rag_engine)."""

    def query(self, text: str, k: int = 5) -> list[dict]:
        """Recherche semantique dans le RAG."""
        ...

    def index(self, doc: dict) -> None:
        """Indexe un document dans le RAG."""
        ...


__all__ = [
    "LLMBridgeProtocol",
    "AppContextProtocol",
    "VersionManagerProtocol",
    "WebSearchProtocol",
    "RAGEngineProtocol",
]
