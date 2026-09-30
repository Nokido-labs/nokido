"""
forge_ring_buffer.py - Ring Buffer Rewind pattern (Phase 37, 2026-05-25).

Inspire NANO Corp n.Scope (NDR cybersecurite breveté) : tampon glissant
des N derniers events RAM, sur trigger rejoue le contexte exact amont.
Adapte aux agents LATS Nokido : avant chaque agent_fn(task, ctx) on
demarre un recording (trace_id), pendant l'execution l'agent push events
via callback, sur REJECTED on dump_window pour enrichir ctx du retry.

Difference vs forge_audit_log (Phase 29) :
  - audit_log = SQLite persistant, queryable, long terme (jours)
  - ring_buffer = collections.deque RAM volatile, window court (60s), focus
    reconstruction contexte agent. Synergie : sur REJECTED critique, on
    flush la window vers audit_log avec trace_id pour forensique.

Capacite : 1000 events/agent x 4KB max = ~4MB/agent. N=10 agents simultanes
= 40MB worst-case acceptable.

API :
    rec = start_recording(agent_id, trace_id, window_s=60)
    push(trace_id, kind, payload)     # kind in {tool_call, llm_response,
                                       #         eval_intermediate, exception}
    dump_window(trace_id, since_ts=None) -> list[Event]
    stop_recording(trace_id)          # libere le deque
    stats() -> dict                   # observabilite hub
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Any, Literal

logger = logging.getLogger("forge_ring_buffer")

EventKind = Literal["tool_call", "llm_response", "eval_intermediate", "exception"]
MAX_EVENTS_PER_TRACE = 1000
MAX_PAYLOAD_BYTES = 4096
DEFAULT_WINDOW_S = 60.0


@dataclass(slots=True)
class Event:
    ts: float
    kind: str
    payload: dict
    seq: int


class _Recording:
    __slots__ = ("agent_id", "trace_id", "t0", "window_s", "events", "lock", "_seq")

    def __init__(self, agent_id: str, trace_id: str, window_s: float):
        self.agent_id = agent_id
        self.trace_id = trace_id
        self.t0 = time.monotonic()
        self.window_s = window_s
        self.events: deque = deque(maxlen=MAX_EVENTS_PER_TRACE)
        self.lock = threading.Lock()
        self._seq = 0


_RECORDINGS: dict[str, _Recording] = {}
_REG_LOCK = threading.Lock()


def _truncate_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        payload = {"_raw": str(payload)[:MAX_PAYLOAD_BYTES]}
    out: dict = {}
    budget = MAX_PAYLOAD_BYTES
    for k, v in payload.items():
        s = str(v)
        if len(s) > budget:
            s = s[:budget] + "...[TRUNC]"
        out[k] = s
        budget -= len(s)
        if budget <= 0:
            out["_truncated"] = True
            break
    return out


def start_recording(agent_id: str, trace_id: str, window_s: float = DEFAULT_WINDOW_S) -> _Recording:
    with _REG_LOCK:
        rec = _Recording(agent_id, trace_id, window_s)
        _RECORDINGS[trace_id] = rec
        return rec


def push(trace_id: str, kind: str, payload: dict) -> bool:
    """Append event au ring buffer. False si trace_id inconnu (silent no-op)."""
    rec = _RECORDINGS.get(trace_id)
    if rec is None:
        return False
    with rec.lock:
        rec._seq += 1
        rec.events.append(
            Event(
                ts=time.monotonic(),
                kind=kind,
                payload=_truncate_payload(payload),
                seq=rec._seq,
            )
        )
    return True


def dump_window(trace_id: str, since_ts: float | None = None) -> list[dict]:
    rec = _RECORDINGS.get(trace_id)
    if rec is None:
        return []
    cutoff = since_ts if since_ts is not None else 0.0
    with rec.lock:
        return [asdict(e) for e in rec.events if e.ts >= cutoff]


def stop_recording(trace_id: str) -> int:
    with _REG_LOCK:
        rec = _RECORDINGS.pop(trace_id, None)
    return len(rec.events) if rec else 0


def stats() -> dict:
    with _REG_LOCK:
        active = len(_RECORDINGS)
        total_events = sum(len(r.events) for r in _RECORDINGS.values())
    return {
        "active_recordings": active,
        "total_events": total_events,
        "max_per_trace": MAX_EVENTS_PER_TRACE,
        "max_payload_bytes": MAX_PAYLOAD_BYTES,
        "approx_ram_mb": round(total_events * MAX_PAYLOAD_BYTES / 1_048_576, 2),
    }
