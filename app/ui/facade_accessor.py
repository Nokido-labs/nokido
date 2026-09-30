"""
app/ui/facade_accessor.py - Point d acces UI vers NokidoFacade.

OBJECTIF (Option G, audit Gemini 2026-04):
  Permettre aux NOUVELLES features UI d utiliser la facade au lieu d importer
  directement les modules backend. Facilite la migration progressive de
  Nokido.py (189KB, 40 imports directs).

USAGE dans code UI existant:
    from app.ui.facade_accessor import get_ui_facade

    async def on_user_prompt(prompt):
        facade = get_ui_facade()
        answer = await facade.ask_llm_async(prompt, backend="gemini")
        return answer

USAGE pour widgets Textual:
    from app.ui.facade_accessor import attach_facade_to_app

    class NokidoApp(App):
        def on_mount(self):
            attach_facade_to_app(self)  # ajoute self.facade et self.afacade
            # Maintenant : self.afacade.ask_llm_async(...) disponible

PROGRESSION:
  Phase 1 (DONE 2026-04) : accesseur cree, utilisable au choix
  Phase 2 (TODO) : nouvelles features UI utilisent UNIQUEMENT ce module
  Phase 3 (TODO) : remplacement progressif des 40 imports dans Nokido.py
"""

from __future__ import annotations

from typing import Any, Optional


def get_ui_facade():
    """Retourne le singleton AsyncNokidoFacade pour l UI."""
    from app.api_facade import get_async_facade

    return get_async_facade()


def get_ui_facade_sync():
    """Retourne le singleton NokidoFacade (version synchrone)."""
    from app.api_facade import get_facade

    return get_facade()


def attach_facade_to_app(app: Any) -> None:
    """Attache self.facade (sync) et self.afacade (async) a une Textual App.

    Args:
        app: L instance de l App Textual (self dans on_mount).

    Example:
        class NokidoApp(App):
            def on_mount(self):
                attach_facade_to_app(self)
                self.facade.agents_status()  # marche
    """
    if not hasattr(app, "facade"):
        app.facade = get_ui_facade_sync()
    if not hasattr(app, "afacade"):
        app.afacade = get_ui_facade()


class FacadeMixin:
    """
    Mixin pour widgets Textual qui ont besoin d acces a la facade.

    Usage:
        class MyWidget(Static, FacadeMixin):
            def __init__(self):
                super().__init__()
                self._init_facade()

            async def on_click(self):
                result = await self.afacade.ask_llm_async("hello")
    """

    def _init_facade(self) -> None:
        """Init les attributs facade (appeler apres super().__init__)."""
        self.facade = get_ui_facade_sync()
        self.afacade = get_ui_facade()


__all__ = [
    "get_ui_facade",
    "get_ui_facade_sync",
    "attach_facade_to_app",
    "FacadeMixin",
    "get_container",
    "attach_container_to_app",
]


# ═══════════════════════════════════════════════════════════════════════════
# DI Container (Vague 4 - 2026-04)
# ═══════════════════════════════════════════════════════════════════════════


def get_container():
    """Retourne le DI container global (vision DI complete)."""
    from app.core.di_container import get_container as _get

    return _get()


def attach_container_to_app(app: Any) -> None:
    """Attache self.container a une App Textual.

    Example:
        class NokidoApp(App):
            def on_mount(self):
                attach_container_to_app(self)
                self.container.get("facade").rag_query("...")
    """
    if not hasattr(app, "container"):
        app.container = get_container()
