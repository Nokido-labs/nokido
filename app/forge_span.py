#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_span.py — context manager `span()` : call-flow IMBRIQUÉ, souverain.

Émet des spans HIÉRARCHIQUES dans `audit.db` (via `forge_audit_log.persist`) :
chaque `with span()` crée un `span_id` propre, référence le span englobant via
`parent_id`, mesure `duration_ms`. `forge_trace_viz` reconstruit l'arbre
(`trace_id` -> `span_id`/`parent_id`) => vrai sequence / call-flow. ZÉRO backend
(≠ AppMap/Jaeger). Pile via `contextvar` (async-safe : chaque tâche a sa pile).

C'est LE gap de l'observabilité : sans spans imbriqués, les traces étaient
mono-span (forge_trace_viz montrait du plat). Wirer ce `span()` sur les call-paths
chauds (hub dispatch -> router -> silo -> tool -> provider) rend trace_viz ET
Phoenix vivants d'un coup.

Usage :
    from forge_span import span, traced

    with span("tool:rag", agent="hub", target="rag.search"):
        ...
        with span("provider:groq", agent="agent_proxy"):   # enfant imbriqué
            ...

    @traced("router.route_task")          # décorateur sync OU async
    async def route_task(...): ...

Fail-open TOTAL : si audit/contexte indispo, no-op transparent (jamais casse
l'appelant — l'observabilité ne doit jamais faire tomber le runtime).
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import time
from typing import Any, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

_current_span: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "nokido_current_span", default=None
)


def current_span_id() -> Optional[str]:
    """span_id du span courant (parent des enfants à venir), ou None."""
    return _current_span.get()


@contextlib.contextmanager
def span(
    name: str,
    *,
    agent: Optional[str] = None,
    target: Optional[str] = None,
    ring: Optional[int] = None,
    payload: Any = None,
):
    """Span imbriqué -> audit.db. parent = span courant (contextvar)."""
    try:
        from nokido_agent.app.forge_audit_log import gen_span_id, persist
    except Exception:
        yield None  # audit indispo : no-op transparent
        return
    try:
        from nokido_agent.app.forge_trace_context import get_trace_id

        trace_id = get_trace_id() or "system"
    except Exception:
        trace_id = "system"

    parent = _current_span.get()
    sid = gen_span_id()
    tok = _current_span.set(sid)
    t0 = time.time()
    status = 0
    try:
        yield sid
    except Exception:
        status = 1
        raise
    finally:
        dur = int((time.time() - t0) * 1000)
        try:
            persist(
                name,
                trace_id=trace_id,
                span_id=sid,
                parent_id=parent,
                agent=agent,
                target=target,
                status=status,
                duration_ms=dur,
                ring=ring,
                payload=payload,
            )
        except Exception:
            pass
        # Dual-emit OTLP -> Phoenix/Jaeger (fail-open, batché). audit.db reste la
        # source SOUVERAINE du tree (forge_trace_viz) ; OTel = dashboard live optionnel.
        try:
            import os as _os, sys as _sys

            _t = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"
            )
            if _t not in _sys.path:
                _sys.path.insert(0, _t)
            from nokido_agent.tools.forge_otel_export import export_span as _otel

            _otel(name, trace_id, duration_ms=dur, agent=agent or "",
                  target=target or "", status_ok=(status == 0))
        except Exception:
            pass
        try:
            _current_span.reset(tok)
        except Exception:
            pass


def _is_coro(fn) -> bool:
    import asyncio

    return asyncio.iscoroutinefunction(fn)


def traced(name: Optional[str] = None, **span_kw):
    """Décorateur : enrobe une fonction (sync OU async) dans un `span()`."""

    def deco(fn):
        span_name = name or getattr(fn, "__qualname__", getattr(fn, "__name__", "fn"))
        if _is_coro(fn):

            @functools.wraps(fn)
            async def awrap(*a, **k):
                with span(span_name, **span_kw):
                    return await fn(*a, **k)

            return awrap

        @functools.wraps(fn)
        def wrap(*a, **k):
            with span(span_name, **span_kw):
                return fn(*a, **k)

        return wrap

    return deco


if __name__ == "__main__":
    # Selftest end-to-end : trace_id dédié -> arbre 3 niveaux -> relit isolé.
    from nokido_agent.app import forge_audit_log as _al

    tid = _al.gen_trace_id()
    try:
        from nokido_agent.app.forge_trace_context import set_trace_id

        set_trace_id(tid)
    except Exception:
        pass
    with span("hub.dispatch", agent="hub", target="ask"):
        with span("router.cascade", agent="llm_router"):
            with span("provider:groq", agent="agent_proxy", target="llama-70b"):
                time.sleep(0.004)
            with span("provider:ollama", agent="agent_proxy", target="qwen"):
                time.sleep(0.003)
    print("TRACE_ID", tid)
    for r in _al.query_recent(limit=10, trace_id=tid):
        print(" ", r.get("action"), "span=", r.get("span_id"), "parent=", r.get("parent_id"),
              "dur=", r.get("duration_ms"))
