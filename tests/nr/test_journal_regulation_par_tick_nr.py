import json
import os
from pathlib import Path

import pytest

# Import the module under test
import forge_resource_manager as rm

@pytest.fixture
def reset_snapshot(monkeypatch):
    # Ensure _SNAPSHOT global is set with needed values
    snapshot = {
        "ram_pct_plancher_60s": 95.0,
        "ram_free_gb": 1.0,
        "ram_total_gb": 16.0,
        "ram_pct": 95.0,
    }
    monkeypatch.setattr(rm, "_SNAPSHOT", snapshot, raising=False)
    # Ensure environment threshold low enough to trigger press
    monkeypatch.setenv("LAFORGE_SUPERVISOR_SLEEP_RAM_THRESHOLD", "90")
    # Mock dependencies
    monkeypatch.setattr(rm, "plan_hamilton", lambda detresse=False: {"delester": [{"service": "svc1", "rss_mb": 1024}], "verdict": "SOI"}, raising=False)
    monkeypatch.setattr(rm, "palier_pression_ram", lambda ram, libre: "NORMAL", raising=False)
    monkeypatch.setattr(rm, "vetos_sommeil_actifs", lambda: {}, raising=False)
    # Mock regulation_hamilton_ram to produce gestures
    def mock_regulation(plan, ram_pct, total, etat, now, vetos=None, critique=False, demandes=None):
        return {"gestes": {"svc1": "SUSPENDRE"}, "etat": {}, "choisis": [], "motif": "test"}
    monkeypatch.setattr(rm, "regulation_hamilton_ram", mock_regulation, raising=False)
    # Ensure HAMILTON_ETAT_RAM_PATH points to a temp file
    tmp_path = Path(rm.__file__).resolve().parent.parent / "sandbox" / "hamilton_state_test.json"
    monkeypatch.setattr(rm, "_HAMILTON_ETAT_RAM_PATH", tmp_path, raising=False)
    # Redirect tick journal path to temporary location
    tick_path = Path(rm.__file__).resolve().parent.parent / "sandbox" / "regulation_tick_test.jsonl"
    monkeypatch.setattr(rm, "_REGULATION_TICK_PATH", tick_path, raising=False)
    # Ensure max bytes for journal
    monkeypatch.setattr(rm, "_REGULATION_TICK_MAX_BYTES", 1024 * 1024, raising=False)
    # Clean up any existing file
    if tick_path.exists():
        tick_path.unlink()
    yield
    # Cleanup after test
    if tick_path.exists():
        tick_path.unlink()
    if tmp_path.exists():
        tmp_path.unlink()

def test_tick_writes_entry(reset_snapshot):
    result = rm._regulation_hamilton_tick()
    # Verify result contains gestures
    assert result.get("gestes")
    # Verify tick journal file created and contains expected fields
    tick_file = rm._REGULATION_TICK_PATH
    assert tick_file.exists()
    line = tick_file.read_text(encoding="utf-8").strip()
    row = json.loads(line)
    # Check required keys and values
    assert isinstance(row["ts"], (int, float))
    assert row["plancher_60s_pct"] == 95.0
    assert row["ram_free_gb"] == 1.0
    assert row["palier"] == "NORMAL"
    assert row["verdict"] == "SOI"
    assert row["n_candidats"] == 1
    assert row["n_vetos"] == 0

def test_tick_without_gesture_still_writes(reset_snapshot, monkeypatch):
    # Modify mock to return no gestures
    def mock_reg_no_gesture(plan, ram_pct, total, etat, now, vetos=None, critique=False, demandes=None):
        return {"gestes": {}, "etat": {}, "choisir": [], "motif": "test"}
    monkeypatch.setattr(rm, "regulation_hamilton_ram", mock_reg_no_gesture, raising=False)
    result = rm._regulation_hamilton_tick()
    assert not result.get("gestes")
    tick_file = rm._REGULATION_TICK_PATH
    assert tick_file.exists()
    line = tick_file.read_text(encoding="utf-8").strip()
    row = json.loads(line)
    assert row["n_candidats"] == 1
    assert row["n_vetos"] == 0
