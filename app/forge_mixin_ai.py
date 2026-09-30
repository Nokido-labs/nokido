"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_mixin_ai
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
Mixin IA/agents â€” dispatch, modÃ¨les, suggestions de DevOpsApp
Extrait de Nokido.py par shredder â€” Phase 5.
Pattern _lf() : rÃ©solution de l'instance DevOpsApp via sys.modules["__main__"].
"""


try:
    import aiohttp
except ImportError:
    aiohttp = None
import sys as _sys

logger = __import__("logging").getLogger(__name__)
from app.core.settings import get_settings as _forge_settings  # noqa: F401
from app.forge_startup import save_last_assignment
from app.forge_ui_widgets import ModelScreen
from nokido_agent.app.forge_core_models import AgentType
from nokido_agent.app.forge_mixin_ui import AGENT_META


# Nom avec underscore de tete : c'est la convention du depot pour ce proxy
# (forge_agents, forge_llm, forge_routing, forge_pty, forge_rag_engine...).
# Le renommage l'avait perdu ICI et NULLE PART AILLEURS, alors que la ligne 42
# instanciait toujours `_SettingsProxy()` : le module levait NameError DES SON
# IMPORT. Symetriquement `_forge_settings` etait appele sans son underscore.
# Deux incoherences de prefixe en sens INVERSE dans le meme fichier.
# Mesure et correction 2026-09-08, verrouille par
# tests/nr/test_modules_parsables_nr.py::test_aucun_nom_libre_au_niveau_module.
class _SettingsProxy:
    def __getattr__(self, k: str) -> object | None:
        """Getattr.

        Args:
            k: Description.
        """
        s = _forge_settings()
        return getattr(s, k, None) if s else None


settings = _SettingsProxy()


def _lf() -> object:
    """RÃ©sout l'instance DevOpsApp depuis le module principal."""
    m = _sys.modules.get("__main__")
    return getattr(m, "_app_instance", None)


# ── Imports Textual manquants ────────────────────────────────
try:
    from textual.widgets import Button as _Button, Static as _Static, RichLog as _RichLog

    Button = _Button
    Static = _Static
    RichLog = _RichLog
except ImportError:
    pass

from nokido_agent.app.forge_logging import debug_log  # centralisé


def _get_inner_cls(self, name, fallback=None) -> object:
    """Résout une classe interne de DevOpsApp via type(self)."""
    return getattr(type(self), name, fallback)


class AiMixin:
    """Mixin IA/agents â€” dispatch, modÃ¨les, suggestions de DevOpsApp"""

    def _setup_chat_buffer(self) -> object:
        """Monkey-patch RichLog.write pour accumuler le texte brut dans _chat_log_buffer.
        Évite export_text() qui freeze l'UI sur les gros logs (Textual ≥ 0.49).
        """
        import re as _re_strip

        _ansi = _re_strip.compile(r"\x1b\[[0-9;]*m|\[/?[a-z_]+[^\]]*\]", _re_strip.I)
        try:
            _log = self._chat_log()
            _orig = _log.write
            _buf = self._chat_log_buffer

            def _patched_write(msg, *a, **kw) -> object:
                """Patched write.

                Args:
                    msg: Description.
                """
                try:
                    _buf.append(_ansi.sub("", str(msg)))
                    if len(_buf) > 2000:  # garder 2000 dernières lignes max
                        del _buf[:500]
                except Exception:
                    pass
                return _orig(msg, *a, **kw)

            _log.write = _patched_write  # type: ignore
        except Exception as _e:
            logger.debug(f"_setup_chat_buffer: {_e}")

    def _chat_log(self) -> RichLog:
        """Chat log."""
        return self.query_one("#chat-log", RichLog)

    def _current_model(self) -> str:
        """Current model."""
        if self.current_agent == AgentType.CHAT:
            return self.model_chat
        if self.current_agent == AgentType.ACTION:
            return self.model_action
        return self.model_rag

    def _set_agent(self, agent: AgentType, _from_user: bool = True) -> None:
        """
        Change l'agent courant affiché dans l'UI.
        NE DOIT ÊTRE APPELÉ QUE DEPUIS UNE ACTION EXPLICITE UTILISATEUR
        (Ctrl+1/2/3, boutons). Jamais depuis l'orchestrateur interne.
        _from_user=False est réservé pour les tests.
        """
        if not _from_user:
            return  # protection anti-boucle orchestrateur
        debug_log(
            hypothesis_id="H1",
            location="DevOpsApp._set_agent",
            message="Changement d'agent courant",
            data={
                "from": self.current_agent.value if hasattr(self, "current_agent") and self.current_agent else None,
                "to": agent.value,
            },
        )
        self.current_agent = agent
        self.agent_selector.set_agent(agent)
        meta = AGENT_META[agent]
        self._set_status(f"[{meta['color']}]{meta['icon']} {meta['label']}[/] actif")
        try:
            self.query_one("#chat-title", Static).update(
                f" [bold {meta['color']}]{meta['icon']} {meta['label']}[/]  "
                f"[dim]@help · @run · @rag · @audit · @estim[/]"
            )
        except Exception:
            pass
        try:
            self.query_one("#btn-model", Button).label = f"🤖 {self._current_model()[:18]}"
        except Exception:
            pass
        self._update_sidebar_title()

    async def _check_ollama_models(self) -> None:
        """Vérifie Ollama + fallback modèle auto si introuvable."""
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        settings = _ac.settings
        chat = self._chat_log()
        _tags_url = settings.ollama_tags_url or "http://localhost:11434/api/tags"
        if not isinstance(_tags_url, str):
            _tags_url = str(_tags_url)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(_tags_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        chat.write(f"[red]❌ Ollama HTTP {resp.status}[/]")
                        return
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    chat_models = [m for m in models if "embed" not in m.lower()]
            if not chat_models:
                chat.write("[red]❌ Aucun modèle Ollama — ollama pull mistral[/]")
                return
            # Résolution du modèle par défaut :
            # si OLLAMA_MODEL_DEFAULT est vide → prendre le 1er modèle dispo
            _forced = settings.ollama_model_default
            changed, fallback = [], (_forced if _forced and _forced in models else chat_models[0])
            for attr, lbl in [("model_chat", "💬"), ("model_action", "⚡"), ("model_rag", "🗄")]:
                cur = getattr(self, attr, None)
                if not cur or cur not in models:
                    setattr(self, attr, fallback)
                    changed.append(f"{lbl}→[green]{fallback}[/]")
            if changed:
                chat.write(f"[yellow]⚠ Modèles introuvables — fallback:[/] {' '.join(changed)}")
                chat.write(f"[dim]Dispo: {', '.join(chat_models[:5])} (@model pour changer)[/]")
                logger.warning(f"[boot] Ollama fallback : {' '.join(changed)}")
                self._update_sidebar_title()
            else:
                chat.write(
                    f"[green]✅ Ollama OK[/] · "
                    f"💬[bold]{getattr(self, 'model_chat', '-')}[/] "
                    f"⚡[bold]{getattr(self, 'model_action', '-')}[/] "
                    f"🗄[bold]{getattr(self, 'model_rag', '-')}[/]"
                )
                logger.info(
                    f"[boot] Ollama OK : chat={getattr(self, 'model_chat', '-')} "
                    f"action={getattr(self, 'model_action', '-')} "
                    f"rag={getattr(self, 'model_rag', '-')} ({len(chat_models)} modèles)"
                )
        except aiohttp.ClientConnectorError:
            chat.write("[red]❌ Ollama non joignable — ollama serve[/]")
            logger.error("[boot] Ollama non joignable")
        except Exception as e:
            chat.write(f"[yellow]⚠ Ollama check: {e}[/]")
            logger.warning(f"[boot] Ollama check : {e}")

    def action_agent_chat(self) -> None:
        """Action agent chat."""
        self._set_agent(AgentType.CHAT)

    def action_agent_action(self) -> None:
        """Action agent action."""
        self._set_agent(AgentType.ACTION)

    def action_agent_rag(self) -> None:
        """Action agent rag."""
        self._set_agent(AgentType.RAG)

    async def _select_model(self) -> None:
        """Select model."""
        async with aiohttp.ClientSession() as s:
            try:
                async with s.get(settings.ollama_tags_url, timeout=5) as resp:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", []) if "embed" not in m["name"]]
            except Exception:
                models = [m for m in [settings.ollama_model_default] if m]
        if not models:
            self._chat_log().write("[red]❌ Aucun modèle disponible[/]")
            return

        def cb(selected: str) -> None:
            """Cb.

            Args:
                selected: Description.
            """
            if self.current_agent == AgentType.CHAT:
                self.model_chat = selected
            elif self.current_agent == AgentType.ACTION:
                self.model_action = selected
            else:
                self.model_rag = selected
            self._set_agent(self.current_agent)
            self._update_sidebar_title()
            save_last_assignment(self.model_chat, self.model_action, self.model_rag)
            self._chat_log().write(
                f"[green]✅ Modèle [bold]{selected}[/] → {AGENT_META[self.current_agent]['icon']}[/]"
            )

        self.push_screen(ModelScreen(models, self._current_model(), cb))
