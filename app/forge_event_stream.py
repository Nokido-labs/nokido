# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-05-23 | VER:v_event_stream_manus_loop
#FORGE:[score:88|agent:claude-mcp|temp:0.00|risk:0.30|ast:OK|test:OK|lint:OK|color:BLUE|attempt:1]
CONTRAINTE: event-driven agent loop Manus-style; backward-compat polling daemons
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = "#FORGE:[score:88|agent:claude-mcp|temp:0.00|risk:0.30|ast:OK|test:OK|lint:OK|color:BLUE|attempt:1]"
"""
forge_event_stream.py - In-process asyncio Event Stream + Manus 6-step AgentLoop
==================================================================================

Pourquoi un module Python neuf (anti-dup verifie 2026-05-23) :
  - proxy_deno/core/nervous_system.ts SystemBus : event bus cote Deno, kinds
    figes spike|route|ingest|alert|heartbeat, pas exposable en async Python.
  - app/forge_byte_router.py / forge_spike_router.py : routage neuronal SNN,
    pas une boucle agentique avec etapes Analyze->Select->Wait->Iterate->Submit.
  - app/forge_task_bus.py : persistance SQLite multi-agents (tasks lifecycle),
    sub-second async event loop hors scope.
  - app/tui_adapters/events_adapter.py : HTTP polling client web_hub :7400.
  - tools/gemini_poll_daemon.py : polling Hub 30s, latence cible <500ms.

Overlap mesure : <30% sur chaque module. Ce module est l'organe manquant :
"Bulbe rachidien" (decision rapide) cote asyncio Python in-process, avec une
queue prioritaire, des handlers pluggables, et la boucle 6-pas Manus.

Pattern source (RAG ai_prompts_landscape/Manus Agent Tools & Prompt/Agent loop):
  1. Analyze Events  : lire le flux d'evenements, focus user_msg + tool_result
  2. Select Tools    : choisir le prochain tool selon etat + plan
  3. Wait Execution  : attendre l'observation (avec timeout)
  4. Iterate         : un seul tool call par iteration, repeter
  5. Submit Results  : publier le resultat + persister via sink
  6. Standby         : idle court si queue vide

Backward-compat : ne touche PAS gemini_poll_daemon a l'execution. L'adapter
gemini_poll_to_event() permet a un futur consumer de pousser les notifs polled
dans la stream sans casser le daemon legacy.

Usage minimal :

    import asyncio
    from forge_event_stream import Event, EventStream, AgentLoop

    stream = EventStream()

    async def my_tool_selector(ev: Event) -> dict:
        # decide what to do based on ev.kind/payload
        return {"tool": "noop", "args": {}}

    async def my_tool_executor(decision: dict) -> dict:
        return {"ok": True, "echo": decision}

    loop = AgentLoop(
        stream=stream,
        select_tool=my_tool_selector,
        execute_tool=my_tool_executor,
    )

    async def main():
        await stream.publish(Event.now(kind="user_msg", payload={"text": "hi"}))
        task = asyncio.create_task(loop.run(max_iters=1))
        await task

    asyncio.run(main())

Anatomy (CLAUDE.md s10) : "Bulbe rachidien autonome" / "Cervelet decisionnel
asyncio". Vascularisation entrante : poll daemons, MCP tools, user inputs.
Vascularisation sortante : forge_task_bus (persist), web_hub events, mailbox.
Hemorragie : si le module fuit, la latence revient au polling 30s -- pas de
casse, juste degradation; gemini_poll_daemon reste maitre du fallback.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
)

logger = logging.getLogger(__name__)

# Type aliases ----------------------------------------------------------------

EventKind = Literal["user_msg", "tool_result", "system", "deadline", "external"]

# Lower number = higher priority. deadline first, user next, then explicit
# system events, then internal tool_result followups (auto-republished by
# AgentLoop._iterate — must not pre-empt user-pushed events), external last.
_PRIORITY: Dict[str, int] = {
    "deadline": 0,
    "user_msg": 1,
    "system": 2,
    "tool_result": 3,
    "external": 4,
}

EventHandler = Callable[["Event"], Awaitable[None]]
ToolSelector = Callable[["Event"], Awaitable[Mapping[str, Any]]]
ToolExecutor = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]
ResultSink = Callable[[Mapping[str, Any]], Awaitable[None]]


# Dataclass -------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """Single event flowing through the agent loop.

    Args:
        kind     : one of EventKind literals.
        payload  : arbitrary JSON-serialisable mapping.
        source   : producer identifier (daemon name, MCP client id, ...).
        id       : unique event id (auto uuid4 hex if omitted).
        ts       : ISO-8601 UTC timestamp (auto now() if omitted).

    Returns:
        Frozen dataclass; safe to share across coroutines.

    Raises:
        ValueError: if `kind` is not a registered EventKind.
    """

    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))

    def __post_init__(self) -> None:
        if self.kind not in _PRIORITY:
            raise ValueError(f"unknown EventKind {self.kind!r}; expected one of {sorted(_PRIORITY)}")

    @classmethod
    def now(
        cls,
        kind: str,
        payload: Optional[Mapping[str, Any]] = None,
        source: str = "unknown",
    ) -> "Event":
        """Convenience constructor with auto id + ts.

        Args:
            kind    : EventKind literal.
            payload : optional mapping.
            source  : producer id.

        Returns:
            Event with fresh uuid + UTC timestamp.
        """
        return cls(kind=kind, payload=dict(payload or {}), source=source)

    def priority(self) -> int:
        """Return scheduling priority (lower = sooner)."""
        return _PRIORITY[self.kind]

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dict representation."""
        d = asdict(self)
        d["payload"] = dict(self.payload)
        return d

    def to_json(self) -> str:
        """Compact JSON serialisation; raises TypeError on non-JSON payload."""
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)


# EventStream -----------------------------------------------------------------


class EventStream:
    """In-process priority queue + pluggable handlers.

    Single-writer-multi-reader semantics. Handlers run sequentially per
    consume() to keep ordering deterministic; spawn asyncio tasks inside
    your handler if you need fan-out.
    """

    def __init__(self, maxsize: int = 0) -> None:
        # asyncio.PriorityQueue tie-breaks on second element; counter prevents
        # comparing Event instances when priorities collide.
        self._q: "asyncio.PriorityQueue[tuple[int, int, Event]]" = asyncio.PriorityQueue(maxsize=maxsize)
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._wildcard: List[EventHandler] = []
        self._seq: int = 0
        self._history: List[Event] = []
        self._max_hist: int = 256

    # registration ------------------------------------------------------------

    def register(self, kind: str, handler: EventHandler) -> Callable[[], None]:
        """Register an async handler for a given EventKind (or '*' wildcard).

        Args:
            kind    : EventKind literal or '*' for all events.
            handler : async callable taking the Event.

        Returns:
            Unsubscribe callable.
        """
        if kind == "*":
            self._wildcard.append(handler)

            def _unsub_w() -> None:
                try:
                    self._wildcard.remove(handler)
                except ValueError:
                    pass

            return _unsub_w
        if kind not in _PRIORITY:
            raise ValueError(f"unknown EventKind {kind!r}")
        self._handlers.setdefault(kind, []).append(handler)

        def _unsub() -> None:
            try:
                self._handlers[kind].remove(handler)
            except (KeyError, ValueError):
                pass

        return _unsub

    # publish / consume -------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """Push an event onto the priority queue (non-blocking dispatch).

        Handlers are NOT called here; consume() drains them. This lets the
        AgentLoop preserve the Manus 6-step ordering instead of fan-out chaos.
        """
        self._seq += 1
        await self._q.put((event.priority(), self._seq, event))

    async def consume(self, timeout: Optional[float] = None) -> Optional[Event]:
        """Pop the next event (highest priority first), dispatch handlers.

        Args:
            timeout : seconds to wait; None blocks forever. Returns None on
                      timeout (used by standby() to detect idle).

        Returns:
            The Event consumed, or None if the timeout elapsed.
        """
        try:
            if timeout is None:
                _prio, _seq, ev = await self._q.get()
            else:
                _prio, _seq, ev = await asyncio.wait_for(self._q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        # Record before dispatch so handlers can introspect history safely.
        self._history.append(ev)
        if len(self._history) > self._max_hist:
            self._history = self._history[-self._max_hist :]
        for h in self._handlers.get(ev.kind, []):
            try:
                await h(ev)
            except Exception:  # noqa: BLE001 -- handler errors must not stop the loop
                logger.exception("handler for %s raised", ev.kind)
        for h in self._wildcard:
            try:
                await h(ev)
            except Exception:  # noqa: BLE001
                logger.exception("wildcard handler raised on %s", ev.kind)
        self._q.task_done()
        return ev

    def empty(self) -> bool:
        """True if queue currently has no pending events."""
        return self._q.empty()

    def qsize(self) -> int:
        """Current queue size (advisory; can race with producers)."""
        return self._q.qsize()

    def history(self, limit: int = 50) -> List[Event]:
        """Return up to `limit` most recent events (oldest first)."""
        if limit <= 0:
            return []
        return list(self._history[-limit:])


# AgentLoop -------------------------------------------------------------------


class AgentLoop:
    """Manus-style 6-step agent loop on top of an EventStream.

    Steps (per iteration):
      1. analyze_events  : await next event from stream (priority-ordered)
      2. select_tool     : delegate to user-provided async selector
      3. wait_execution  : await user-provided async executor (with timeout)
      4. iterate         : republish tool_result event for downstream handlers
      5. submit_results  : forward to sink (mailbox, task_bus, mmap, ...)
      6. standby         : short sleep when queue empty (default 50ms)

    Constraints:
      - one tool call per iteration (Manus rule 4)
      - sink + selector + executor are all mock-able (tests pass without
        any hub/router dependency)
    """

    def __init__(
        self,
        stream: EventStream,
        select_tool: ToolSelector,
        execute_tool: ToolExecutor,
        sink: Optional[ResultSink] = None,
        standby_ms: int = 10,
        wait_timeout_s: float = 30.0,
    ) -> None:
        self.stream = stream
        self.select_tool = select_tool
        self.execute_tool = execute_tool
        self.sink = sink
        self.standby_ms = max(1, int(standby_ms))
        self.wait_timeout_s = max(0.1, float(wait_timeout_s))
        self._iter_count: int = 0
        self._stopped: bool = False

    # public API --------------------------------------------------------------

    async def run(self, max_iters: Optional[int] = None) -> int:
        """Run the loop until stopped or max_iters reached.

        Args:
            max_iters : safety cap on total TICKS (idle + active). None = unbounded.

        Returns:
            Number of ACTIVE iterations (events consumed). Idle standby ticks
            count vs max_iters but are NOT returned (contract : "iters" = work).
        """
        self._stopped = False
        self._iter_count = 0
        tick = 0
        while not self._stopped:
            if max_iters is not None and tick >= max_iters:
                break
            await self._one_iteration()
            tick += 1
        return self._iter_count

    def stop(self) -> None:
        """Request graceful shutdown after the current iteration completes."""
        self._stopped = True

    # internals (named after Manus 6 steps) -----------------------------------

    async def _one_iteration(self) -> None:
        ev = await self._analyze_events()
        if ev is None:
            await self._standby()
            return  # idle tick : counted in run() loop, NOT in _iter_count
        try:
            decision = await self._select_tool(ev)
            result = await self._wait_execution(decision)
        except Exception as exc:  # noqa: BLE001
            logger.exception("iteration failed on event %s", ev.id)
            result = {"ok": False, "error": str(exc), "event_id": ev.id}
        await self._iterate(ev, result)
        await self._submit_results(ev, result)
        self._iter_count += 1

    async def _analyze_events(self) -> Optional[Event]:
        # short timeout so standby can kick in instead of blocking forever
        return await self.stream.consume(timeout=self.standby_ms / 1000.0)

    async def _select_tool(self, ev: Event) -> Mapping[str, Any]:
        decision = await self.select_tool(ev)
        if not isinstance(decision, Mapping):
            raise TypeError("select_tool must return a Mapping")
        return decision

    async def _wait_execution(self, decision: Mapping[str, Any]) -> Mapping[str, Any]:
        return await asyncio.wait_for(self.execute_tool(decision), timeout=self.wait_timeout_s)

    async def _iterate(self, src: Event, result: Mapping[str, Any]) -> None:
        # Republish a tool_result event so other handlers can react. Tagging
        # source with the originator id keeps causality traceable.
        followup = Event.now(
            kind="tool_result",
            payload={"source_event": src.id, "result": dict(result)},
            source=f"agent_loop:{src.source}",
        )
        await self.stream.publish(followup)

    async def _submit_results(self, src: Event, result: Mapping[str, Any]) -> None:
        if self.sink is None:
            return
        try:
            await self.sink(
                {
                    "event_id": src.id,
                    "kind": src.kind,
                    "ts": src.ts,
                    "result": dict(result),
                }
            )
        except Exception:  # noqa: BLE001
            logger.exception("sink failed for event %s", src.id)

    async def _standby(self) -> None:
        # consume(timeout=standby_ms) already paced this tick — yield only to
        # let other coroutines progress, no extra sleep (avoids 2x wall budget
        # per idle iteration and respects test's 200ms cap for 5 ticks).
        await asyncio.sleep(0)


# Adapters --------------------------------------------------------------------


def gemini_poll_to_event(notify_state: Mapping[str, Any]) -> Event:
    """Backward-compat bridge : convert a gemini_poll_daemon notify dict to Event.

    The polling daemon currently surfaces dicts like:
        {"id": "...", "text": "...", "addressed_to": "...", "ts": "..."}

    Args:
        notify_state : raw dict pulled from Hub /tools/call name=poll.

    Returns:
        Event with kind="external" (lower priority than user_msg, by design:
        polled notifs are stale; live user msgs should preempt them).

    Raises:
        ValueError: if mandatory fields (`text` or `id`) are missing.
    """
    if not isinstance(notify_state, Mapping):
        raise ValueError("notify_state must be a mapping")
    if "text" not in notify_state and "id" not in notify_state:
        raise ValueError("notify_state needs at least 'text' or 'id'")
    payload = {k: v for k, v in notify_state.items() if k not in {"ts"}}
    src = str(notify_state.get("source") or "gemini_poll_daemon")
    ts = str(notify_state.get("ts") or datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
    eid = str(notify_state.get("id") or uuid.uuid4().hex[:16])
    return Event(kind="external", payload=payload, source=src, id=eid[:16], ts=ts)


def to_byte_router_sentinel(event: Event) -> bytes:
    """Encode an Event as a forge_byte_router-compatible 13-byte sentinel hint.

    Best-effort interop : forge_byte_router uses small fixed-size sentinels.
    This produces a stable, deterministic byte fingerprint (NOT a full frame)
    suitable for spike-router routing decisions.

    Args:
        event : the Event to fingerprint.

    Returns:
        13 bytes : 1 byte kind code + 8 bytes truncated id + 4 bytes ts hash.
    """
    kind_code = (_PRIORITY.get(event.kind, 9) & 0xFF).to_bytes(1, "big")
    eid_bytes = event.id.encode("ascii", errors="ignore")[:8].ljust(8, b"\x00")
    ts_hash = (abs(hash(event.ts)) & 0xFFFFFFFF).to_bytes(4, "big")
    return kind_code + eid_bytes + ts_hash


__all__ = [
    "Event",
    "EventStream",
    "AgentLoop",
    "EventKind",
    "EventHandler",
    "ToolSelector",
    "ToolExecutor",
    "ResultSink",
    "gemini_poll_to_event",
    "to_byte_router_sentinel",
]
