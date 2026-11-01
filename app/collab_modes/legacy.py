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

    return _appel_borne(_run)


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

    return _appel_borne(_run)


# Audit C2.1 (29/10) : `with ThreadPoolExecutor` attendait la tache en sortie de bloc, le delai ne liberait pas
# l'appelant. Pool ferme sans attente ; TimeoutError au delai, comme avant, mais AU delai.
_DELAI_S = 60


def _appel_borne(fn):
    import concurrent.futures
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=_DELAI_S)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
