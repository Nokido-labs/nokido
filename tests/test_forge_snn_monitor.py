"""Phase 39 SNN monitor tests (fallback path principal, snntorch optional)."""
import time
import pytest
import forge_snn_monitor as snm


def test_available_returns_bool():
    assert isinstance(snm.available(), bool)


def test_fallback_static_spike_on_threshold():
    """Sans snntorch, path statique pure threshold."""
    mon = snm.SNNMonitor(enabled=False)
    spikes = mon.feed({"ram_pct": 90, "cpu_pct": 50, "gpu_pct": None})
    assert spikes["ram"] is True
    assert spikes["cpu"] is False
    assert spikes["gpu"] is False


def test_fallback_below_threshold_no_spike():
    mon = snm.SNNMonitor(enabled=False)
    spikes = mon.feed({"ram_pct": 50, "cpu_pct": 60, "gpu_pct": 70})
    assert all(v is False for v in spikes.values())


def test_refractory_blocks_second_spike():
    mon = snm.SNNMonitor(enabled=False)
    s1 = mon.feed({"ram_pct": 90, "cpu_pct": 0, "gpu_pct": 0})
    s2 = mon.feed({"ram_pct": 90, "cpu_pct": 0, "gpu_pct": 0})
    assert s1["ram"] is True
    assert s2["ram"] is False   # refractory bloque


def test_window_keeps_last_60_samples():
    mon = snm.SNNMonitor(enabled=False)
    for i in range(100):
        mon.feed({"ram_pct": i, "cpu_pct": 0, "gpu_pct": 0})
    assert len(mon.window) == snm._WINDOW


def test_get_monitor_singleton():
    a = snm.get_monitor()
    b = snm.get_monitor()
    assert a is b


def test_gpu_none_no_spike():
    """gpu_pct None ne doit pas spike (GPU absent)."""
    mon = snm.SNNMonitor(enabled=False)
    spikes = mon.feed({"ram_pct": 0, "cpu_pct": 0, "gpu_pct": None})
    assert spikes["gpu"] is False
