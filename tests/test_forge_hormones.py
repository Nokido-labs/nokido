import pytest, time
import forge_hormones as fh


@pytest.fixture(autouse=True)
def _reset_state():
    fh._ACTIVE.clear()
    fh._SUBSCRIBERS.clear()
    yield
    fh._ACTIVE.clear()
    fh._SUBSCRIBERS.clear()


def test_decay_at_release_equals_level():
    rec = {"level": 1.0, "released_ts": 1000.0, "half_life_s": 60}
    assert fh._decay_level(rec, 1000.0) == 1.0


def test_decay_at_half_life_is_half():
    rec = {"level": 1.0, "released_ts": 1000.0, "half_life_s": 60}
    assert fh._decay_level(rec, 1060.0) == pytest.approx(0.5, abs=1e-6)


def test_decay_at_two_half_lives_is_quarter():
    rec = {"level": 1.0, "released_ts": 1000.0, "half_life_s": 60}
    assert fh._decay_level(rec, 1120.0) == pytest.approx(0.25, abs=1e-6)


def test_release_then_active_returns_event():
    r = fh.release("adrenaline", 0.5, {"k": "v"}, ["agt"])
    assert r["ok"] is True
    act = fh.active("adrenaline")
    assert len(act) == 1 and act[0]["hormone"] == "adrenaline"


def test_cleanup_purges_expired():
    fh.release("adrenaline", 0.5)
    for rec in fh._ACTIVE.values():
        rec["expires_at"] = time.time() - 10
    assert fh.cleanup() == 1
    assert fh._ACTIVE == {}


def test_push_to_subscribers_noop_without_subscriber():
    fh._push_to_subscribers({"x": 1})  # no raise
