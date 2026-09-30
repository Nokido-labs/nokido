"""Adapter PTY — gère 1 PTYSession active pour la vue MASTER de la TUI v3.

Le widget Textual `PTYTerminalWidget` existe (`forge_pty_widget`) mais
l'intégration dans `nokido_tui` v3 utilise le pane MASTER RichLog existant
pour éviter un swap dynamique de widgets. L'adapter expose 4 fonctions :

    open(host, port, user, password, entity_id) -> bool   # ferme l'ancien
    inject(cmd) -> bool                                    # envoie commande
    snapshot() -> list[str]                                # lignes display
    close() -> None                                        # ferme
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

_session = None  # global active PTYSession


def _import_widget():
    """Lazy import — Textual / asyncssh / pyte peuvent manquer dans tests."""
    try:
        from nokido_agent.app import forge_pty_widget as fpw

        return fpw
    except Exception as e:
        logger.debug(f"forge_pty_widget unavailable: {e}")
        return None


def is_open() -> bool:
    return _session is not None and getattr(_session, "is_connected", False)


def session_info() -> dict:
    if _session is None:
        return {"open": False}
    return {
        "open": is_open(),
        "host": getattr(_session, "host", "?"),
        "port": getattr(_session, "port", 0),
        "user": getattr(_session, "username", "?"),
        "bytes": getattr(_session, "bytes_received", 0),
        "error": getattr(_session, "last_error", None),
    }


async def open_async(
    host: str, port: int, user: str, password: Optional[str] = None, entity_id: str = ""
) -> tuple[bool, str]:
    """Ouvre une session PTY. Ferme l'ancienne si présente.
    Retourne (ok, reason)."""
    global _session
    fpw = _import_widget()
    if fpw is None:
        return False, "forge_pty_widget indisponible (pyte/asyncssh/textual manquants?)"

    # Ferme ancienne
    await close_async()

    try:
        sess = fpw.PTYSession(host=host, port=int(port), username=user, password=password, entity_id=entity_id)
        ok = await sess.connect()
        if not ok:
            return False, sess.last_error or "connect failed"
        _session = sess
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


async def inject_async(cmd: str) -> bool:
    if _session is None or not _session.is_connected:
        return False
    try:
        await _session.inject(cmd)
        return True
    except Exception:
        return False


def snapshot() -> list[str]:
    """Lignes du display courant + (si dispo) ligne de status."""
    if _session is None:
        return ["[no PTY session]"]
    try:
        lines = _session.get_display()
    except Exception as e:
        return [f"[snapshot err: {e}]"]
    if not _session.is_connected:
        lines = list(lines) + [f"[disconnected: {_session.last_error or ''}]"]
    return lines


async def close_async() -> None:
    global _session
    if _session is None:
        return
    try:
        await _session.disconnect()
    except Exception:
        pass
    _session = None


# ── Sync wrappers — utiles depuis Textual app coroutines ──────────────────


def run_in_loop(coro):
    """Helper : run coroutine dans loop courant ou nouveau."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.ensure_future(coro)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
