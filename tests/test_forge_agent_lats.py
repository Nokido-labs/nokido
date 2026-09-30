import pytest
import forge_agent_lats as lats


@pytest.fixture(autouse=True)
def _no_hormone_no_git(monkeypatch):
    monkeypatch.setattr(lats, "_release_hormone", lambda *a, **kw: None)
    monkeypatch.setattr(lats, "_snapshot_state", lambda: {"head": "x", "dirty": False, "ts": 0})
    # Phase 16 worktree : skip git operations (test runs sans repo isolation)
    monkeypatch.setattr(lats, "_worktree_create", lambda agent_name: None)
    monkeypatch.setattr(lats, "_worktree_destroy", lambda wt_path: None)
    monkeypatch.setattr(lats, "_git_reset_clean", lambda wt_path: None)
    # _isolated_worktree devient no-op context manager
    from contextlib import contextmanager
    @contextmanager
    def _noop_iso(agent_name):
        yield None
    monkeypatch.setattr(lats, "_isolated_worktree", _noop_iso)
    monkeypatch.setattr(lats, "_git", lambda *a, **kw: (0, "", ""))


def test_default_eval_none_rejected():
    assert lats._default_eval(None)["grade"] == "REJECTED"


def test_default_eval_error_rejected():
    assert lats._default_eval({"error": "boom"})["grade"] == "REJECTED"


def test_default_eval_ok_promoted():
    assert lats._default_eval({"ok": True})["grade"] == "PROMOTED"


def test_run_with_lats_success_first_try():
    res = lats.run_with_lats(lambda t, c: {"ok": True}, "task", max_retries=2,
                             rollback_on_reject=False)
    assert res["ok"] is True and res["attempts"] == 1


def test_run_with_lats_fail_then_success():
    calls = {"n": 0}
    def agent(t, c):
        calls["n"] += 1
        return {"error": "x"} if calls["n"] < 2 else {"ok": True}
    res = lats.run_with_lats(agent, "task", max_retries=2, rollback_on_reject=False)
    assert res["ok"] is True and res["attempts"] == 2


def test_run_with_lats_always_fail_exhausts():
    res = lats.run_with_lats(lambda t, c: {"error": "nope"}, "task", max_retries=2,
                             rollback_on_reject=False)
    assert res["ok"] is False and res["attempts"] == 3
