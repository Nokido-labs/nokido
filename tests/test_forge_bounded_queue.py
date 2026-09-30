import pytest
from forge_bounded_queue import BoundedQueue


def test_capacity_3_with_5_put_returns_3_ok_2_rejected():
    bq = BoundedQueue("t", capacity=3, leptin_release=False)
    results = [bq.try_put(i) for i in range(5)]
    assert results.count(True) == 3 and results.count(False) == 2


def test_get_drains_fifo():
    bq = BoundedQueue("t", capacity=3, leptin_release=False)
    for i in range(3):
        bq.try_put(i)
    assert [bq.get_nowait() for _ in range(3)] == [0, 1, 2]


def test_stats_reflects_accepted_and_rejected():
    bq = BoundedQueue("t", capacity=2, leptin_release=False)
    bq.try_put("a"); bq.try_put("b"); bq.try_put("c")
    s = bq.stats()
    assert s["accepted"] == 2 and s["rejected"] == 1 and s["current"] == 2


def test_invalid_capacity_raises():
    with pytest.raises(ValueError):
        BoundedQueue("t", capacity=0)
