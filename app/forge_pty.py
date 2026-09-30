"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_053059_groqcerber
#FORGE:[score:90|agent:groq-cerberus|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings Google-style complets
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:90|agent:groq-cerberus|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
forge_pty.py — Terminal PTY interactif sur SSH (asyncssh + pyte + Textual).

Fournit PTYTerminal : Widget Textual qui ouvre un shell interactif sur le
serveur SSH configuré dans settings.ssh_host.

Caractéristiques :
  - Scroll-back : historique 500 lignes via pyte.HistoryScreen
  - Curseur bloc inversé rendu en temps réel
  - Resize adaptatif (watch_size, on_resize)
  - KEY_MAP : toutes les touches spéciales + Ctrl+lettre
  - inject(cmd) : envoie une commande sans bloquer la TUI
  - Touches APP_RESERVED déléguées à DevOpsApp (Ctrl+L, F1-F5…)

Importé par Nokido.py :
    from forge_pty import PTYTerminal, get_pty_class
"""


import asyncio
import logging

from app.core.settings import get_settings as _forge_settings  # noqa: F401


class _SettingsProxy:
    def __getattr__(self, k: str) -> object | None:
        """Getattr.

        Args:
            k: Description.
        Returns:
            Attribut de settings ou None si non trouvé.
        """
        s = _forge_settings()
        return getattr(s, k, None) if s else None


settings = _SettingsProxy()


logger = logging.getLogger(__name__)

# ── Dépendances optionnelles ──────────────────────────────────────────────────
try:
    import pyte

    HAS_PYTE = True
except ImportError:
    HAS_PYTE = False

try:
    import asyncssh

    HAS_ASYNCSSH = True
except ImportError:
    HAS_ASYNCSSH = False

try:
    from textual.app import ComposeResult
    from textual.widget import Widget
    from textual.widgets import RichLog
    from textual import events
    from rich.text import Text

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

# Injecté par Nokido.py via configure()
_settings = None


def configure(settings) -> None:
    """Configure les paramètres de l'application.

    Args:
        settings: Paramètres de l'application.
    Returns:
        None
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    settings = _ac.settings
    global _settings
    _settings = settings


def _get_settings() -> object:
    """Récupère les paramètres de l'application.

    Returns:
        Paramètres de l'application.
    Raises:
        RuntimeError: Si les paramètres n'ont pas été configurés.
    """
    if _settings is None:
        raise RuntimeError("forge_pty.configure(settings) n'a pas été appelé")
    return _settings


# =============================================================================
# Guard — pas de PTYTerminal si Textual ou pyte manquent
# =============================================================================
if not (HAS_TEXTUAL and HAS_PYTE):

    class PTYTerminal:  # stub minimal pour import sans crash
        """Stub pour PTYTerminal."""

        def __init__(self) -> None:
            """Initialise le stub."""
            pass

        async def connect(self) -> bool:
            """Connecte au serveur SSH.

            Returns:
                False car la connexion n'est pas possible sans Textual et pyte.
            """
            return False

        async def inject(self, cmd: str, echo: bool = True) -> None:
            """Injecte une commande dans le terminal.

            Args:
                cmd: Commande à injecter.
                echo: Affiche la commande dans le terminal.
            Returns:
                None
            """
            pass

        async def disconnect(self) -> None:
            """Déconnecte du serveur SSH.

            Returns:
                None
            """
            pass
else:

    class PTYTerminal(Widget):
        """Terminal interactif basé sur pyte et asyncssh."""

        # Touches réservées à l'App — PTY ne les consomme pas
        _APP_RESERVED: frozenset = frozenset(
            {
                "ctrl+l",
                "ctrl+c",
                "ctrl+v",
                "ctrl+z",
                "ctrl+shift+c",
                "ctrl+shift+v",
                "f1",
                "f2",
                "f3",
                "f4",
                "f5",
                "ctrl+q",
                "ctrl+p",
            }
        )

        # PTYTerminal doit être focusable pour recevoir les keystrokes
        can_focus = True

        def __init__(self) -> None:
            """Initialise le terminal."""
            super().__init__()
            self._cols = 80
            self._rows = 24
            # HistoryScreen garde les lignes qui scrollent hors écran
            try:
                self._screen = pyte.HistoryScreen(self._cols, self._rows, history=500)
            except AttributeError:
                self._screen = pyte.Screen(self._cols, self._rows)
            self._stream = pyte.Stream(self._screen)
            self._input_queue = asyncio.Queue()
            self._connection = None
            self._channel = None
            self._connected = False
            self._read_task = None
            self._write_task = None
            self._log = None
            self._cursor_timer = None

        def compose(self) -> ComposeResult:
            """Compose le terminal.

            Returns:
                ComposeResult du terminal.
            """
            rl = RichLog(id="pty-log", wrap=False, markup=False, auto_scroll=True)
            rl.can_focus = False
            yield rl

        async def on_mount(self) -> None:
            """On mount.

            Returns:
                None
            """
            self._log = self.query_one("#pty-log", RichLog)
            self._sync_size()
            # Timer de refresh pour le curseur (visible même quand idle)
            self._cursor_timer = self.set_interval(0.6, self._cursor_refresh)

        def _cursor_refresh(self) -> None:
            """Refresh périodique pour garder le curseur visible.

            Returns:
                None
            """
            if self._connected:
                self._refresh()

        def _sync_size(self) -> None:
            """Sync size.

            Returns:
                None
            """
            try:
                w, h = self.size.width, self.size.height
                nc = max(40, w - 1)  # -1 pour le scrollbar
                nr = max(8, h - 1)
                if nc != self._cols or nr != self._rows:
                    self._cols = nc
                    self._rows = nr
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
            Returns:
                None
            """
            self._sync_size()
            self._refresh_log()

        def watch_size(self, size) -> None:
            """Watcher réactif — déclenché sur TOUT changement de taille (splitter, fenêtre).

            Args:
                size: Description.
            Returns:
                None
            """
            self._sync_size()
            self._refresh_log()

        def _refresh_log(self) -> None:
            """Force le RichLog à recalculer sa largeur d'affichage.

            Returns:
                None
            """
            try:
                log = self.query_one("#pty-log", RichLog)
                log.refresh(layout=True)
                log._max_width = max(40, self.size.width - 1)
            except Exception:
                pass

        async def connect(self) -> bool:
            """Connecte au serveur SSH.

            Returns:
                True si la connexion est établie, False sinon.
            Raises:
                Exception: Si la connexion échoue.
            """
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
            """Read loop.

            Returns:
                None
            Raises:
                Exception: Si la lecture échoue.
            """
            try:
                while self._connected:
                    try:
                        data = await asyncio.wait_for(self._channel.stdout.read(4096), timeout=0.05)
                        if data:
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
            """Write loop.

            Returns:
                None
            Raises:
                Exception: Si l'écriture échoue.
            """
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
            """Refresh.

            Returns:
                None
            """
            if not self._log:
                return
            try:
                from rich.text import Text

                self._log.clear()
                w = self._cols
                cursor_y = self._screen.cursor.y
                cursor_x = self._screen.cursor.x

                # Historique scroll-back (lignes qui ont scrollé hors écran)
                if hasattr(self._screen, "history") and hasattr(self._screen.history, "top"):
                    for hist_line in self._screen.history.top:
                        # hist_line est un dict {col: pyte.Char} — reconstruire le texte
                        if isinstance(hist_line, dict):
                            chars = []
                            for col in range(w):
                                c = hist_line.get(col)
                                chars.append(c.data if c else " ")
                            self._log.write("".join(chars))
                        else:
                            self._log.write(str(hist_line)[:w])

                # Écran courant pyte avec curseur
                for row_idx, line in enumerate(self._screen.display):
                    if len(line) < w:
                        padded = line + " " * (w - len(line))
                    elif len(line) > w:
                        padded = line[:w]
                    else:
                        padded = line
                    # Curseur bloc inversé
                    if row_idx == cursor_y and 0 <= cursor_x < len(padded):
                        t = Text(padded)
                        t.stylize("reverse bold", cursor_x, cursor_x + 1)
                        self._log.write(t)
                    else:
                        self._log.write(padded)
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

        def on_click(self, event) -> None:
            """Clic PTY → PTYTerminal prend le focus (pour recevoir les keystrokes).

            Args:
                event: Description.
            Returns:
                None
            """
            try:
                event.stop()
                self.focus()  # focus sur le Widget, pas le RichLog interne
            except Exception:
                pass

        def on_mouse_down(self, event) -> None:
            """Mousedown PTY — capture pour éviter crash Textual.

            Args:
                event: Description.
            Returns:
                None
            """
            try:
                event.stop()
            except Exception:
                pass

        async def on_key(self, event: events.Key) -> None:
            """On key.

            Args:
                event: Description.
            Returns:
                None
            """
            if not self._connected:
                return
            # Laisser l'App gérer ses bindings prioritaires (clipboard, focus, agents)
            if event.key in self._APP_RESERVED:
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

            Args:
                cmd: Commande à envoyer.
                echo: Affiche la commande dans le terminal.
            Returns:
                None
            """
            if not self._connected:
                if self._log:
                    self._log.write(f"[non connecté] {cmd}")
                return
            # Écho local immédiat — évite le blanc avant réponse serveur
            if echo and self._log and cmd.strip():
                try:
                    self._log.write(f"$ {cmd}")
                except Exception:
                    pass
            await self._input_queue.put(cmd + "\r")

        async def disconnect(self) -> None:
            """Déconnecte du serveur SSH.

            Returns:
                None
            """
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


def get_pty_class() -> object:
    """Retourne PTYTerminal si disponible, sinon None.

    Returns:
        PTYTerminal si disponible, sinon None.
    """
    return PTYTerminal if (HAS_TEXTUAL and HAS_PYTE) else None


__all__ = ["PTYTerminal", "get_pty_class", "configure"]
