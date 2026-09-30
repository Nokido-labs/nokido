# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_gui_debug
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_gui_debug.py — Overlay de debug graphique pour la TUI Nokido
====================================================================
Attrape les incohérences GUI en temps réel :
  - Widgets manquants (NoMatches)
  - Handlers @ qui plantent silencieusement
  - Imports de modules optionnels échoués (HAS_* = False)
  - Erreurs Textual non affichées à l'utilisateur

Usage dans Nokido.py :
    from forge_gui_debug import GuiDebugOverlay, gui_debug_log, patch_app_for_debug

    # Dans DevOpsApp.compose() :
    yield GuiDebugOverlay()

    # Dans on_mount() :
    patch_app_for_debug(self)

    # Dans n'importe quel handler :
    gui_debug_log("@audit", "RAG non initialisé", level="warn")

API :
    gui_debug_log(source, message, level="info"|"warn"|"error")
    GuiDebugOverlay  — widget Textual, panneau flottant bas de page
    patch_app_for_debug(app) — monkey-patch on_error + handle_exception
"""


import logging
import traceback
from collections import deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Buffer circulaire — conserve les 50 dernières entrées
_DEBUG_BUFFER: deque[dict] = deque(maxlen=50)
_OVERLAY_REF: Optional[object] = None  # référence au widget actif

_LEVEL_COLORS = {
    "info": "#58a6ff",
    "warn": "#ffa657",
    "error": "#ff7b72",
    "ok": "#3fb950",
}
_LEVEL_ICONS = {
    "info": "ℹ",
    "warn": "⚠",
    "error": "✗",
    "ok": "✓",
}


# =============================================================================
# API PUBLIQUE — LOGGING DEBUG GUI
# =============================================================================


def gui_debug_log(source: str, message: str, level: str = "info", exc: Optional[Exception] = None) -> None:
    """
    Enregistre une entrée de debug GUI et l'affiche dans l'overlay si actif.
    Également loggué dans le fichier de log Python standard.
    """
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "source": source,
        "message": message,
        "level": level,
        "exc": traceback.format_exc() if exc else "",
    }
    _DEBUG_BUFFER.append(entry)

    # Log Python
    log_fn = {
        "info": logger.info,
        "warn": logger.warning,
        "error": logger.error,
        "ok": logger.info,
    }.get(level, logger.debug)
    log_fn(f"[gui-debug] [{source}] {message}" + (f" | {exc}" if exc else ""))

    # Mise à jour de l'overlay si actif
    global _OVERLAY_REF
    if _OVERLAY_REF is not None:
        try:
            _OVERLAY_REF.push_entry(entry)
        except Exception:
            pass


def gui_debug_clear() -> None:
    """Vide le buffer de debug."""
    _DEBUG_BUFFER.clear()
    global _OVERLAY_REF
    if _OVERLAY_REF:
        try:
            _OVERLAY_REF.refresh_all()
        except Exception:
            pass


# =============================================================================
# WIDGET TEXTUAL — OVERLAY DEBUG
# =============================================================================

try:
    from textual.widgets import Static, RichLog
    from textual.app import ComposeResult
    from textual.reactive import reactive

    class GuiDebugOverlay(Static):
        """
        Panneau de debug flottant — affiché en bas de la TUI.
        Captures :
          - Erreurs handlers @ (NoMatches, AttributeError, TypeError)
          - Modules optionnels non chargés (HAS_* = False)
          - Exceptions Textual non catchées

        Contrôles :
          Ctrl+D → afficher/cacher l'overlay
          Ctrl+K → vider le buffer
        """

        DEFAULT_CSS = """
        GuiDebugOverlay {
            dock: bottom;
            height: 8;
            background: #0d1117;
            border-top: solid #30363d;
            display: none;
            padding: 0 1;
            overflow-y: scroll;
        }
        GuiDebugOverlay.-visible {
            display: block;
        }
        GuiDebugOverlay .debug-title {
            color: #8b949e;
            text-style: bold;
        }
        """

        _visible: reactive[bool] = reactive(False)

        def compose(self) -> ComposeResult:
            """Compose."""
            yield Static("[bold #8b949e]◉ Debug GUI[/]  [dim]Ctrl+D masquer · Ctrl+K vider[/]", classes="debug-title")
            yield RichLog(id="debug-log", highlight=True, markup=True, max_lines=200)

        def on_mount(self) -> None:
            """On mount."""
            global _OVERLAY_REF
            _OVERLAY_REF = self
            # Rejouer le buffer existant
            self.refresh_all()

        def push_entry(self, entry: dict) -> None:
            """Ajoute une ligne dans le RichLog."""
            try:
                log = self.query_one("#debug-log", RichLog)
                color = _LEVEL_COLORS.get(entry["level"], "#8b949e")
                icon = _LEVEL_ICONS.get(entry["level"], "•")
                line = f"[dim]{entry['ts']}[/] [bold {color}]{icon}[/] [{color}]{entry['source']}[/] {entry['message']}"
                if entry.get("exc"):
                    line += f"\n[dim red]{entry['exc'][:200]}[/]"
                log.write(line)
                # Rendre visible automatiquement si erreur
                if entry["level"] == "error" and not self._visible:
                    self.toggle_visibility()
            except Exception:
                pass

        def refresh_all(self) -> None:
            """Rejoue tout le buffer dans le RichLog."""
            try:
                log = self.query_one("#debug-log", RichLog)
                log.clear()
                for entry in _DEBUG_BUFFER:
                    self.push_entry(entry)
            except Exception:
                pass

        def toggle_visibility(self) -> None:
            """Toggle visibility."""
            self._visible = not self._visible
            if self._visible:
                self.add_class("-visible")
            else:
                self.remove_class("-visible")

        def watch__visible(self, visible: bool) -> None:
            """Watch  visible.

            Args:
                visible: Description.
            """
            if visible:
                self.add_class("-visible")
            else:
                self.remove_class("-visible")

    _TEXTUAL_OK = True

except Exception as _e_textual:
    # Textual pas dispo (tests unitaires, MCP sandbox)
    _TEXTUAL_OK = False
    GuiDebugOverlay = None  # Textual absent — ne pas utiliser comme widget


# =============================================================================
# PATCH APP — MONKEY-PATCH SUR DEVOPSAPP
# =============================================================================


def patch_app_for_debug(app) -> None:
    """
    Patche l'instance DevOpsApp pour capturer toutes les erreurs GUI :
      1. handle_exception → gui_debug_log
      2. Vérification des modules HAS_* au boot
      3. Wrapper sur _handle_at pour capturer les erreurs handlers
    """
    # ── 1. Patch handle_exception ─────────────────────────────────────────────
    _orig_handle = getattr(app, "handle_exception", None)

    def _patched_handle_exception(error: Exception) -> None:
        """Patched handle exception.

        Args:
            error: Description.
        """
        gui_debug_log(
            source=f"App.{type(error).__name__}",
            message=str(error)[:120],
            level="error",
            exc=error,
        )
        if _orig_handle:
            _orig_handle(error)

    try:
        app.handle_exception = _patched_handle_exception
    except Exception:
        pass

    # ── 2. Vérification modules HAS_* ─────────────────────────────────────────
    import sys as _sys

    main_mod = _sys.modules.get("__main__") or app
    has_checks = {
        "HAS_SKILLTREE": "SkillTree",
        "HAS_DANGER_GUARD": "DangerGuard",
        "HAS_SCORING": "ModelScorer",
        "HAS_PREDICTIF": "PredictiveRouter",
        "HAS_ROUTAGE": "SmartRouter",
        "HAS_LOOPS": "forge_loop",
        "HAS_WEB_SEARCH": "WebSearch",
        "HAS_DISPATCH_NET": "forge_dispatch_network",
    }
    missing = []
    for flag, label in has_checks.items():
        val = getattr(main_mod, flag, None)
        if val is False:
            missing.append(label)
            gui_debug_log(
                source="boot:modules",
                message=f"{label} non chargé ({flag}=False)",
                level="warn",
            )
        elif val is True:
            gui_debug_log(
                source="boot:modules",
                message=f"{label} ✓",
                level="ok",
            )

    if missing:
        gui_debug_log(
            source="boot:résumé",
            message=f"{len(missing)} modules optionnels absents : {', '.join(missing)}",
            level="warn",
        )
    else:
        gui_debug_log(
            source="boot:résumé",
            message="Tous les modules optionnels chargés",
            level="ok",
        )

    # ── 3. Wrapper _handle_at ─────────────────────────────────────────────────
    _orig_handle_at = getattr(app, "_handle_at", None)
    if _orig_handle_at:

        async def _patched_handle_at(cmd_line: str) -> None:
            """Patched handle at.

            Args:
                cmd_line: Description.
            """
            cmd = cmd_line.split()[0].lower() if cmd_line.split() else "?"
            try:
                await _orig_handle_at(cmd_line)
                gui_debug_log(source=cmd, message="OK", level="ok")
            except Exception as e:
                gui_debug_log(
                    source=cmd,
                    message=f"{type(e).__name__}: {str(e)[:100]}",
                    level="error",
                    exc=e,
                )
                raise

        try:
            app._handle_at = _patched_handle_at
        except Exception:
            pass

    logger.info("[gui-debug] patch_app_for_debug appliqué")


# =============================================================================
# INTÉGRATION DANS NOKIDO — INSTRUCTIONS
# =============================================================================
# Dans Nokido.py, ajouter après les imports :
#
#   from forge_gui_debug import GuiDebugOverlay, gui_debug_log, patch_app_for_debug
#
# Dans DevOpsApp.compose() — à la fin :
#   yield GuiDebugOverlay()
#
# Dans DevOpsApp.on_mount() — après les checks boot :
#   patch_app_for_debug(self)
#
# Raccourci clavier dans DevOpsApp :
#   BINDINGS = [..., Binding("ctrl+d", "toggle_debug", "Debug GUI")]
#
#   def action_toggle_debug(self):
#       try:
#           self.query_one(GuiDebugOverlay).toggle_visibility()
#       except Exception:
#           pass
