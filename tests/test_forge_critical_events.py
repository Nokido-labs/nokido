import pytest
import time
import forge_critical_events as ce


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "DB_PATH", tmp_path / "evt.db")
    monkeypatch.setattr(ce, "_INITIALIZED", False)
    yield


def test_persist_then_unprocessed_returns_event():
    rid = ce.persist("hormone", "critical", {"k": "v"})
    assert rid > 0
    unp = ce.unprocessed()
    assert len(unp) == 1 and unp[0]["kind"] == "hormone"


def test_mark_processed_clears_unprocessed():
    rid = ce.persist("cve", "warn", {})
    ce.mark_processed([rid])
    assert ce.unprocessed() == []


def test_purge_older_than_respects_cutoff():
    rid = ce.persist("x", "warn", {})
    ce.mark_processed([rid])
    # backdate
    with ce._conn() as c:
        c.execute("UPDATE forge_critical_events SET ts=? WHERE id=?",
                  (time.time() - 30 * 86400, rid))
    assert ce.purge_older_than(days=7) == 1


def test_backup_creates_file():
    ce.persist("test", "info", {"x": 1})
    res = ce.backup(suffix="testbak")
    assert res["ok"] is True
    from pathlib import Path
    assert Path(res["path"]).exists()
