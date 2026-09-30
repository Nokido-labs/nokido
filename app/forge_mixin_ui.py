"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164743_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0
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
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
import builtins

"""
Mixin UI/layout â€” compose, events, sidebar de DevOpsApp
Extrait de Nokido.py par shredder â€” Phase 5.
Pattern _lf() : rÃ©solution de l'instance DevOpsApp via sys.modules["__main__"].
"""
import sys as _sys

import asyncio
import logging
from pathlib import Path

# Imports Textual manquants (shredder ne les avait pas inclus)
from textual.app import ComposeResult
from textual.widgets import (
    Header,
    Footer,
    Static,
    Button,
    Input,
    ListView,
    RichLog,
)
from textual.containers import Horizontal, Vertical

logger = logging.getLogger(__name__)
import sys as _sys_f


def _fv_label(vm=None, plain: bool = False) -> str:
    """
    Helper centralisé — retourne le label de version pour l'affichage TUI.
    plain=True  → 'v0.13.3 [main]'          (pour les comparaisons texte)
    plain=False → '[dim]v0.13.3 [main][/]'  (markup Textual pour Static)
    Appelle forge_version.full_label() — source de vérité unique.
    """
    try:
        from nokido_agent.app.forge_version import full_label as _fl

        lbl = _fl(vm)
    except Exception:
        try:
            lbl = f"v{vm.current_version}" if vm else "v?"
        except Exception:
            lbl = "v?"
    return lbl if plain else f"[dim]{lbl}[/]"


from app.core.settings import get_settings as _forge_settings  # noqa: F401


class _SettingsProxy:
    """settingsproxy."""

    def __getattr__(self, k) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        s = _forge_settings()
        if s:
            return getattr(s, k, None)
        return None


settings = _SettingsProxy()  # résolution lazy via _forge_settings()


def _forge_run_ssh(*a, **kw) -> object:
    """Forge run ssh."""
    import sys as _s

    m = _s.modules.get("__main__")
    fn = getattr(m, "run_ssh", None)
    if fn:
        return fn(*a, **kw)
    raise RuntimeError("run_ssh non disponible")


run_ssh = _forge_run_ssh


def _forge_version_manager() -> object:
    """Forge version manager."""
    m = _sys_f.modules.get("__main__")
    return getattr(m, "version_manager", None)


def _main_attr(name, default=None) -> object:
    """Accès lazy aux globaux de Nokido.py via __main__."""
    m = _sys_f.modules.get("__main__")
    return getattr(m, name, default)


class _LazyGlobal:
    """Proxy pour un global de __main__ — résolu à l'accès (lazy)."""

    def __init__(self, name, default=None) -> None:
        """Init.

        Args:
            name: Description.
            default: Description.
        """
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_default", default)

    def _val(self) -> object:
        """Val."""
        v = _main_attr(object.__getattribute__(self, "_name"), object.__getattribute__(self, "_default"))
        return v

    def __getattr__(self, k) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        v = self._val()
        if v is not None:
            return getattr(v, k)
        return None

    def __truediv__(self, other) -> object:
        """Truediv.

        Args:
            other: Description.
        """
        v = self._val()
        if v is not None:
            return v / other
        from pathlib import Path as _P

        return _P(".") / other

    def __rtruediv__(self, other) -> object:
        """Rtruediv.

        Args:
            other: Description.
        """
        v = self._val()
        if v is not None:
            return other / v
        return other

    def __str__(self) -> object:
        """Str."""
        v = self._val()
        return str(v) if v is not None else ""

    def __repr__(self) -> object:
        """Repr."""
        return repr(self._val())

    def __bool__(self) -> object:
        """Bool."""
        return bool(self._val())


# Chemins calculés directement depuis __file__ — plus fiables que __main__
_APP_DIR = Path(__file__).resolve().parent  # …/LaForge/app/
_ROOT_DIR = _APP_DIR.parent  # …/LaForge/
_LOGS_DIR = _ROOT_DIR / "logs"
_DATA_DIR = _ROOT_DIR / "data"

# Lazy pour les objets runtime (engine, manager…)
agentic_engine = _LazyGlobal("agentic_engine")
rag_engine = _LazyGlobal("rag_engine")
prefect_manager = _LazyGlobal("prefect_manager")
ssh_manager = _LazyGlobal("ssh_manager")
"""Has onnx."""


def _HAS_ONNX() -> object:
    """has onnx."""
    return bool(_main_attr("HAS_ONNX", False))


HAS_ONNX = _main_attr("HAS_ONNX", False)


class _VMProxy:
    """vmproxy."""

    def __getattr__(self, k) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        vm = _forge_version_manager()
        if vm:
            return getattr(vm, k)
        if k == "current_version":
            try:
                from nokido_agent.app.forge_version import get as _fvget

                return _fvget()
            except Exception:
                return _main_attr("__version__", "0.13.0")
        defaults = {"work_path": None}
        return defaults.get(k)


version_manager = _VMProxy()


def _lf() -> object:
    """RÃ©sout l'instance DevOpsApp depuis le module principal."""
    m = _sys.modules.get("__main__")
    return getattr(m, "_app_instance", None)


# ── Symboles manquants résolus lazy ──────────────────────────
def _lazy(name) -> object:
    """Lazy.

    Args:
        name: Description.
    """
    import sys as _s

    m = _s.modules.get("__main__")
    return getattr(m, name, None)


def init_onnx_backend(*a, **kw) -> object:
    """Init onnx backend."""
    fn = _lazy("init_onnx_backend")
    if fn:
        return fn(*a, **kw)
    return {"embedder": False, "generator": False, "tree_sitter": False}


def init_registry(*a, **kw) -> object:
    """Init registry."""
    fn = _lazy("init_registry")
    if fn:
        return fn(*a, **kw)


# Classes internes DevOpsApp — résolues via type(self) au runtime
def _inner(self, name, fallback=None) -> object:
    """Inner.

    Args:
        name: Description.
        fallback: Description.
    """
    return getattr(type(self), name, fallback)


# SkillLearner — optionnel
try:
    from nokido_agent.app.skilltree import SkillLearner
except ImportError:

    class SkillLearner:
        """Init."""

        def __init__(self, **kw) -> None:
            """Initialise."""
            pass

        """Get."""

        def get(self, *a) -> object:
            """Get."""
            return type("S", (), {"status": "unknown"})()


# VSplitter — widget custom dans Nokido.py, fallback Static
try:
    from textual.widgets import Static as _St

    VSplitter = _St
except ImportError:
    pass


# Autres classes Textual internes — proxy via __main__
class _ClassProxy:
    """Init.

    Args:
        name: Description.
    """

    def __init__(self, name) -> None:
        """Initialise."""
        self._n = name

    def __call__(self, *a, **kw) -> object:
        """Call."""
        cls = _lazy(self._n)
        if cls:
            return cls(*a, **kw)
        raise NameError(self._n)


# Imports depuis les modules shredded
try:
    from nokido_agent.app.forge_orchestrator import SessionContext, AutocompleteEngine
    from nokido_agent.app.forge_rag_engine import AgenticEngine, RAGEngine
except ImportError:
    SessionContext = _ClassProxy("SessionContext")
    AutocompleteEngine = _ClassProxy("AutocompleteEngine")
    AgenticEngine = _ClassProxy("AgenticEngine")
    RAGEngine = _ClassProxy("RAGEngine")

# Restent en proxy (définies dans Nokido.py direct)
SSHWizardScreen = _ClassProxy("SSHWizardScreen")
try:
    from nokido_agent.app.forge_orchestrator import OrchestratorState
except ImportError:
    OrchestratorState = _ClassProxy("OrchestratorState")


# ── Résolution lazy des symboles Nokido.py ──────────────────
def _strip_ssh_output(s) -> object:
    """Strip ssh output.

    Args:
        s: Description.
    """
    fn = _main_attr("_strip_ssh_output")
    if fn:
        return fn(s)
    return str(s).strip() if s else ""


# Flags HAS_* — lus depuis __main__ au runtime
"""Has.

Args:
    name: Description.
"""


def _has(name) -> object:
    """has."""
    return bool(_main_attr(name, False))


# AGENT_META / AgentType — lazy
"""Agent meta."""


def _AGENT_META() -> object:
    """agent meta."""
    return _main_attr("AGENT_META", {})


"""Agenttype."""


def _AgentType() -> object:
    """agenttype."""
    return _main_attr("AgentType")


class _AgentTypeProxy:
    """agenttypeproxy."""

    def __getattr__(self, k) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        at = _AgentType()
        if at:
            return getattr(at, k)
        return k  # fallback: retourner le nom comme string


AgentType = _AgentTypeProxy()


class _AgentMetaProxy:
    """agentmetaproxy."""

    def __getitem__(self, k) -> object:
        """Getitem.

        Args:
            k: Description.
        """
        m = _AGENT_META()
        return m[k] if m else {}

    def get(self, k, d=None) -> object:
        """Get.

        Args:
            k: Description.
            d: Description.
        """
        m = _AGENT_META()
        return m.get(k, d) if m else d


AGENT_META = _AgentMetaProxy()


class UiMixin:
    """Mixin UI/layout â€” compose, events, sidebar de DevOpsApp"""

    def compose(self) -> ComposeResult:
        """Compose."""
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        version_manager = _ac.version_manager
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="sidebar"):
                yield Static("[bold #58a6ff]⚒ La Forge[/]", id="orc-title")
                yield Static(_fv_label(version_manager), id="orc-version")
                yield Button("🤖 Autonome", id="btn-mode-autonome", classes="mode-btn")
                yield Button("🤝 Collab", id="btn-mode-collaboration", classes="mode-btn")
                yield Button("⚖ Comité", id="btn-mode-comite", classes="mode-btn")
                yield Button("🔒 Sudo OFF", id="btn-sudo-toggle", classes="mode-btn")
                yield Static("─" * 20, classes="sb-sep")
                if hasattr(self, "role_panel"):
                    yield self.role_panel
                yield Static("─" * 20, classes="sb-sep")
                if hasattr(self, "rag_info"):
                    yield self.rag_info
                yield Static("─" * 20, classes="sb-sep")
                _EG = getattr(type(self), "EntropyGauge", None)
                if _EG:
                    yield _EG(id="entropy-gauge")
                else:
                    yield Static("", id="entropy-gauge")
                if hasattr(self, "skill_panel"):
                    yield self.skill_panel
                if hasattr(self, "metrics"):
                    yield self.metrics
                yield Static("[dim]Sessions:[/]", id="sess-label")
                yield ListView(id="session-list")
            with Horizontal(id="center-layout"):
                with Vertical(id="chat-panel"):
                    yield RichLog(id="chat-log", wrap=True, markup=True)
                    yield Input(placeholder="Message...", id="chat-input")
                yield Static("", id="v-splitter", classes="hidden")
                with Vertical(id="terminal-panel", classes="hidden"):
                    yield self.terminal
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        version_manager = _ac.version_manager
        yield Footer()

    def _update_sidebar_title(self) -> None:
        """Update sidebar title."""
        try:
            ver = _fv_label(version_manager, plain=True)
            self.query_one("#orc-title", Static).update("[bold #58a6ff]⚒ La Forge[/]")
            self.query_one("#orc-version", Static).update(f"[dim]v{ver} · {self.session_name[:12]}[/]")
        except Exception:
            pass

    def _update_mode_buttons(self) -> None:
        """Met à jour visuellement les boutons de mode orchestrateur."""
        try:
            for mode_id in ("autonome", "collaboration", "comite"):
                btn = self.query_one(f"#btn-mode-{mode_id}", Button)
                if mode_id == self._collab_mode:
                    btn.add_class("-active")
                else:
                    btn.remove_class("-active")
        except Exception:
            pass

    async def on_mount(self) -> None:
        """On mount."""
        global rag_engine, orchestrator_state
        self.sub_title = _fv_label(version_manager)
        _ver = _main_attr("__version__", "?")
        logger.info(f"[on_mount START] __version__={_ver!r}  label={_fv_label(version_manager)!r}")
        logger.info(f"[on_mount] ROOT={_ROOT_DIR}  LOGS={_LOGS_DIR}")
        try:
            from datetime import datetime as _dt

            _bak_dir = _APP_DIR / "backups"
            _bak_dir.mkdir(exist_ok=True)
            _ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            _dst = _bak_dir / f"auto_boot_{_ts}.py"
            if (_APP_DIR / "Nokido.py").exists():
                import shutil as _sb

                _sb.copy2(_APP_DIR / "Nokido.py", _dst)
                for _o in sorted(_bak_dir.glob("auto_boot_*.py"), key=lambda p: p.stat().st_mtime, reverse=True)[10:]:
                    try:
                        _o.unlink()
                    except Exception:
                        pass
                logger.info(f"[boot] Auto-backup -> {_dst.name}")
        except Exception as _be:
            logger.debug(f"[boot] backup: {_be}")

        if settings.use_rag and not rag_engine:
            rag_engine = RAGEngine()

            # NOTE: index_pending() supprime ici — timeout sur 50Mo de PDFs
            # et race condition avec warmup. Utiliser @rag reindex manuellement.
            # ── RAG warmup : conscience de soi ───────────────────────────
            async def _warmup_with_signal() -> None:
                """Warmup with signal."""
                try:
                    await self._rag_self_warmup()
                finally:
                    _ev = getattr(builtins, "_rag_warmup_done", None)
                    if _ev is not None and not _ev.is_set():
                        _ev.set()
                        logger.debug("[MemMgr] RAG warmup signal set")

        # ── Gérer la perte de focus (minimize / fenêtre par-dessus) ──────
        # Textual peut "geler" l'affichage quand l'app perd le focus terminal.
        # On s'abonne à SIGWINCH pour forcer un refresh quand le terminal
        # est redimensionné ou restauré.
        import signal as _sig

        def _on_winch(*_) -> None:
            """On winch."""
            try:
                self.refresh(layout=True)
                self.call_later(self.refresh, layout=True)
            except Exception:
                pass

        try:
            _sig.signal(_sig.SIGWINCH, _on_winch)
        except (OSError, ValueError, AttributeError):
            pass  # SIGWINCH indisponible (Windows)

        self.context = SessionContext(self.session_name)
        orchestrator_state = OrchestratorState()

        # ── Si SSH non configuré → ouvrir le wizard TUI ─────────────
        if not settings.ssh_host:

            async def _after_wizard(configured: bool):
                """After wizard.

                Args:
                    configured: Description.
                """
                if not configured:
                    self._set_ssh_mode(False)
                    self._chat_log().write(
                        "[yellow]⚠ Mode local — pas de connexion SSH.[/]\n"
                        "  [dim]Le terminal est masqué. Tapez [bold]@ssh <host>[/] pour vous connecter.[/]"
                    )
                    return
                # Connexion avec les valeurs saisies dans le wizard
                try:
                    await ssh_manager.connect()
                    _hn = settings.ssh_host
                    try:
                        _o, _, _ = await run_ssh("hostname -f 2>/dev/null || hostname")
                        _hn = _strip_ssh_output(_o)
                    except Exception:
                        pass
                    _kern = ""
                    try:
                        _o2, _, _ = await run_ssh("uname -r")
                        _kern = _strip_ssh_output(_o2)
                    except Exception:
                        pass
                    _ks = f" · [dim]kernel {_kern}[/]" if _kern else ""
                    self._set_ssh_mode(True, hostname=_hn or settings.ssh_host)
                    self._chat_log().write(
                        f"[green]✅ SSH[/] [bold]{_hn}[/] "
                        f"[dim]({settings.ssh_host}:{settings.ssh_port})[/] "
                        f"{ssh_manager.os_type} privilege={'[green]' + ssh_manager.privilege_method + '[/]' if ssh_manager.sudo_available else '[yellow]none[/]'}"
                        f"{_ks}"
                    )
                except Exception as _e:
                    self._set_ssh_mode(False)
                    self._chat_log().write(f"[red]❌ SSH: {_e}[/]")

            _SWS = getattr(type(self), "SSHWizardScreen", None)
            if _SWS:
                self.push_screen(_SWS(lambda ok: asyncio.create_task(_after_wizard(ok))))
        else:
            try:
                await ssh_manager.connect()
                # Récupérer hostname + kernel pour affichage au démarrage
                _hn, _kern = "", ""
                try:
                    _hn_out, _, _ = await run_ssh("hostname -f 2>/dev/null || hostname")
                    _hn = _strip_ssh_output(_hn_out)
                except Exception:
                    _hn = settings.ssh_host
                try:
                    _kern_out, _, _ = await run_ssh("uname -r")
                    _kern = _strip_ssh_output(_kern_out)
                except Exception:
                    pass
                _kern_str = f" · [dim]kernel {_kern}[/]" if _kern else ""
                self._set_ssh_mode(True, hostname=_hn or settings.ssh_host)
                self._chat_log().write(
                    f"[green]✅ SSH[/] [bold]{_hn or settings.ssh_host}[/] "
                    f"[dim]({settings.ssh_host}:{settings.ssh_port})[/] "
                    f"{ssh_manager.os_type} privilege={'[green]' + ssh_manager.privilege_method + '[/]' if ssh_manager.sudo_available else '[yellow]none[/]'}"
                    f"{_kern_str}"
                )
            except Exception as e:
                self._set_ssh_mode(False)
                self._chat_log().write(f"[red]❌ SSH: {e}[/]")

        ok = await self.terminal.connect()
        self._chat_log().write("[green]✅ Terminal PTY prêt[/]" if ok else "[yellow]⚠ Terminal non disponible[/]")
        logger.info(f"[boot] Terminal PTY : {'OK' if ok else 'non disponible'}")

        logger.debug(f"[boot] HAS_ONNX={_HAS_ONNX()}")
        if _HAS_ONNX():  # réévalué au runtime, pas à l'import

            async def _init_onnx_bg() -> None:
                """Init onnx bg."""
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: init_onnx_backend(
                        load_generator=True,
                        auto_launch=True,
                    ),
                )
                _emb = result.get("embedder", False)
                _gen = result.get("generator", False)
                _ts = result.get("tree_sitter", False)
                _c = self._chat_log()

                # ── Affichage Sidecar (une ligne résumée) ──
                _parts = []
                _log_parts = []
                if _emb:
                    _parts.append("[green]✅ Embeddings MiniLM[/]")
                    _log_parts.append("Embeddings=MiniLM")
                else:
                    _parts.append("[dim]Embeddings → Ollama[/]")
                    _log_parts.append("Embeddings=Ollama")
                if _gen:
                    _parts.append("[green]✅ Génération Phi-3.5[/]")
                    _log_parts.append("Génération=Phi-3.5")
                else:
                    _parts.append("[green]✅ Génération → Ollama[/]")
                    _log_parts.append("Génération=Ollama")
                _c.write("[bold #a371f7]⚡ Sidecar[/] " + "  ".join(_parts))
                logger.info(f"[boot] Sidecar : {' | '.join(_log_parts)}")

                # ── Affichage tree-sitter ──
                if _ts:
                    _c.write("[bold #a371f7]🛡️ Sentinelle[/] [green]✅ tree-sitter actif[/]")
                    logger.info("[boot] Sentinelle : tree-sitter actif")
                else:
                    _c.write("[bold #a371f7]🛡️ Sentinelle[/] [dim]⚠ tree-sitter inactif → audit AST natif[/]")
                    logger.warning("[boot] Sentinelle : tree-sitter inactif")

            asyncio.create_task(_init_onnx_bg())
        else:
            self._chat_log().write("[dim]⚡ Sidecar [yellow]⚠ Sidecar ML via brain_worker[/][/]")
            logger.info("[boot] Sidecar : HAS_ONNX=False (forge_runtime import)")

        await self._check_ollama_models()

        _pm = _main_attr("prefect_manager")
        if _pm and hasattr(_pm, "start"):
            await _pm.start()

        if rag_engine:
            asyncio.create_task(self._update_rag_info())

        logger.info(f"[boot] La Forge {_fv_label(version_manager)}")

        # ── Service Registry (routage réseau modulaire) ───────────────
        if _has("HAS_SERVICES"):
            _svc_path = _DATA_DIR / "services.json"
            _reg = init_registry(_svc_path)
            _n = len(_reg.all()) if _reg else 0
            logger.info(f"[boot] Services : {_n} endpoints enregistrés")

        # ── Initialiser l'AgenticEngine avec callback vers SkillTree ─
        global agentic_engine
        # SkillLearner (arbre hierarchique)
        _learner = None
        try:
            if _has("HAS_SKILLTREE"):
                logger.debug("[boot] SkillLearner init...")
                _learner = SkillLearner(registry_path=_DATA_DIR / "skill_registry.json")
                _learner.on_update(
                    lambda name, status: self.call_from_thread(self.skill_panel.add_or_update, name, status)
                )
                import sys as _sys_sl

                _mm = _sys_sl.modules.get("__main__")
                if _mm:
                    setattr(_mm, "_skill_learner", _learner)
                logger.debug("[boot] SkillLearner OK")
        except Exception as _sle:
            logger.warning(f"[boot] SkillLearner: {_sle}")
        # Monter la SkillTree maintenant que _learner est prêt
        try:
            self.skill_panel.refresh_tree(_learner)
            logger.debug("[boot] refresh_tree OK")
        except Exception as _rte:
            logger.warning(f"[boot] refresh_tree: {_rte}")
        try:
            logger.debug("[boot] AgenticEngine init...")
            agentic_engine = AgenticEngine(
                ui_callback=lambda name, status: self.call_from_thread(self.skill_panel.add_or_update, name, status),
                log_fn=lambda m: self._chat_log().write(m),
            )
            logger.debug(f"[boot] AgenticEngine OK  skills={len(agentic_engine._skills)}")
        except Exception as _aee:
            logger.warning(f"[boot] AgenticEngine: {_aee}")
            agentic_engine = None
        # Charger les compétences existantes dans le panneau
        if agentic_engine and agentic_engine._skills:
            try:
                self.skill_panel.render_summary(agentic_engine.get_skill_summary())
                logger.debug("[boot] render_summary OK")
            except Exception as _re:
                logger.warning(f"[boot] render_summary: {_re}")

        # ── Apprentissage autonome en background ─────────────────────
        if _has("HAS_SKILLTREE") and _learner and agentic_engine:

            async def _auto_learn() -> None:
                """Auto learn."""
                await _learner.run_autonomous(
                    discover_fn=agentic_engine._discover_and_ingest,
                    check_fn=agentic_engine.check_competence,
                    log_fn=lambda m: self._chat_log().write(m),
                )

            asyncio.create_task(_auto_learn())

        self._update_mode_buttons()
        self._setup_chat_buffer()  # patch RichLog.write → buffer
        self.query_one("#chat-input", getattr(type(self), "AutocompleteInput", Input)).focus()

    async def _update_rag_info(self) -> None:
        """
        Boucle 5s : sync UI + détecte les écritures MCP dans RAG/embeddings.db.
        from forge_app_context import app_ctx as _actx; _ac = _actx()
        rag_engine = _ac.rag_engine
        Si la DB a changé depuis le dernier load → recharge rag_engine.chunks.
        Garantit que les ingestions MCP (rag_ingest, _snap_rag_state) sont
        visibles dans la TUI sans redémarrage.
        """
        _last_db_mtime: float = 0.0
        while True:
            # ── Sync UI ──────────────────────────────────────────────────
            if rag_engine:
                self.rag_info.sync()

            # ── Détection changement DB → reload rag_engine ──────────────
            try:
                from nokido_agent.app.forge_rag_engine import _EMBEDDINGS_DB as _edb

                if _edb.exists():
                    _mtime = _edb.stat().st_mtime
                    if _mtime != _last_db_mtime and _last_db_mtime != 0.0:
                        # DB modifiée par MCP ou autre agent → recharge
                        if rag_engine and hasattr(rag_engine, "_load_embeddings"):
                            _before = len(rag_engine.chunks)
                            rag_engine._load_embeddings()
                            _after = len(rag_engine.chunks)
                            if _after != _before:
                                import logging as _lg

                                _lg.getLogger(__name__).info(f"[RAG sync] DB changée → {_before}→{_after} chunks")
                        # Invalide aussi le RagCache singleton
                        try:
                            from nokido_agent.app import forge_rag_cache as _frc

                            _frc._SINGLETON = None
                        except Exception:
                            pass
                    _last_db_mtime = _mtime
            except Exception:
                pass

            await asyncio.sleep(5)

    def action_focus_term(self) -> None:
        """Ctrl+T — affiche/masque le panneau PTY et y donne le focus."""
        try:
            panel = self.query_one("#terminal-panel")
            if "hidden" in panel.classes:
                # Afficher panneau + splitter
                panel.remove_class("hidden")
                try:
                    self.query_one("#v-splitter").remove_class("hidden")
                except Exception:
                    pass
                try:
                    self.query_one("#chat-panel").remove_class("expanded")
                except Exception:
                    pass
                # Connecter le terminal SSH si pas encore fait
                if hasattr(self.terminal, "_connected") and not self.terminal._connected:
                    import asyncio as _aio

                    _aio.create_task(self.terminal.connect())
            else:
                # Masquer panneau + splitter
                panel.add_class("hidden")
                try:
                    self.query_one("#v-splitter").add_class("hidden")
                except Exception:
                    pass
                try:
                    self.query_one("#chat-panel").add_class("expanded")
                except Exception:
                    pass
                self.query_one("#chat-input", getattr(type(self), "AutocompleteInput", Input)).focus()
                return
        except Exception:
            pass
        self.terminal.focus()

    def action_focus_input(self) -> None:
        """Action focus input."""
        self.query_one("#chat-input", getattr(type(self), "AutocompleteInput", Input)).focus()

    def on_focus(self) -> None:
        """App reprend le focus — forcer un refresh complet."""
        self.refresh(layout=True)

    def on_screen_resume(self) -> None:
        """Écran Textual restauré (après minimize ou fenêtre par-dessus)."""
        self.refresh(layout=True)
        try:
            self.call_later(self.refresh, layout=True)
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed):
        """On button pressed.

        Args:
            event: Description.
        """
        bid = event.button.id or ""
        # ── Mode orchestrateur ────────────────────────────────────────────
        if bid in ("btn-mode-autonome", "btn-mode-collaboration", "btn-mode-comite"):
            mode = bid.replace("btn-mode-", "")
            self._collab_mode = mode
            self._update_mode_buttons()
            self._chat_log().write(
                f"[bold #8b949e]Orchestrateur → mode [/]"
                f"[bold {'#79c0ff' if mode == 'autonome' else '#56d364' if mode == 'collaboration' else '#d2a8ff'}]{mode}[/]"
            )
            return
        # ── Sudo toggle ─────────────────────────────────────────────────
        if bid == "btn-sudo-toggle":
            self._sudo_unlocked = not self._sudo_unlocked
            btn = event.button
            if self._sudo_unlocked:
                btn.label = "🔓 Sudo ON"
                btn.styles.background = "#5c1a1a"
                btn.styles.color = "#ff6b6b"
                self._chat_log().write(
                    "[bold red]🔓 Sudo DÉVERROUILLÉ[/] — les commandes sudo seront injectées dans le terminal.\n"
                    "[dim]  ⚠ Attention : les commandes dangereuses restent bloquées (rm -rf, mkfs, dd…)[/]"
                )
            else:
                btn.label = "🔒 Sudo OFF"
                btn.styles.background = "#0d1f33"
                btn.styles.color = "#79c0ff"
                self._chat_log().write("[green]🔒 Sudo verrouillé[/] — les commandes sudo ne seront plus injectées.")
            return
        if bid == "btn-agent-chat":
            self._set_agent(AgentType.CHAT)
        elif bid == "btn-agent-action":
            self._set_agent(AgentType.ACTION)
        elif bid == "btn-agent-rag":
            self._set_agent(AgentType.RAG)
        elif bid == "btn-model":
            await self._select_model()
        elif bid == "btn-rag-open":
            import os as _os_btn, sys as _sys_btn

            try:
                _rd = settings.rag_dir
                if not _rd:
                    self._chat_log().write("[yellow]RAG dir non configure[/]")
                    return
                _p = Path(_rd)
                if not _p.is_absolute():
                    _p = _ROOT_DIR / "data" / _rd
                if not _p.exists():
                    _p.mkdir(parents=True, exist_ok=True)
                if _sys_btn.platform == "win32":
                    _os_btn.startfile(str(_p))
                elif _sys_btn.platform == "darwin":
                    _os_btn.system(f'open "{_p}"')
                else:
                    _os_btn.system(f'xdg-open "{_p}"')
                self._chat_log().write(f"[dim]Ouverture de {_p}[/]")
            except Exception as _e:
                self._chat_log().write(f"[red]Erreur RAG dir : {_e}[/]")

    async def on_input_submitted(self, event: Input.Submitted):
        """Gère la soumission avec orchestration."""
        txt = event.value.strip()
        if not txt:
            return
        event.input.value = ""

        # Commandes d'urgence
        if txt == "@reset":
            if self.ai_task and not self.ai_task.done():
                self.ai_task.cancel()
            self.ai_busy = False
            self._set_status("")
            self._chat_log().write("[yellow]⟳ IA réinitialisée.[/]")
            return

        if txt == "@status":
            meta = AGENT_META[self.current_agent]
            self._chat_log().write(
                f"Agent : [bold {meta['color']}]{meta['icon']} {meta['label']}[/] · "
                f"Modèle : [bold]{self._current_model()}[/] · "
                f"IA : {'[red]occupée[/]' if self.ai_busy else '[green]libre[/]'}"
            )
            return

        # Utilisation de l'orchestrateur pour le routage intelligent
        if settings.auto_switch_agent and not txt.startswith("@"):
            await self._handle_orchestrated_input(txt)
        else:
            # Traitement direct pour les commandes @
            await self._handle_orchestrated_input(txt)
