"""Phase 37 ring buffer rewind tests."""
import threading
import time
import pytest
from forge_ring_buffer import (
    start_recording, push, dump_window, stop_recording, stats,
    MAX_EVENTS_PER_TRACE,
)


def test_push_dump_basic():
    tid = "test-basic"
    start_recording("agt", tid, window_s=10.0)
    assert push(tid, "tool_call", {"name": "ls"})
    assert push(tid, "llm_response", {"tokens": 42})
    events = dump_window(tid)
    assert len(events) == 2
    assert events[0]["kind"] == "tool_call"
    assert events[1]["seq"] == 2
    stop_recording(tid)


def test_dump_window_since_ts():
    tid = "test-window"
    start_recording("agt", tid)
    push(tid, "tool_call", {"i": 1})
    time.sleep(0.02)  # garantit boundary > ts(i=1)
    boundary = time.monotonic()
    time.sleep(0.02)  # garantit ts(i=2) > boundary
    push(tid, "tool_call", {"i": 2})
    events = dump_window(tid, since_ts=boundary)
    assert len(events) == 1
    assert events[0]["payload"]["i"] == "2"
    stop_recording(tid)


def test_capacity_overflow_drop_oldest():
    tid = "test-cap"
    start_recording("agt", tid)
    for i in range(MAX_EVENTS_PER_TRACE + 50):
        push(tid, "tool_call", {"i": i})
    events = dump_window(tid)
    assert len(events) == MAX_EVENTS_PER_TRACE
    assert int(events[0]["payload"]["i"]) == 50
    stop_recording(tid)


def test_thread_safety_concurrent_push():
    tid = "test-mt"
    start_recording("agt", tid)
    def worker(n):
        for i in range(n):
            push(tid, "tool_call", {"t": threading.get_ident(), "i": i})
    threads = [threading.Thread(target=worker, args=(100,)) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    events = dump_window(tid)
    assert len(events) == 1000
    seqs = sorted(e["seq"] for e in events)
    assert seqs == list(range(1, 1001))
    stop_recording(tid)


def test_push_unknown_trace_returns_false():
    assert push("never-started", "tool_call", {}) is False


def test_stats_reflects_active():
    initial = stats()["active_recordings"]
    start_recording("agt", "stats-test")
    push("stats-test", "tool_call", {})
    s = stats()
    assert s["active_recordings"] == initial + 1
    stop_recording("stats-test")
