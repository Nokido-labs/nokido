"""Tests for forge_event_stream — Manus-style 6-step agent loop.

Run :
    PYTHONNOUSERSITE=1 __import__("os").path.expanduser("~/miniforge3/python.exe") \
        -m pytest tests/test_forge_event_stream.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

# Make `app/` importable without installing the package.
_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_event_stream  # noqa: E402
from forge_event_stream import (  # noqa: E402
    AgentLoop,
    Event,
    EventStream,
    gemini_poll_to_event,
    to_byte_router_sentinel,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Event dataclass instanciable + sérialisable JSON
# ─────────────────────────────────────────────────────────────────────────────


def test_event_dataclass_instantiation_and_json_roundtrip():
    ev = Event.now(kind="user_msg", payload={"text": "salut"}, source="cli")
    assert ev.kind == "user_msg"
    assert ev.payload == {"text": "salut"}
    assert ev.source == "cli"
    assert isinstance(ev.id, str) and len(ev.id) == 16
    assert ev.ts.endswith("+00:00") or "T" in ev.ts  # ISO UTC

    # JSON roundtrip
    raw = ev.to_json()
    parsed = json.loads(raw)
    assert parsed["kind"] == "user_msg"
    assert parsed["payload"]["text"] == "salut"
    assert parsed["id"] == ev.id

    # Invalid kind raises
    with pytest.raises(ValueError):
        Event(kind="bogus_kind", payload={})


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — EventStream.register + publish + consume dans le bon ordre (priorité)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_stream_priority_and_handler_registration():
    stream = EventStream()
    seen: list[str] = []

    async def h_user(ev: Event) -> None:
        seen.append(f"user:{ev.payload.get('n')}")

    async def h_deadline(ev: Event) -> None:
        seen.append(f"deadline:{ev.payload.get('n')}")

    stream.register("user_msg", h_user)
    stream.register("deadline", h_deadline)

    # Publish out of priority order : system, user_msg, deadline.
    # consume() must return deadline first, then user_msg, then system.
    await stream.publish(Event.now(kind="system", payload={"n": 1}))
    await stream.publish(Event.now(kind="user_msg", payload={"n": 2}))
    await stream.publish(Event.now(kind="deadline", payload={"n": 3}))

    consumed_kinds: list[str] = []
    for _ in range(3):
        ev = await stream.consume(timeout=1.0)
        assert ev is not None
        consumed_kinds.append(ev.kind)

    assert consumed_kinds == ["deadline", "user_msg", "system"], consumed_kinds
    # Handlers fired for the right kinds (no handler registered for system).
    assert seen == ["deadline:3", "user:2"], seen


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — AgentLoop.run() processes priority-first; one tool call per iter
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_processes_events_in_priority_order():
    stream = EventStream()
    processed: list[str] = []

    async def selector(ev: Event):
        return {"tool": "echo", "kind": ev.kind, "n": ev.payload.get("n")}

    async def executor(decision):
        processed.append(f"{decision['kind']}:{decision['n']}")
        return {"ok": True, "echoed": decision}

    sink_calls: list[dict] = []

    async def sink(item):
        sink_calls.append(dict(item))

    loop = AgentLoop(
        stream=stream,
        select_tool=selector,
        execute_tool=executor,
        sink=sink,
        standby_ms=10,
    )

    # 3 inputs, scrambled priorities
    await stream.publish(Event.now(kind="system", payload={"n": "S"}))
    await stream.publish(Event.now(kind="deadline", payload={"n": "D"}))
    await stream.publish(Event.now(kind="user_msg", payload={"n": "U"}))

    # Run exactly 3 iterations (each consumes one event AND republishes a
    # tool_result event — but max_iters caps us at 3 so the followups stay
    # queued harmlessly).
    iters = await loop.run(max_iters=3)
    assert iters == 3

    # Order must be deadline -> user_msg -> system (priority asc).
    assert processed == ["deadline:D", "user_msg:U", "system:S"], processed
    # Sink received exactly 3 results.
    assert len(sink_calls) == 3
    assert all(c["result"]["ok"] for c in sink_calls)


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — standby() does NOT block indefinitely when queue empty
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_standby_does_not_hang_on_empty_queue():
    stream = EventStream()

    async def selector(ev: Event):  # never called
        return {"tool": "noop"}

    async def executor(decision):  # never called
        return {"ok": True}

    loop = AgentLoop(
        stream=stream,
        select_tool=selector,
        execute_tool=executor,
        standby_ms=20,
    )

    # No events published; run for 5 iterations (each = one standby tick of
    # ~20ms). Cap total wall time to 200ms — well below the 30s wait_timeout.
    start = time.monotonic()
    iters = await asyncio.wait_for(loop.run(max_iters=5), timeout=0.2)
    elapsed = time.monotonic() - start

    assert iters == 0, "no events consumed when queue empty (standby path)"
    assert elapsed < 0.2, f"standby took too long: {elapsed:.3f}s"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — gemini_poll_to_event adapter + byte_router sentinel encoding
# ─────────────────────────────────────────────────────────────────────────────


def test_gemini_poll_adapter_and_byte_router_sentinel():
    notify = {
        "id": "abc123def456ghi7",
        "text": "Claude pls help",
        "addressed_to": "gemini",
        "ts": "2026-05-23T12:00:00.000+00:00",
        "source": "gemini_poll_daemon",
    }
    ev = gemini_poll_to_event(notify)
    assert ev.kind == "external", "polled notifs should never preempt live user_msg"
    assert ev.source == "gemini_poll_daemon"
    assert ev.id == "abc123def456ghi7"
    assert ev.payload["text"] == "Claude pls help"
    assert ev.ts == "2026-05-23T12:00:00.000+00:00"

    # Sentinel encoding : 1 byte kind + 8 bytes id prefix + 4 bytes ts hash.
    sent = to_byte_router_sentinel(ev)
    assert isinstance(sent, bytes)
    assert len(sent) == 13
    # First byte = priority code for "external" = 4
    assert sent[0] == 4

    # Defensive : missing both id and text raises
    with pytest.raises(ValueError):
        gemini_poll_to_event({"addressed_to": "gemini"})
    with pytest.raises(ValueError):
        gemini_poll_to_event("not a mapping")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Bonus — wildcard handler ('*') fires on every event kind
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wildcard_handler_fires_on_every_kind():
    stream = EventStream()
    seen: list[str] = []

    async def wildcard(ev: Event) -> None:
        seen.append(ev.kind)

    unsub = stream.register("*", wildcard)

    await stream.publish(Event.now(kind="user_msg"))
    await stream.publish(Event.now(kind="system"))
    await stream.consume(timeout=1.0)
    await stream.consume(timeout=1.0)

    assert set(seen) == {"user_msg", "system"}
    # Unsubscribe stops the firing
    unsub()
    await stream.publish(Event.now(kind="deadline"))
    await stream.consume(timeout=1.0)
    assert "deadline" not in seen
