# -*- coding: utf-8 -*-
"""
app.collab_modes.legacy - Sync wrappers legacy.

2 fonctions sync qui wrappent les versions async de _participants.
A deprecate a terme, conservees pour backward compat avec forge_swarm_team
et forge_desktop qui les utilisent directement.

Voir docs/REFACTO_COLLAB_MODES_SPEC.md pour le refacto.
"""
from __future__ import annotations

import asyncio

from ._participants import _ollama_ask, _gemini_ask


# ── Wrappers synchrones pour appel depuis threads sans event loop ──────────────
def ollama_ask_sync(task: str, context: str = "", system: str = "", max_tokens: int = 500, session_id: str = "") -> str:
    """Wrapper sync de _ollama_ask — utilisable depuis run_in_executor."""
    import concurrent.futures

    def _run() -> object:
        """Run."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                _ollama_ask(task, context=context, system=system, max_tokens=max_tokens, session_id=session_id)
            )
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_run).result(timeout=60)


def gemini_ask_sync(task: str, context: str = "", mode: str = "STRICT", session_id: str = "") -> str:
    """Wrapper sync de _gemini_ask — utilisable depuis run_in_executor."""
    import concurrent.futures

    def _run() -> object:
        """Run."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_gemini_ask(task, context=context, mode=mode, session_id=session_id))
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_run).result(timeout=60)
