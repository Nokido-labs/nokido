from __future__ import annotations

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164743_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__  = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_ssh.py — Composants SSH/PTY extraits de Nokido.py (v16.5)
=================================================================
Contient :
  SSHManager        — connexions SSH + retry
  PTYTerminal       — widget Textual terminal PTY
  SSHWizardScreen   — assistant configuration SSH
  handle_ssh()      — _handle_ssh de DevOpsApp
  handle_set_ssh_mode()           — _set_ssh_mode
  handle_apply_pending_ssh_mode() — _apply_pending_ssh_mode
"""

import asyncio, logging, os, re
from pathlib import Path
from rich.markup import escape

# asyncssh
try:
    import asyncssh
except ImportError:
    asyncssh = None

# pyte
try:
    import pyte
except ImportError:
    pyte = None


# settings — résolu via _g() au runtime (Nokido.py le définit après boot)
# Fallback : créer une instance fraiche si appelé hors contexte Nokido
def _get_settings() -> object:
    """Get settings."""
    s = forge_context.get_settings()
    if s is None:
        try:
            from app.core.settings import create_settings as _cs

            s = _cs()
        except Exception:
            pass
    if s is not None:
        return s
    try:
        from app.core.settings import create_settings

        return create_settings()
    except Exception:
        return None


# Textual imports
try:
    from textual.app import ComposeResult
    from textual.widget import Widget
    from textual.widgets import Button, Input, Label, Static, RichLog
    from textual.screen import ModalScreen
    from textual.reactive import reactive
    from textual import events
except ImportError:
    # Fallback si Textual absent (tests unitaires)
    class Widget:
        """Widget."""
        pass  # type: ignore

    class ModalScreen:
        """Modalscreen."""
        pass  # type: ignore

    class ComposeResult:
        """Composeresult."""
        pass  # type: ignore

    def reactive(*a, **k):
        """Reactive."""
        return None  # type: ignore

    class events:
        """Events."""
        pass  # type: ignore

    class Button:
        """Button."""
        pass  # type: ignore

    class Input:
        """Input."""
        pass  # type: ignore

    class Label:
        """Label."""
        pass  # type: ignore

    class Static:
        """Static."""
        pass  # type: ignore

    class RichLog:
        """Richlog."""
        pass  # type: ignore


# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

import forge_context  # centralisé

# ── Dépendances locales ────────────────────────────────────────────


def _strip_ssh_output(raw: str) -> str:
    """Nettoie stdout SSH : séquences ANSI, \r, espaces parasites."""
    clean = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", raw)
    result = clean.replace("\r", "").strip().split("\n")[0].strip()
    return result


class ErrorManager:
    """Gestion centralisée des erreurs avec retry et logging."""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0) -> None:
        """Init.

        Args:
            max_retries: Description.
            base_delay: Description.
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.error_stats: dict = {}

    async def execute_with_retry(self, func, *args, **kwargs) -> object:
        """Execute with retry.

        Args:
            func: Description.
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(min(self.base_delay * (2**attempt), 10))
        raise last_error


# ── SSHManager ──────────────────────────────────────────────────


class SSHManager:
    """Gère la connexion SSH et l'exécution de commandes avec retry."""

    def __init__(self) -> None:
        """Init."""
        self._connection = None
        self._sudo_available = False
        self._lock = asyncio.Lock()
        self.error_manager = ErrorManager(max_retries=2, base_delay=2.0)

    async def connect(self) -> object:
        """Connect."""
        async with self._lock:
            if self._connection and not self._connection.is_closed():
                return
            # known_hosts : charger ~/.ssh/known_hosts si disponible
            # None = désactivé (risque MITM) — fallback si fichier absent
            _known_hosts_path = Path.home() / ".ssh" / "known_hosts"
            _kh = str(_known_hosts_path) if _known_hosts_path.exists() else None
            if _kh is None:
                logger.warning("[SSH] known_hosts absent")
            _s = forge_context.get_settings()
            if _s is None:
                raise RuntimeError("settings non disponible")

            # Helper interne pour ne pas dupliquer les args
            async def _do_connect(_kh_arg) -> object:
                """Do connect.

                Args:
                    _kh_arg: Description.
                """
                return await asyncssh.connect(
                    _s.ssh_host,
                    port=_s.ssh_port,
                    username=_s.ssh_user,
                    client_keys=[str(_s.private_key_path)],
                    known_hosts=_kh_arg,
                )

            try:
                self._connection = await _do_connect(_kh)
            except asyncssh.HostKeyNotVerifiable:
                # Hôte absent du known_hosts — tentative ssh-keyscan multi-algo
                logger.warning(f"[SSH] {_s.ssh_host} absent known_hosts — ssh-keyscan...")
                _kh_updated = False
                try:
                    import subprocess as _sp_kh

                    # Essayer plusieurs types de clé (sntrup761 non supporté sur certains Windows)
                    for _key_type in ("rsa", "ecdsa", "ed25519", ""):
                        _args = ["ssh-keyscan", "-H", "-p", str(_s.ssh_port)]
                        if _key_type:
                            _args += ["-t", _key_type]
                        _args.append(_s.ssh_host)
                        _scan = _sp_kh.run(_args, capture_output=True, text=True, timeout=10)
                        if _scan.stdout and _scan.stdout.strip():
                            _known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
                            _existing = _known_hosts_path.read_text() if _known_hosts_path.exists() else ""
                            _known_hosts_path.write_text(_existing + _scan.stdout)
                            _kh = str(_known_hosts_path)
                            _kh_updated = True
                            logger.info(f"[SSH] {_s.ssh_host} ajouté known_hosts (type={_key_type or 'auto'})")
                            break
                except Exception as _ke:
                    logger.warning(f"[SSH] ssh-keyscan: {_ke}")
                if not _kh_updated:
                    # Dernier recours : connexion sans vérification (avec warning)
                    logger.warning("[SSH] ssh-keyscan échoué — known_hosts=None (TOFU)")
                    _kh = None
                self._connection = await _do_connect(_kh)
            try:
                r = await self._connection.run("sudo -n true")
                self._sudo_available = r.exit_status == 0
            except Exception:
                self._sudo_available = False
            logger.info(f"SSH connecté sudo={self._sudo_available}")

    async def run(self, command: str, sudo: bool = False, timeout: int = 30) -> Tuple[str, str, int]:
        """Run.

        Args:
            command: Description.
            sudo: Description.
            timeout: Description.
        """
        await self.connect()
        full_cmd = f"sudo {command}" if sudo else command
        async with self._lock:
            return await self.error_manager.execute_with_retry(self._execute_command, full_cmd, timeout)

    async def _execute_command(self, full_cmd: str, timeout: int) -> Tuple[str, str, int]:
        """Execute command.

        Args:
            full_cmd: Description.
            timeout: Description.
        """
        try:
            result = await asyncio.wait_for(self._connection.run(full_cmd), timeout=timeout)
            return result.stdout, result.stderr, result.exit_status
        except asyncio.TimeoutError:
            return "", f"Timeout ({timeout}s)", -1
        except Exception as e:
            return "", f"[SSH] {e}", -1

    async def close(self) -> None:
        """Close."""
        async with self._lock:
            if self._connection and not self._connection.is_closed():
                self._connection.close()
                await self._connection.wait_closed()
                self._connection = None

    @property
    def sudo_available(self) -> bool:
        """Sudo available."""
        return self._sudo_available


# ── PTYTerminal ─────────────────────────────────────────────────


class PTYTerminal(Widget):
    """Terminal interactif basé sur pyte et asyncssh."""

    def __init__(self) -> None:
        """Init."""
        super().__init__()
        self._cols = 110
        self._rows = 30
        self._screen = None
        self._stream = None
        if pyte is not None:
            try:
                self._screen = pyte.Screen(self._cols, self._rows)
                self._stream = pyte.Stream(self._screen)
            except Exception as _pe:
                logger.warning(f"[PTY] pyte init: {_pe}")
        self._input_queue = asyncio.Queue()
        self._connection = None
        self._channel = None
        self._connected = False
        self._read_task = None
        self._write_task = None
        self._log = None

    def compose(self) -> ComposeResult:
        """Compose."""
        import traceback as _tb_c, pathlib as _pl_c

        _clog = _pl_c.Path(__file__).parent.parent / "logs" / "compose_error.txt"
        try:
            yield from self._compose_inner()
        except Exception:
            _clog.write_text(_tb_c.format_exc(), encoding="utf-8")
            raise

    def _compose_inner(self) -> ComposeResult:
        """Compose inner."""
        yield RichLog(id="pty-log", wrap=False, markup=False, auto_scroll=True)

    async def on_mount(self) -> None:
        """On mount."""
        self._log = self.query_one("#pty-log", RichLog)
        self._sync_size()

    def _sync_size(self) -> None:
        """Sync size."""
        try:
            w, h = self.size.width, self.size.height
            nc = max(40, w - 2)
            nr = max(8, h - 2)
            if nc != self._cols or nr != self._rows:
                self._cols = nc
                self._rows = nr
                if self._screen:
                    self._screen.resize(nr, nc)
                if self._connected and self._channel:
                    try:
                        self._channel.change_terminal_size(nc, nr)
                    except Exception:
                        pass
        except Exception:
            pass

    async def on_resize(self, _) -> None:
        """On resize.

        Args:
            _: Description.
        """
        self._sync_size()
        self._refresh_log()

    def watch_size(self, size) -> None:
        """Watcher réactif — déclenché sur TOUT changement de taille (splitter, fenêtre)."""
        self._sync_size()
        self._refresh_log()

    def _refresh_log(self) -> None:
        """Force le RichLog à recalculer sa largeur d'affichage."""
        try:
            log = self.query_one("#pty-log", RichLog)
            log.refresh(layout=True)
            # Recalibrer la largeur de wrapping
            log._max_width = max(40, self.size.width - 2)
        except Exception:
            pass

    async def connect(self) -> bool:
        """Connect."""
        if self._connected:
            return True
        try:
            self._connection = await asyncssh.connect(
                _get_settings().ssh_host,
                port=_get_settings().ssh_port,
                username=_get_settings().ssh_user,
                client_keys=[str(_get_settings().private_key_path)],
                known_hosts=None,
            )
            self._channel = await self._connection.create_process(
                term_type="xterm-256color", term_size=(self._cols, self._rows), request_pty=True
            )
            self._connected = True
            self._sync_size()  # adapter au layout courant dès la connexion
            self._read_task = asyncio.create_task(self._read_loop())
            self._write_task = asyncio.create_task(self._write_loop())
            return True
        except Exception as e:
            if self._log:
                self._log.write(f"[PTY] Connexion échouée: {e}")
            return False

    async def _read_loop(self) -> None:
        """Read loop."""
        try:
            while self._connected:
                try:
                    data = await asyncio.wait_for(self._channel.stdout.read(4096), timeout=0.05)
                    if data:
                        if self._stream:
                            self._stream.feed(data)
                        self._refresh()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._connected = False
                    if self._log:
                        self._log.write(f"[PTY déconnecté: {e}]")
                    break
        except asyncio.CancelledError:
            pass

    async def _write_loop(self) -> None:
        """Write loop."""
        try:
            while self._connected:
                try:
                    data = await asyncio.wait_for(self._input_queue.get(), timeout=1.0)
                    if self._channel and not self._channel.stdin.is_closing():
                        self._channel.stdin.write(data)
                        await self._channel.stdin.drain()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"PTY write: {e}")
                    break
        except asyncio.CancelledError:
            pass

    def _refresh(self) -> None:
        """Refresh."""
        if not self._log:
            return
        try:
            self._log.clear()
            for line in self._screen.display if self._screen else []:
                self._log.write(line)
        except Exception:
            pass

    KEY_MAP = {
        "enter": "\r",
        "backspace": "\x7f",
        "tab": "\t",
        "escape": "\x1b",
        "space": " ",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "right": "\x1b[C",
        "left": "\x1b[D",
        "home": "\x1b[H",
        "end": "\x1b[F",
        "delete": "\x1b[3~",
        "insert": "\x1b[2~",
        "pageup": "\x1b[5~",
        "pagedown": "\x1b[6~",
        "f1": "\x1bOP",
        "f2": "\x1bOQ",
        "f3": "\x1bOR",
        "f4": "\x1bOS",
    }

    async def on_key(self, event: events.Key) -> None:
        """On key.

        Args:
            event: Description.
        """
        if not self._connected:
            return
        key = event.key
        if key in self.KEY_MAP:
            await self._input_queue.put(self.KEY_MAP[key])
            event.stop()
            return
        if key.startswith("ctrl+"):
            c = key[5:]
            if len(c) == 1 and c.isalpha():
                await self._input_queue.put(chr(ord(c.lower()) - 96))
                event.stop()
                return
        char = getattr(event, "character", None)
        if char and len(char) == 1 and char.isprintable():
            await self._input_queue.put(char)
            event.stop()
            return
        if len(key) == 1 and key.isprintable():
            await self._input_queue.put(key)
            event.stop()

    async def inject(self, cmd: str, echo: bool = True) -> None:
        """
        Envoie une commande au shell SSH.
        echo=True : affiche immédiatement la commande dans le RichLog.
        DangerGuard vérifié avant injection — bloque les commandes destructrices.
        """
        if not self._connected:
            if self._log:
                self._log.write(f"[non connecté] {cmd}")
            return
        # DangerGuard sur PTY inject — même protection que @run
        try:
            from forge_code import get_guard, should_auto_block

            _guard = get_guard()
            if _guard:
                _chk = _guard.check(cmd)
                if should_auto_block(_chk):
                    logger.warning(f"[PTY inject BLOCKED] {cmd[:80]} — {_chk.rule_name}")
                    if self._log:
                        self._log.write(f"[red]☠ PTY BLOCKED: {escape(cmd[:60])}[/]")
                    return
        except Exception:
            pass  # DangerGuard absent — on continue sans blocage
        # Écho local immédiat — évite le blanc avant réponse serveur
        if echo and self._log and cmd.strip():
            try:
                self._log.write(f"$ {cmd}")
            except Exception:
                pass
        await self._input_queue.put(cmd + "\r")

    async def disconnect(self) -> None:
        """Disconnect."""
        self._connected = False
        for task in (self._read_task, self._write_task):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (self._read_task, self._write_task) if t), return_exceptions=True)
        if self._channel:
            try:
                self._channel.stdin.write_eof()
            except Exception:
                pass
        if self._connection:
            self._connection.close()
            await self._connection.wait_closed()


# ── SSHWizardScreen ─────────────────────────────────────────────


class SSHWizardScreen(ModalScreen):
    """
    Interface de configuration SSH, cohérente avec le style La Forge.
    Lancée depuis on_mount() si SSH_HOST / SSH_USER / PRIVATE_KEY_PATH
    sont absents. Propose session temporaire ou enregistrement Nokido.env.
    """

    CSS = """
    SSHWizardScreen {
        align: center middle;
        background: rgba(0,0,0,0.85);
    }
    #wizard-box {
        width: 64;
        background: #161b22;
        border: solid #58a6ff;
        padding: 1 2;
    }
    #wizard-title {
        color: #58a6ff;
        text-style: bold;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }
    #wizard-subtitle {
        color: #8b949e;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }
    .wiz-label {
        color: #8b949e;
        height: 1;
        margin-top: 1;
    }
    .wiz-input {
        background: #0d1117;
        color: #c9d1d9;
        border: solid #30363d;
        height: 1;
    }
    .wiz-input:focus { border: solid #58a6ff; }
    #wizard-error {
        color: #ff7b72;
        height: 1;
        margin-top: 1;
    }
    #wizard-sep {
        color: #30363d;
        margin-top: 1;
        height: 1;
    }
    #wizard-save-label {
        color: #c9d1d9;
        height: 1;
        margin-top: 1;
    }
    #btn-session {
        background: #0d2137;
        color: #58a6ff;
        border: none;
        width: 1fr;
        margin-top: 1;
    }
    #btn-session:hover { background: #1a3a5c; color: #ffffff; }
    #btn-save {
        background: #0d2010;
        color: #56d364;
        border: none;
        width: 1fr;
        margin-top: 0;
    }
    #btn-save:hover { background: #1a3d18; color: #ffffff; }
    #btn-cancel {
        background: #1a1a1a;
        color: #8b949e;
        border: none;
        width: 1fr;
        margin-top: 0;
    }
    #btn-cancel:hover { background: #30363d; color: #c9d1d9; }
    """

    def __init__(self, on_done: Callable) -> None:
        """Init.

        Args:
            on_done: Description.
        """
        super().__init__()
        self._on_done = on_done  # callback(saved: bool) appelé après config

    def compose(self) -> ComposeResult:
        """Compose."""
        with Vertical(id="wizard-box"):
            yield Static("⚒  La Forge — Connexion SSH", id="wizard-title")
            yield Static("Aucune cible SSH configurée dans Nokido.env", id="wizard-subtitle")
            yield Static("─" * 58, id="wizard-sep")

            yield Static("Adresse IP ou hostname  (SSH_HOST)", classes="wiz-label")
            yield Input(placeholder="192.168.1.x  ou  mon-serveur.local", id="wiz-host", classes="wiz-input")

            with Horizontal():
                with Vertical():
                    yield Static("Utilisateur  (SSH_USER)", classes="wiz-label")
                    yield Input(placeholder="root  /  admin  /  pi", id="wiz-user", classes="wiz-input")
                with Vertical():
                    yield Static("Port  (SSH_PORT)", classes="wiz-label")
                    yield Input(placeholder="22", value="22", id="wiz-port", classes="wiz-input")

            yield Static("Chemin clé privée  (PRIVATE_KEY_PATH)", classes="wiz-label")
            yield Input(placeholder=r"C:\Users\…\id_rsa   ou   ~/.ssh/id_rsa", id="wiz-key", classes="wiz-input")

            yield Static("", id="wizard-error")
            yield Static("─" * 58, id="wizard-sep2", classes="wiz-label")
            yield Static(
                "[dim]Session[/] = actif jusqu'à la fermeture  ·  [dim]Enregistrer[/] = écrit dans Nokido.env",
                id="wizard-save-label",
            )

            with Horizontal():
                yield Button("🔌  Session uniquement", id="btn-session")
            with Horizontal():
                yield Button("💾  Enregistrer dans Nokido.env", id="btn-save")
            with Horizontal():
                yield Button("✕  Annuler", id="btn-cancel")

    def _get_values(self) -> tuple:
        """Get values."""
        host = self.query_one("#wiz-host", Input).value.strip()
        user = self.query_one("#wiz-user", Input).value.strip()
        key = self.query_one("#wiz-key", Input).value.strip()
        port_raw = self.query_one("#wiz-port", Input).value.strip()
        try:
            port = int(port_raw) if port_raw else 22
        except ValueError:
            port = 22
        return host, user, port, key

    def _show_error(self, msg: str) -> None:
        """Show error.

        Args:
            msg: Description.
        """
        try:
            self.query_one("#wizard-error", Static).update(f"[red]⚠ {msg}[/]")
        except Exception:
            pass

    def _apply(self, host: str, user: str, port: int, key: str) -> bool:
        """Valide et injecte dans os.environ + _get_settings()."""
        if not host:
            self._show_error("SSH_HOST obligatoire")
            return False
        if not user:
            self._show_error("SSH_USER obligatoire")
            return False
        if not key:
            self._show_error("PRIVATE_KEY_PATH obligatoire")
            return False
        if not Path(key).exists():
            self._show_error(f"Fichier introuvable : {key}")
            return False

        # Injecter dans os.environ et settings
        os.environ["SSH_HOST"] = host
        os.environ["SSH_USER"] = user
        os.environ["SSH_PORT"] = str(port)
        os.environ["PRIVATE_KEY_PATH"] = key
        _get_settings().ssh_host = host
        _get_settings().ssh_user = user
        _get_settings().ssh_port = port
        _get_settings().private_key_path = Path(key)
        return True

    def _write_env(self, host: str, user: str, port: int, key: str) -> object:
        """Écrit les variables SSH dans Nokido.env."""
        import re as _re

        env_path = _ROOT_DIR / "Nokido.env"
        try:
            content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""

            def _set_v(c, k, v) -> object:
                """Set v.

                Args:
                    c: Description.
                    k: Description.
                    v: Description.
                """
                pat = _re.compile(rf"^{k}=.*$", _re.MULTILINE)
                ln = f"{k}={v}"
                return pat.sub(ln, c) if pat.search(c) else c.rstrip("\n") + f"\n{ln}\n"

            content = _set_v(content, "SSH_HOST", host)
            content = _set_v(content, "SSH_PORT", str(port))
            content = _set_v(content, "SSH_USER", user)
            content = _set_v(content, "PRIVATE_KEY_PATH", key)
            env_path.write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            self._show_error(f"Nokido.env : {e}")
            return False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """On button pressed.

        Args:
            event: Description.
        """
        bid = event.button.id

        if bid == "btn-cancel":
            self._on_done(False)
            self.dismiss()
            return

        host, user, port, key = self._get_values()

        if bid == "btn-session":
            if self._apply(host, user, port, key):
                self._on_done(True)
                self.dismiss()

        elif bid == "btn-save":
            if self._apply(host, user, port, key):
                saved = self._write_env(host, user, port, key)
                if saved:
                    self._on_done(True)
                    self.dismiss()
                # si erreur écriture, _show_error déjà appelé, on reste ouvert

    def on_key(self, event: events.Key) -> None:
        """On key.

        Args:
            event: Description.
        """
        if event.key == "escape":
            self._on_done(False)
            self.dismiss()


# ── Fonctions interface ──────────────────────────────────────────


async def handle_ssh(app, cmd_line: str) -> object:
    # ── Connexion vers une nouvelle cible SSH ────────────────────
    """Handle ssh.

    Args:
        app: Description.
        cmd_line: Description.
    """
    from forge_app_context import app_ctx as _actx

    _ac = _actx()
    ssh_manager = _ac.ssh_manager
    version_manager = _ac.version_manager
    chat = app._chat_log()
    # @ssh <host> [user] [port] [keypath]
    # @ssh save   — enregistre la session courante dans Nokido.env
    # @ssh status — affiche la connexion courante
    _ssh_parts = cmd_line[4:].strip().split()
    _ssh_sub = _ssh_parts[0].lower() if _ssh_parts else "help"

    if _ssh_sub == "status":
        _sudo_s = "[green]oui[/]" if ssh_manager.sudo_available else "[yellow]non[/]"
        chat.write(
            "[bold]Connexion SSH courante :[/]\n"
            f"  Hôte : [bold]{_get_settings().ssh_host or '—'}[/] "
            f"port={_get_settings().ssh_port}  user=[bold]{_get_settings().ssh_user or '—'}[/]\n"
            f"  Clé  : [dim]{_get_settings().private_key_path or '—'}[/]\n"
            f"  Sudo : {_sudo_s}"
        )

    elif _ssh_sub == "save":
        # Écrire la config courante dans Nokido.env
        if not _get_settings().ssh_host:
            chat.write("[yellow]⚠ Aucune connexion SSH active à sauvegarder.[/]")
        else:
            try:
                env_path = _ROOT_DIR / "Nokido.env"
                content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
                import re as _re2

                def _set_v(c, k, v) -> object:
                    """Set v.

                    Args:
                        c: Description.
                        k: Description.
                        v: Description.
                    """
                    pat = _re2.compile(rf"^{k}=.*$", _re2.MULTILINE)
                    ln = f"{k}={v}"
                    return pat.sub(ln, c) if pat.search(c) else c.rstrip("\n") + f"\n{ln}\n"

                content = _set_v(content, "SSH_HOST", _get_settings().ssh_host)
                content = _set_v(content, "SSH_PORT", str(_get_settings().ssh_port))
                content = _set_v(content, "SSH_USER", _get_settings().ssh_user)
                content = _set_v(content, "PRIVATE_KEY_PATH", str(_get_settings().private_key_path or ""))
                env_path.write_text(content, encoding="utf-8")
                chat.write("[green]✅ Connexion SSH enregistrée dans Nokido.env[/]")
            except Exception as _e:
                chat.write(f"[red]❌ Écriture Nokido.env : {escape(str(_e))}[/]")

    elif len(_ssh_parts) >= 1 and _ssh_sub not in ("help", "save", "status"):
        # @ssh <host> [user] [port] [keypath]
        _new_host = _ssh_parts[0]
        _new_user = _ssh_parts[1] if len(_ssh_parts) > 1 else _get_settings().ssh_user
        _new_port = int(_ssh_parts[2]) if len(_ssh_parts) > 2 else _get_settings().ssh_port
        _new_key = Path(_ssh_parts[3]) if len(_ssh_parts) > 3 else _get_settings().private_key_path

        if not _new_user or not _new_key:
            chat.write(
                "[yellow]⚠ Usage : @ssh <host> [user] [port] [keypath][/]\n"
                "  Exemple : @ssh localhost admin 22 ~/.ssh/id_rsa\n"
                "  [dim]user/port/keypath optionnels si déjà configurés[/dim]"
            )
        else:
            chat.write(f"[dim]🔌 Connexion vers {_new_user}@{_new_host}:{_new_port}…[/]")

            async def _reconnect(_h=_new_host, _u=_new_user, _p=_new_port, _k=_new_key) -> None:
                """Reconnect.

                Args:
                    _h: Description.
                    _u: Description.
                    _p: Description.
                    _k: Description.
                """
                try:
                    # Fermer la connexion existante
                    await ssh_manager.close()
                    # Mettre à jour settings en session
                    _get_settings().ssh_host = _h
                    _get_settings().ssh_user = _u
                    _get_settings().ssh_port = _p
                    _get_settings().private_key_path = _k
                    os.environ["SSH_HOST"] = _h
                    os.environ["SSH_USER"] = _u
                    os.environ["SSH_PORT"] = str(_p)
                    os.environ["PRIVATE_KEY_PATH"] = str(_k)
                    # Reconnecter
                    await ssh_manager.connect()
                    # Récupérer hostname
                    _hn, _kern = "", ""
                    try:
                        _o, _, _ = await run_ssh("hostname -f 2>/dev/null || hostname")
                        _hn = _strip_ssh_output(_o)
                    except Exception:
                        _hn = _h
                    try:
                        _o2, _, _ = await run_ssh("uname -r")
                        _kern = _strip_ssh_output(_o2)
                    except Exception:
                        pass
                    _ks = f" · [dim]kernel {_kern}[/]" if _kern else ""
                    chat.write(
                        f"[green]✅ SSH[/] [bold]{_hn}[/] [dim]({_h}:{_p})[/] "
                        f"sudo={'[green]oui[/]' if ssh_manager.sudo_available else '[yellow]non[/]'}{_ks}\n"
                        f"  [dim]@ssh save pour enregistrer dans Nokido.env[/]"
                    )
                    app._set_ssh_mode(True, hostname=_hn)
                    app.sub_title = f"v{version_manager.current_version} · {_hn}"
                except Exception as _err:
                    chat.write(f"[red]❌ SSH {_h} : {escape(str(_err))}[/]")

            asyncio.create_task(_reconnect())

    else:
        chat.write(
            "[bold]@ssh[/] <host> [user] [port] [keypath]  — connexion vers une nouvelle cible\n"
            "  @ssh status   — connexion active\n"
            "  @ssh save     — enregistre dans Nokido.env\n"
            "[dim]Exemples :\n"
            "  @ssh localhost\n"
            "  @ssh localhost admin 22 ~/.ssh/id_rsa[/]"
        )


def handle_set_ssh_mode(app, connected: bool, hostname: str = "") -> None:
    """
    Bascule le layout selon l'état SSH.
    connected=False → terminal masqué, chat pleine largeur
    connected=True  → terminal visible, splitter actif
    hostname        → vrai nom machine (pas l'IP) pour le titre terminal
    """
    logger.debug(f"[_set_ssh_mode] connected={connected} hostname={hostname!r}")
    app._ssh_connected = connected
    if hostname:
        app._pending_hostname = hostname
    try:
        term = app.query_one("#terminal-panel")
        split = app.query_one("#v-splitter")
        title = app.query_one("#term-title")
        chat = app.query_one("#chat-panel")
        banner = app.query_one("#no-ssh-banner")

        if connected:
            _host = hostname or app._pending_hostname or _get_settings().ssh_host or "SSH"
            title.update(f" [bold #3fb950]🖥 {_host}[/]  [dim]Ctrl+T · focus[/]")
            logger.info(f"[_set_ssh_mode] titre mis à jour → {_host!r}")
            # display=True en premier → Textual alloue l'espace avant remove_class
            term.display = True
            split.display = True
            title.display = True
            term.remove_class("hidden")
            split.remove_class("hidden")
            title.remove_class("hidden")
            chat.remove_class("expanded")
            banner.remove_class("visible")
            chat.styles.width = "1fr"
            term.styles.width = "1fr"
            app.refresh(layout=True)
        else:
            term.add_class("hidden")
            split.add_class("hidden")
            title.add_class("hidden")
            chat.add_class("expanded")
            banner.add_class("visible")
            banner.update("[dim]Pas de SSH · [bold]@ssh <host>[/] pour ouvrir le terminal[/]")
    except Exception as _e:
        logger.debug(f"[_set_ssh_mode] exception={_e!r}, call_later → _apply_pending_ssh_mode")
        app.call_later(app._apply_pending_ssh_mode)


def handle_apply_pending_ssh_mode(app) -> None:
    """Applique l'état SSH différé (appelé après mount des widgets)."""
    if app._ssh_connected and app._pending_hostname:
        logger.debug(f"[_apply_pending_ssh_mode] hostname={app._pending_hostname!r}")
        app._set_ssh_mode(True, hostname=app._pending_hostname)


def handle_ssh_setup_wizard() -> bool:
    """
    Lance un assistant interactif en console pour configurer la connexion SSH.
    Proposé uniquement si SSH_HOST / SSH_USER / PRIVATE_KEY_PATH sont absents.

    Retourne True si la configuration a été saisie (session ou fichier),
    False si l'utilisateur a annulé.

    Modes :
      1. Session uniquement  — injecté dans os.environ, perdu à la fermeture
      2. Enregistrer         — écrit dans Nokido.env (persist)
    """

    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║   ⚒  La Forge — Configuration SSH requise       ║")
    print("  ║                                                  ║")
    print("  ║  SSH_HOST / SSH_USER / PRIVATE_KEY_PATH          ║")
    print("  ║  absents dans Nokido.env                        ║")
    print("  ╚══════════════════════════════════════════════════╝")
    print()

    def _ask(prompt: str, default: str = "") -> str:
        """Ask.

        Args:
            prompt: Description.
            default: Description.
        """
        try:
            val = input(f"  {prompt}" + (f" [{default}]" if default else "") + " : ").strip()
            return val or default
        except (EOFError, KeyboardInterrupt):
            return default

    # ── Saisie des valeurs ────────────────────────────────────────────────────
    host = ""
    while not host:
        host = _ask("Adresse IP / hostname SSH_HOST")
        if not host:
            print("  ⚠  SSH_HOST obligatoire.")

    port = _ask("Port SSH (SSH_PORT)", "22")
    try:
        port = str(int(port))
    except ValueError:
        port = "22"

    user = ""
    while not user:
        user = _ask("Utilisateur SSH_USER")
        if not user:
            print("  ⚠  SSH_USER obligatoire.")

    key_path = ""
    while not key_path:
        key_path = _ask("Chemin clé privée PRIVATE_KEY_PATH")
        if not key_path:
            print("  ⚠  PRIVATE_KEY_PATH obligatoire.")
        elif not Path(key_path).exists():
            print(f"  ⚠  Fichier introuvable : {key_path}")
            if _ask("Continuer quand même ? (o/N)", "N").lower() not in ("o", "oui", "y", "yes"):
                key_path = ""

    # ── Choix persistence ─────────────────────────────────────────────────────
    print()
    print("  Comment souhaitez-vous enregistrer ces paramètres ?")
    print("  [1] Session uniquement  — actif jusqu'à la fermeture de La Forge")
    print("  [2] Enregistrer dans Nokido.env  — persistant pour les prochains lancements")
    print("  [0] Annuler")
    print()
    choice = _ask("Choix", "1")

    if choice == "0":
        print("  Annulé.")
        return False

    # Injecter dans os.environ (toujours, quelle que soit l'option)
    os.environ["SSH_HOST"] = host
    os.environ["SSH_PORT"] = port
    os.environ["SSH_USER"] = user
    os.environ["PRIVATE_KEY_PATH"] = key_path

    if choice == "2":
        # ── Écrire dans Nokido.env ───────────────────────────────────────────
        env_path = _ROOT_DIR / "Nokido.env"
        try:
            # Lire le contenu existant
            existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""

            # Remplacer ou ajouter chaque variable
            def _set_var(content: str, key: str, value: str) -> str:
                """Set var.

                Args:
                    content: Description.
                    key: Description.
                    value: Description.
                """
                import re as _re

                pattern = _re.compile(rf"^{key}=.*$", _re.MULTILINE)
                line = f"{key}={value}"
                if pattern.search(content):
                    return pattern.sub(line, content)
                return content.rstrip("\n") + f"\n{line}\n"

            content = existing
            content = _set_var(content, "SSH_HOST", host)
            content = _set_var(content, "SSH_PORT", port)
            content = _set_var(content, "SSH_USER", user)
            content = _set_var(content, "PRIVATE_KEY_PATH", key_path)

            env_path.write_text(content, encoding="utf-8")
            print(f"  ✅ Enregistré dans {env_path.resolve()}")
        except Exception as _e:
            print(f"  ⚠  Impossible d'écrire Nokido.env : {_e}")
            print("  Session uniquement.")
    else:
        print("  ✅ Paramètres SSH actifs pour cette session.")

    print()
    return True


async def run_ci_pipeline(
    self,
    repo_url: str,
    branch: str = "main",
    workdir: str = "/tmp/ci-repo",
    on_step: Optional[callable] = None,
) -> str:
    """
    Pipeline CI complet :
    1. clone/pull  2. checkout  3. détection auto (Makefile/pytest/npm/docker)
    4. test         5. build     6. optionnel: docker build + deploy
    on_step(icon, msg) appelé à chaque étape pour l'UI.
    """
    results = []

    def _ok(msg):
        """ ok."""
        return results.append(f"✅ {msg}")

    def _ko(msg):
        """ ko."""
        return results.append(f"❌ {msg}")

    def _info(msg):
        """ info."""
        return results.append(f"  ℹ {msg}")

    def _step(icon: str, msg: str) -> None:
        """Step.

        Args:
            icon: Description.
            msg: Description.
        """
        results.append(f"{icon} {msg}")
        if on_step:
            try:
                on_step(icon, msg)
            except Exception:
                pass

    # 1. Clone ou pull
    _step("🔄", f"Sync {repo_url} ({branch})")
    try:
        clone_cmd = (
            f"[ -d {workdir}/.git ] && "
            f"(cd {workdir} && git fetch origin && git reset --hard origin/{branch}) || "
            f"git clone --depth=1 -b {branch} {repo_url} {workdir}"
        )
        out = await self.run_ssh_command(clone_cmd)
        _ok(f"Dépôt prêt dans {workdir}")
    except RuntimeError as e:
        _ko(f"Clone/pull échoué : {e}")
        self._record(repo_url, "FAILED", str(e))
        return "\n".join(results)

    # 2. Détection de l'outillage
    _step("🔍", "Détection de l'outillage…")
    try:
        ls_out = await self.run_ssh_command(f"ls {workdir}/")
        has_make = "Makefile" in ls_out or "makefile" in ls_out
        has_pytest = "pytest.ini" in ls_out or "setup.cfg" in ls_out or "pyproject.toml" in ls_out
        has_npm = "package.json" in ls_out
        has_docker = "Dockerfile" in ls_out
        has_compose = "docker-compose" in ls_out or "compose.yml" in ls_out
        tools = []
        if has_make:
            tools.append("Makefile")
        if has_pytest:
            tools.append("pytest")
        if has_npm:
            tools.append("npm")
        if has_docker:
            tools.append("Docker")
        if has_compose:
            tools.append("Compose")
        _info(f"Outillage détecté : {', '.join(tools) or 'générique'}")
    except RuntimeError:
        has_make = has_pytest = has_npm = has_docker = has_compose = False

    # 3. Tests
    _step("🧪", "Exécution des tests…")
    test_ok = False
    if has_make:
        try:
            out = await self.run_ssh_command(f"cd {workdir} && make test 2>&1 | tail -20")
            _ok(f"make test OK\n{out[:300]}")
            test_ok = True
        except RuntimeError as e:
            _ko(f"make test : {str(e)[:200]}")
    elif has_pytest:
        try:
            out = await self.run_ssh_command(f"cd {workdir} && python -m pytest -x --tb=short 2>&1 | tail -30")
            _ok(f"pytest OK\n{out[:300]}")
            test_ok = True
        except RuntimeError as e:
            _ko(f"pytest : {str(e)[:200]}")
    elif has_npm:
        try:
            out = await self.run_ssh_command(f"cd {workdir} && npm test 2>&1 | tail -20")
            _ok(f"npm test OK\n{out[:200]}")
            test_ok = True
        except RuntimeError as e:
            _ko(f"npm test : {str(e)[:200]}")
    else:
        _info("Aucun système de test détecté — étape sautée")
        test_ok = True

    # 4. Build
    _step("🔨", "Build…")
    if has_make:
        try:
            out = await self.run_ssh_command(f"cd {workdir} && make build 2>&1 | tail -20")
            _ok(f"make build OK\n{out[:200]}")
        except RuntimeError as e:
            _ko(f"make build : {str(e)[:200]}")
    elif has_npm:
        try:
            out = await self.run_ssh_command(f"cd {workdir} && npm run build 2>&1 | tail -20")
            _ok(f"npm build OK\n{out[:200]}")
        except RuntimeError as e:
            _ko(f"npm build : {str(e)[:200]}")
    else:
        _info("Pas de build configuré")

    # 5. Docker build (si Dockerfile présent)
    if has_docker:
        _step("🐳", "Docker build…")
        img_name = repo_url.rstrip("/").split("/")[-1].lower() or "app"
        try:
            out = await self.run_ssh_command(f"cd {workdir} && docker build -t {img_name}:{branch} . 2>&1 | tail -10")
            _ok(f"Image {img_name}:{branch} construite\n{out[:200]}")
        except RuntimeError as e:
            _ko(f"docker build : {str(e)[:200]}")

    # 6. Docker Compose up (si compose présent)
    if has_compose:
        _step("🚢", "Docker Compose up…")
        try:
            out = await self.run_ssh_command(f"cd {workdir} && docker compose up -d --build 2>&1 | tail -10")
            _ok(f"Compose déployé\n{out[:200]}")
        except RuntimeError as e:
            _ko(f"docker compose : {str(e)[:200]}")

    final_status = "SUCCESS" if test_ok else "FAILED"
    self._record(repo_url, final_status, results[-1] if results else "")
    if final_status == "SUCCESS":
        self._send_notification(f"✅ CI {repo_url}@{branch} réussi")
    else:
        self._send_notification(f"❌ CI {repo_url}@{branch} échoué")
    return "\n".join(results)
