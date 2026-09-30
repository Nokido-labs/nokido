"""
forge_pty_widget.py - Nokido PTY Textual widget (moderne)
===========================================================

Successeur moderne de PTYTerminal (Nokido_v13.6.py L1009-1290).
Différences vs v13 :
- Pipeline découplé : `PTYSession` async-pur (testable hors UI)
- Hook EventBus Nokido `pty.*` (connect / disconnect / error / data)
- RBAC ring-check via `forge_rbac_mapping` : refuse si ring > seuil
- Plus de monolithe — widget standalone, importé par TUI v3 quand demandé

API publique :
    from forge_pty_widget import PTYSession, PTYTerminalWidget

    # Pipeline pur (sans Textual)
    sess = PTYSession(host, port, user, password=...)
    sess.on_screen_update = callback
    await sess.connect()
    await sess.inject("uname -a")
    await sess.disconnect()

    # Widget Textual (consomme PTYSession)
    term = PTYTerminalWidget(host, port, user, password=..., entity_id="agt_x")
    # mount(term) → connecte au mount + render auto

    # Pipeline LOCAL ConPTY (CLI OAuth vivants : claude, gemini — postal/secrétaire)
    sess = LocalPTYSession(["claude"], cwd=repo_dir)
    await sess.connect()
    await sess.inject("message du correspondant")
    await sess.disconnect()

Dépendances : pyte, asyncssh, pywinpty (optionnels — degrade gracieux si absents).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger(__name__)

# ── Imports optionnels ────────────────────────────────────────────────────────
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
    import winpty  # pywinpty — ConPTY Windows (sessions CLI locales)

    HAS_WINPTY = True
except ImportError:
    HAS_WINPTY = False

try:
    from textual.widgets import RichLog
    from textual.containers import Vertical
    from textual import events

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False
    Vertical = object  # type: ignore[assignment,misc]

# ── EventBus hook (silent fail si bus indispo) ────────────────────────────────
_EVENT_BUS = None


def _emit(topic: str, kind: str, data: dict, agent: str = "PTY") -> None:
    global _EVENT_BUS
    try:
        if _EVENT_BUS is None:
            import sys

            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from nokido_agent.app.forge_state_manager import EventBus, get_state_manager

            _EVENT_BUS = EventBus(get_state_manager())
        _EVENT_BUS.publish(topic=topic, kind=kind, data=data, agent=agent, trusted=True)
    except Exception as e:
        logger.debug(f"EventBus emit skipped: {e}")


# ── RBAC ring check ───────────────────────────────────────────────────────────


def _ring_allowed(entity_id: str, max_ring: int = 2) -> tuple[bool, str]:
    """True si ring(entity_id) <= max_ring (TRUSTED ou mieux).
    Returns (allowed, reason)."""
    if not entity_id:
        return True, ""  # appel direct (humain TUI ring 0)
    try:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app.forge_rbac_mapping import get_mapping

        m = get_mapping(entity_id)
    except Exception as e:
        return True, f"rbac unavailable ({e})"
    if not m:
        return False, f"entity inconnue: {entity_id}"
    ring = m.get("ring_level", 4)
    if ring > max_ring:
        return False, f"ring {ring} > max_ring {max_ring} (PTY interdit)"
    return True, ""


# ── PTYSession (pipeline asyncio pur) ─────────────────────────────────────────


class PTYConnectError(Exception):
    pass


class PTYSession:
    """Session SSH PTY pure — pas de dépendance UI.

    Émet sur EventBus : pty.connect / pty.error / pty.bytes / pty.disconnect
    """

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "admin",
        password: Optional[str] = None,
        client_keys: Optional[list] = None,
        known_hosts: Optional[object] = None,
        term_type: str = "xterm-256color",
        term_cols: int = 80,
        term_rows: int = 24,
        history_lines: int = 500,
        connect_timeout: float = 10.0,
        on_screen_update: Optional[Callable[[], None]] = None,
        entity_id: str = "",
    ) -> None:
        if not HAS_PYTE:
            raise RuntimeError("pyte manquant (pip install pyte)")
        if not HAS_ASYNCSSH:
            raise RuntimeError("asyncssh manquant (pip install asyncssh)")

        self.host = host
        self.port = int(port)
        self.username = username
        self.entity_id = entity_id
        self._password = password
        self._client_keys = client_keys
        self._known_hosts = known_hosts
        self.term_type = term_type
        self._cols = int(term_cols)
        self._rows = int(term_rows)
        self._history_lines = int(history_lines)
        self._connect_timeout = float(connect_timeout)
        self.on_screen_update = on_screen_update

        try:
            self._screen = pyte.HistoryScreen(self._cols, self._rows, history=self._history_lines)
        except AttributeError:
            self._screen = pyte.Screen(self._cols, self._rows)
        self._stream = pyte.Stream(self._screen)

        self._input_queue: asyncio.Queue = asyncio.Queue()
        self._connection = None
        self._channel = None
        self._connected = False
        self._read_task: Optional[asyncio.Task] = None
        self._write_task: Optional[asyncio.Task] = None
        self._bytes_received = 0
        self._last_error: Optional[str] = None

    # ── propriétés ──────────────────────────────────────────────────────
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def bytes_received(self) -> int:
        return self._bytes_received

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ── rendu (snapshot) ────────────────────────────────────────────────
    def get_display(self) -> list[str]:
        try:
            return list(self._screen.display)
        except Exception:
            return []

    def get_cursor(self) -> tuple[int, int]:
        try:
            return (self._screen.cursor.x, self._screen.cursor.y)
        except Exception:
            return (0, 0)

    # ── connexion ───────────────────────────────────────────────────────
    async def connect(self) -> bool:
        ok, reason = _ring_allowed(self.entity_id)
        if not ok:
            self._last_error = f"RBAC: {reason}"
            _emit("pty.rbac_denied", "error", {"entity_id": self.entity_id, "reason": reason})
            return False
        if self._connected:
            return True
        try:
            kwargs = {
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "known_hosts": self._known_hosts,
            }
            if self._password is not None:
                kwargs["password"] = self._password
            if self._client_keys is not None:
                kwargs["client_keys"] = self._client_keys
            self._connection = await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=self._connect_timeout)
            self._channel = await self._connection.create_process(
                term_type=self.term_type,
                term_size=(self._cols, self._rows),
                request_pty=True,
            )
            self._connected = True
            self._last_error = None
            self._password = None  # drop après auth
            self._read_task = asyncio.create_task(self._read_loop(), name="pty-read")
            self._write_task = asyncio.create_task(self._write_loop(), name="pty-write")
            _emit(
                "pty.connect",
                "success",
                {"host": self.host, "port": self.port, "user": self.username, "entity_id": self.entity_id},
            )
            return True
        except asyncio.TimeoutError:
            self._last_error = f"timeout {self._connect_timeout}s"
            await self._cleanup_partial()
            _emit("pty.error", "timeout", {"host": self.host, "port": self.port})
            return False
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            await self._cleanup_partial()
            _emit("pty.error", "exception", {"host": self.host, "port": self.port, "err": self._last_error[:120]})
            return False

    async def _cleanup_partial(self) -> None:
        try:
            if self._connection is not None:
                self._connection.close()
                await self._connection.wait_closed()
        except Exception:
            pass
        self._connection = None
        self._channel = None
        self._connected = False

    # ── boucles IO ──────────────────────────────────────────────────────
    async def _read_loop(self) -> None:
        try:
            while self._connected:
                try:
                    data = await asyncio.wait_for(self._channel.stdout.read(4096), timeout=0.05)
                    if not data:
                        self._connected = False
                        self._last_error = "EOF distant"
                        _emit("pty.disconnect", "eof", {"host": self.host, "port": self.port})
                        self._notify()
                        return
                    if isinstance(data, bytes):
                        text = data.decode("utf-8", errors="replace")
                    else:
                        text = data
                    self._stream.feed(text)
                    self._bytes_received += len(text)
                    self._notify()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._connected = False
                    self._last_error = f"read: {type(exc).__name__}"
                    _emit("pty.error", "read_loop", {"err": self._last_error})
                    self._notify()
                    return
        except asyncio.CancelledError:
            pass

    async def _write_loop(self) -> None:
        try:
            while self._connected:
                try:
                    data = await asyncio.wait_for(self._input_queue.get(), timeout=0.5)
                    if self._channel and not self._channel.stdin.is_closing():
                        self._channel.stdin.write(data)
                        await self._channel.stdin.drain()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(f"write_loop: {exc}")
                    return
        except asyncio.CancelledError:
            pass

    def _notify(self) -> None:
        cb = self.on_screen_update
        if cb is None:
            return
        try:
            cb()
        except Exception:
            logger.exception("on_screen_update raised")

    # ── input ────────────────────────────────────────────────────────────
    async def send_bytes(self, data) -> None:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        await self._input_queue.put(data)

    async def inject(self, cmd: str, newline: str = "\r") -> None:
        await self._input_queue.put(cmd + newline)

    def resize(self, cols: int, rows: int) -> None:
        cols = max(20, int(cols))
        rows = max(5, int(rows))
        if cols == self._cols and rows == self._rows:
            return
        self._cols = cols
        self._rows = rows
        try:
            self._screen.resize(rows, cols)
        except Exception:
            pass
        if self._connected and self._channel:
            try:
                self._channel.change_terminal_size(cols, rows)
            except Exception:
                pass

    # ── teardown ─────────────────────────────────────────────────────────
    async def disconnect(self) -> None:
        was = self._connected
        self._connected = False
        for task in (self._read_task, self._write_task):
            if task and not task.done():
                task.cancel()
        pending = [t for t in (self._read_task, self._write_task) if t]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._channel:
            try:
                self._channel.stdin.write_eof()
            except Exception:
                pass
            try:
                self._channel.close()
            except Exception:
                pass
        if self._connection:
            try:
                self._connection.close()
                await self._connection.wait_closed()
            except Exception:
                pass
        self._channel = None
        self._connection = None
        if was:
            _emit("pty.disconnect", "clean", {"host": self.host, "port": self.port, "bytes": self._bytes_received})


# ── LocalPTYSession (ConPTY local — sessions CLI OAuth vivantes) ──────────────


class LocalPTYSession:
    """Session PTY LOCALE (ConPTY Windows via pywinpty) — même interface que
    PTYSession, transport process local au lieu de SSH.

    Usage cible : sessions interactives VIVANTES des CLI OAuth (claude, gemini)
    possédées par Nokido — la secrétaire postale inject() dedans, pyte rend
    l'écran, EventBus pty.* trace le flux (validé PoC C:/tmp/poc_conpty_claude.py).

    winpty.PtyProcess est BLOQUANT → IO via asyncio.to_thread. spawn : argv en
    LISTE sans quotes (PtyProcess.spawn fait shlex+isfile, un chemin quoté échoue).
    """

    def __init__(
        self,
        argv: list[str] | str,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        term_cols: int = 120,
        term_rows: int = 40,
        history_lines: int = 500,
        spawn_timeout: float = 20.0,
        on_screen_update: Optional[Callable[[], None]] = None,
        entity_id: str = "",
    ) -> None:
        if not HAS_PYTE:
            raise RuntimeError("pyte manquant (pip install pyte)")
        if not HAS_WINPTY:
            raise RuntimeError("pywinpty manquant (pip install pywinpty)")

        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.entity_id = entity_id
        self._cols = int(term_cols)
        self._rows = int(term_rows)
        self._history_lines = int(history_lines)
        self._spawn_timeout = float(spawn_timeout)
        self.on_screen_update = on_screen_update

        try:
            self._screen = pyte.HistoryScreen(self._cols, self._rows, history=self._history_lines)
        except AttributeError:
            self._screen = pyte.Screen(self._cols, self._rows)
        self._stream = pyte.Stream(self._screen)

        self._input_queue: asyncio.Queue = asyncio.Queue()
        self._proc = None
        self._connected = False
        self._read_task: Optional[asyncio.Task] = None
        self._write_task: Optional[asyncio.Task] = None
        self._bytes_received = 0
        self._last_error: Optional[str] = None

    # ── propriétés (mêmes accesseurs que PTYSession) ─────────────────────
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def bytes_received(self) -> int:
        return self._bytes_received

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def is_alive(self) -> bool:
        try:
            return bool(self._proc and self._proc.isalive())
        except Exception:
            return False

    # ── rendu (snapshot) ────────────────────────────────────────────────
    def get_display(self) -> list[str]:
        try:
            return list(self._screen.display)
        except Exception:
            return []

    def get_cursor(self) -> tuple[int, int]:
        try:
            return (self._screen.cursor.x, self._screen.cursor.y)
        except Exception:
            return (0, 0)

    # ── connexion (spawn ConPTY) ────────────────────────────────────────
    async def connect(self) -> bool:
        ok, reason = _ring_allowed(self.entity_id)
        if not ok:
            self._last_error = f"RBAC: {reason}"
            _emit("pty.rbac_denied", "error", {"entity_id": self.entity_id, "reason": reason})
            return False
        if self._connected:
            return True
        try:
            from winpty import PtyProcess

            def _spawn():
                return PtyProcess.spawn(
                    self.argv,
                    cwd=self.cwd,
                    env=self.env,
                    dimensions=(self._rows, self._cols),
                )

            self._proc = await asyncio.wait_for(asyncio.to_thread(_spawn), timeout=self._spawn_timeout)
            self._connected = True
            self._last_error = None
            self._read_task = asyncio.create_task(self._read_loop(), name="lpty-read")
            self._write_task = asyncio.create_task(self._write_loop(), name="lpty-write")
            _emit("pty.connect", "success", {"argv": str(self.argv), "entity_id": self.entity_id, "local": True})
            return True
        except asyncio.TimeoutError:
            self._last_error = f"spawn timeout {self._spawn_timeout}s"
            self._proc = None
            _emit("pty.error", "timeout", {"argv": str(self.argv), "local": True})
            return False
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._proc = None
            _emit("pty.error", "exception", {"argv": str(self.argv), "err": self._last_error[:120], "local": True})
            return False

    # ── boucles IO (read bloquant pywinpty → to_thread) ─────────────────
    async def _read_loop(self) -> None:
        try:
            while self._connected:
                try:
                    data = await asyncio.to_thread(self._proc.read, 4096)
                except asyncio.CancelledError:
                    raise
                except (EOFError, OSError):
                    self._connected = False
                    self._last_error = "EOF process"
                    _emit("pty.disconnect", "eof", {"argv": str(self.argv), "local": True})
                    self._notify()
                    return
                except Exception as exc:
                    self._connected = False
                    self._last_error = f"read: {type(exc).__name__}"
                    _emit("pty.error", "read_loop", {"err": self._last_error, "local": True})
                    self._notify()
                    return
                if not data:
                    continue
                self._stream.feed(data)
                self._bytes_received += len(data)
                self._notify()
        except asyncio.CancelledError:
            pass

    async def _write_loop(self) -> None:
        try:
            while self._connected:
                try:
                    data = await asyncio.wait_for(self._input_queue.get(), timeout=0.5)
                    if self._proc is not None:
                        await asyncio.to_thread(self._proc.write, data)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(f"local write_loop: {exc}")
                    return
        except asyncio.CancelledError:
            pass

    def _notify(self) -> None:
        cb = self.on_screen_update
        if cb is None:
            return
        try:
            cb()
        except Exception:
            logger.exception("on_screen_update raised")

    # ── input ────────────────────────────────────────────────────────────
    async def send_bytes(self, data) -> None:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        await self._input_queue.put(data)

    async def inject(self, cmd: str, newline: str = "\r") -> None:
        await self._input_queue.put(cmd + newline)

    def resize(self, cols: int, rows: int) -> None:
        cols = max(20, int(cols))
        rows = max(5, int(rows))
        if cols == self._cols and rows == self._rows:
            return
        self._cols = cols
        self._rows = rows
        try:
            self._screen.resize(rows, cols)
        except Exception:
            pass
        if self._connected and self._proc is not None:
            try:
                self._proc.setwinsize(rows, cols)
            except Exception:
                pass

    # ── teardown ─────────────────────────────────────────────────────────
    async def disconnect(self) -> None:
        was = self._connected
        self._connected = False
        # terminate AVANT cancel : débloque le read bloquant dans son thread
        if self._proc is not None:
            try:
                await asyncio.to_thread(self._proc.terminate, True)
            except Exception:
                pass
        for task in (self._read_task, self._write_task):
            if task and not task.done():
                task.cancel()
        pending = [t for t in (self._read_task, self._write_task) if t]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._proc = None
        if was:
            _emit("pty.disconnect", "clean", {"argv": str(self.argv), "bytes": self._bytes_received, "local": True})


# ── Widget Textual ────────────────────────────────────────────────────────────

if HAS_TEXTUAL:
    # Mapping clavier minimal (suffisant pour shell interactif)
    _KEY_MAP = {
        "enter": "\r",
        "tab": "\t",
        "backspace": "\x7f",
        "delete": "\x1b[3~",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "right": "\x1b[C",
        "left": "\x1b[D",
        "home": "\x1b[H",
        "end": "\x1b[F",
        "pageup": "\x1b[5~",
        "pagedown": "\x1b[6~",
        "escape": "\x1b",
    }

    class PTYTerminalWidget(Vertical):  # type: ignore[misc]
        """Widget Textual qui consomme un PTYSession et affiche un RichLog."""

        DEFAULT_CSS = """
        PTYTerminalWidget {
            height: 1fr;
            background: $surface-darken-1;
        }
        """

        # Touches réservées App-level — pas consommées par PTY
        _RESERVED = frozenset(
            {
                "ctrl+q",
                "ctrl+t",
                "ctrl+r",
                "ctrl+m",
                "ctrl+e",
                "ctrl+s",
                "ctrl+h",
                "ctrl+v",
                "ctrl+f",
                "ctrl+g",
                "ctrl+u",
                "ctrl+l",
                "ctrl+b",
                "ctrl+p",
                "f1",
                "f2",
                "f3",
            }
        )

        def __init__(
            self,
            host: str = "",
            port: int = 22,
            username: str = "admin",
            password: Optional[str] = None,
            entity_id: str = "",
            auto_connect: bool = True,
            widget_id: Optional[str] = None,
            argv: "Optional[list[str] | str]" = None,
            cwd: Optional[str] = None,
            env: Optional[dict] = None,
        ) -> None:
            """`argv` -> terminal LOCAL (ConPTY) ; sinon terminal SSH, inchange.

            Le widget savait deja tout faire d'un terminal — `on_key` envoie les
            touches a la session, pyte rend l'ecran — mais il ne pouvait consommer
            qu'une `PTYSession` SSH, qu'il construisait lui-meme. `LocalPTYSession`
            existait a cote, fonctionnelle (PoC valide, HAS_WINPTY vrai), et aucun
            widget ne la montait : le terminal LOCAL etait donc inatteignable
            depuis l'interface, faute de ce seul parametre.

            Retro-compatible : sans `argv`, le comportement SSH est identique."""
            super().__init__(id=widget_id)
            self.can_focus = True
            self._local = argv is not None
            if self._local:
                self._sess = LocalPTYSession(
                    argv=argv,
                    cwd=cwd,
                    env=env,
                    entity_id=entity_id,
                    on_screen_update=self._on_update,
                )
            else:
                self._sess = PTYSession(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    entity_id=entity_id,
                    on_screen_update=self._on_update,
                )
            self._auto_connect = auto_connect
            self._log: Optional[RichLog] = None
            self._last_display: list[str] = []

        def cible(self) -> str:
            """Ce a quoi ce terminal est attache, en clair — un ecran de terminal
            sans en-tete ne dit pas OU l'on tape."""
            if self._local:
                argv = getattr(self._sess, "argv", None) or getattr(self._sess, "_argv", "?")
                return "local: %s" % (argv if isinstance(argv, str) else " ".join(argv))
            return "ssh: %s@%s:%s" % (getattr(self._sess, "username", "?"),
                                      getattr(self._sess, "host", "?"),
                                      getattr(self._sess, "port", "?"))

        def compose(self):
            yield RichLog(id="pty-log", wrap=False, markup=False, auto_scroll=True, highlight=False)

        async def on_mount(self) -> None:
            self._log = self.query_one("#pty-log", RichLog)
            if self._auto_connect:
                self._log.write("[PTY] Ouverture %s..." % self.cible())
                ok = await self._sess.connect()
                if not ok:
                    self._log.write(f"[PTY] Connect FAIL: {self._sess.last_error}")
                else:
                    self._log.write("[PTY] Connected. Type commands.")

        def _on_update(self) -> None:
            if self._log is None:
                return
            try:
                display = self._sess.get_display()
                if display == self._last_display:
                    return
                self._log.clear()
                for line in display:
                    self._log.write(line.rstrip())
                self._last_display = list(display)
            except Exception as e:
                logger.debug(f"refresh err: {e}")

        async def on_key(self, event: "events.Key") -> None:
            if event.key in self._RESERVED:
                return
            data = _KEY_MAP.get(event.key)
            if data is None:
                if event.character is not None and len(event.character) == 1:
                    data = event.character
            if data is not None:
                await self._sess.send_bytes(data)
                event.stop()

        async def shutdown(self) -> None:
            await self._sess.disconnect()
else:

    class PTYTerminalWidget:  # type: ignore[no-redef]
        """Stub si Textual indisponible."""

        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("textual manquant — pip install textual")


# ── Selftest local (ConPTY) ───────────────────────────────────────────────────


async def _selftest_local() -> bool:
    """Spawn cmd.exe sous ConPTY, inject un echo, vérifie l'écran pyte."""
    sess = LocalPTYSession(["cmd.exe"], term_cols=80, term_rows=24)
    if not await sess.connect():
        print(f"[selftest-local] spawn FAIL: {sess.last_error}")
        return False
    await asyncio.sleep(1.5)
    await sess.inject("echo LOCALPTY_INJECT_OK")
    ok = False
    for _ in range(40):
        await asyncio.sleep(0.25)
        if "LOCALPTY_INJECT_OK" in "\n".join(sess.get_display()):
            ok = True
            break
    rx = sess.bytes_received
    await sess.disconnect()
    verdict = "PASS" if (ok and rx > 0) else "FAIL"
    print(f"[selftest-local] inject_visible={ok} bytes={rx} -> {verdict}")
    return ok and rx > 0


if __name__ == "__main__":
    import sys as _sys

    if "--selftest-local" in _sys.argv:
        raise SystemExit(0 if asyncio.run(_selftest_local()) else 1)
