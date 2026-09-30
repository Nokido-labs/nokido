"""Phase 29 audit log tests."""
import pytest
import time
import forge_audit_log as al


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "DB_PATH", tmp_path / "audit_test.db")
    monkeypatch.setattr(al, "_INIT_DONE", False)
    yield


def test_persist_then_query_returns_event():
    al.persist("test_action", trace_id="t1234", agent="agt_test",
               target="/api/test", status=200, duration_ms=42,
               payload={"k": "v"})
    rows = al.query_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "test_action"
    assert rows[0]["trace_id"] == "t1234"
    assert rows[0]["status"] == 200


def test_query_filter_trace_id():
    al.persist("a", trace_id="aaa", agent="x", target="/")
    al.persist("b", trace_id="bbb", agent="y", target="/")
    rows = al.query_recent(trace_id="aaa")
    assert len(rows) == 1
    assert rows[0]["trace_id"] == "aaa"


def test_query_filter_agent():
    al.persist("a", trace_id="t1", agent="claude", target="/")
    al.persist("b", trace_id="t2", agent="gemini", target="/")
    rows = al.query_recent(agent="claude")
    assert len(rows) == 1


def test_payload_hash_not_full_by_default():
    al.persist("a", trace_id="t1", agent="x", target="/",
               payload={"sensitive": "secret_data"})
    rows = al.query_recent()
    assert rows[0]["payload_hash"] is not None
    assert "payload_full" not in rows[0]


def test_payload_full_only_when_verbose():
    al.persist("a", trace_id="t1", agent="x", target="/",
               payload={"data": "xyz"}, verbose=True)
    rows = al.query_recent(verbose=True)
    assert rows[0]["payload_full"] is not None
    assert "xyz" in rows[0]["payload_full"]


def test_parse_traceparent_valid_w3c():
    tid, pid = al.parse_traceparent("00-0123456789abcdef0123456789abcdef-0123456789abcdef-01")
    assert tid == "0123456789abcdef0123456789abcdef"
    assert pid == "0123456789abcdef"


def test_parse_traceparent_invalid_generates_new():
    tid, pid = al.parse_traceparent("garbage")
    assert len(tid) == 32
    assert len(pid) == 16


def test_parse_traceparent_none_generates():
    tid, pid = al.parse_traceparent(None)
    assert len(tid) == 32


def test_build_traceparent_format():
    tp = al.build_traceparent("a" * 32, "b" * 16)
    assert tp == "00-" + "a" * 32 + "-" + "b" * 16 + "-01"


def test_purge_older_than():
    al.persist("old", trace_id="t1", agent="x", target="/")
    with al._conn() as c:
        c.execute("UPDATE audit_log SET ts=? WHERE trace_id=?",
                  (time.time() - 40 * 86400, "t1"))
    n = al.purge_older_than(days=30)
    assert n == 1


@pytest.mark.asyncio
async def test_persist_async():
    ok = await al.persist_async("async_action", trace_id="async_t",
                                 agent="x", target="/")
    assert ok is True
    rows = al.query_recent()
    assert len(rows) == 1
