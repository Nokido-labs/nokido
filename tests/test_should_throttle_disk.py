"""Autoregulation disque — should_throttle percoit enfin le disque (2026-07-14).

Trou : le disque etait mesure (get_snapshot.disk_pct) mais should_throttle ne le
regardait pas -> a disque quasi-plein, les taches disk-heavy (embed batch, vector
rebuild) continuaient jusqu'au write-crash. Ces tests verrouillent le garde-fou.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import forge_resource_manager as rm  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cortisol(monkeypatch):
    """Neutralise l'efferent endocrinien pour isoler la logique ressources/disque
    (should_throttle throttle aussi si CORTISOL_* reel >= seuil)."""
    try:
        import forge_endocrine
        monkeypatch.setattr(forge_endocrine, "read", lambda *a, **k: 0.0)
    except Exception:
        pass


def _snap(disk_pct):
    return {"ram_pct": 10.0, "cpu_pct": 5.0, "gpu_pct": 1.0, "tdr_recent": 0, "disk_pct": disk_pct}


def test_disk_below_threshold_does_not_throttle(monkeypatch):
    """Usage normal (~88%) ne doit PAS freiner : seul le bord (>=95%) agit."""
    monkeypatch.setattr(rm, "get_snapshot", lambda: _snap(88.0))
    assert rm.should_throttle() is False


def test_disk_at_critical_throttles(monkeypatch):
    """Disque quasi-plein (>=95%) -> throttle (protege contre write-crash)."""
    monkeypatch.setattr(rm, "get_snapshot", lambda: _snap(96.0))
    assert rm.should_throttle() is True


def test_disk_threshold_is_tunable(monkeypatch):
    """Le seuil disque est parametrable (ex: tache tres disk-sensible)."""
    monkeypatch.setattr(rm, "get_snapshot", lambda: _snap(88.0))
    assert rm.should_throttle(disk_pct_threshold=85.0) is True
    assert rm.should_throttle(disk_pct_threshold=95.0) is False
