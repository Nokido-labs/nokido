"""Tests forge_circadian - rythme physiologique."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_circadian import (  # noqa
    PHASE_PROGRAM, Phase, PhysiologicalState, current_phase,
    fire_phase, load_state, report_status, save_state,
)


# === Phase detection =========================================================

@pytest.mark.parametrize("hour,expected", [
    (7, Phase.AURORE), (10, Phase.JOUR), (17, Phase.JOUR),
    (19, Phase.CREPUSCULE), (21, Phase.CREPUSCULE),
    (23, Phase.NREM1), (0, Phase.NREM1), (1, Phase.NREM1),
    (3, Phase.NREM3),
    (5, Phase.REM),
])
def test_phase_detection_by_hour(hour, expected):
    now = datetime(2026, 5, 24, hour, 0, 0)
    assert current_phase(now) == expected


# === Phase program coverage ==================================================

def test_all_phases_have_program():
    for p in Phase:
        assert p in PHASE_PROGRAM
        assert len(PHASE_PROGRAM[p]) >= 1


def test_organs_documented():
    for p, actions in PHASE_PROGRAM.items():
        for a in actions:
            assert a.organ, f"action {a.name} in {p} sans organ"
            assert a.why, f"action {a.name} in {p} sans why"


# === PhysiologicalState ======================================================

def test_state_debt_inf_if_never_completed():
    st = PhysiologicalState()
    assert st.debt_hours(Phase.NREM3) == float("inf")


def test_state_mark_completed_resets_debt():
    st = PhysiologicalState()
    st.mark_completed(Phase.NREM3)
    assert st.debt_hours(Phase.NREM3) < 1.0


def test_sleep_debt_when_NREM_skipped():
    st = PhysiologicalState()
    import time
    # NREM1 + NREM3 > 48h ago
    st.last_completed[Phase.NREM1] = time.time() - 49 * 3600
    st.last_completed[Phase.NREM3] = time.time() - 50 * 3600
    assert st.has_sleep_debt() is True


def test_no_sleep_debt_if_recent_NREM():
    st = PhysiologicalState()
    import time
    st.last_completed[Phase.NREM1] = time.time() - 12 * 3600
    st.last_completed[Phase.NREM3] = time.time() - 10 * 3600
    assert st.has_sleep_debt() is False


# === fire_phase (dry_run) ====================================================

def test_fire_phase_dry_run_no_side_effects():
    st = PhysiologicalState()
    r = fire_phase(Phase.NREM3, state=st, dry_run=True)
    assert r["phase"] == "NREM3"
    assert len(r["results"]) == len(PHASE_PROGRAM[Phase.NREM3])
    for res in r["results"]:
        assert res.get("dry_run") is True
    # Un dry_run ne solde RIEN : la dette reste entiere. L'assertion inverse vivait
    # ici sous un commentaire « state mark_completed est OK », en contradiction avec
    # le nom meme du test -- et elle VERROUILLAIT le defaut : une SIMULATION mutait
    # l'etat physiologique, effacant la dette de sommeil sans qu'aucune action n'ait
    # lieu. Corrige le 2026-08-25 dans `fire_phase`. Un banc d'essai qui modifie le
    # patient n'est pas un banc d'essai.
    assert st.debt_hours(Phase.NREM3) == float("inf")
    assert r["completed"] is False


def test_fire_phase_invokes_restart_for_services():
    with patch("forge_circadian._restart_service",
               return_value={"ok": True}) as mock_restart:
        r = fire_phase(Phase.NREM3, state=PhysiologicalState())
    # NREM3 contient au moins offline_replay + night_train (services)
    assert mock_restart.call_count >= 2
    services_called = [c.args[0] for c in mock_restart.call_args_list]
    assert "NokidoOfflineTrainer" in services_called


# === Persistence =============================================================

def test_state_roundtrip(monkeypatch):
    import forge_circadian
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    monkeypatch.setattr(forge_circadian, "_STATE_PATH", Path(tmp.name))
    try:
        st = PhysiologicalState()
        st.mark_completed(Phase.AURORE)
        st.mark_completed(Phase.REM)
        save_state(st)
        st2 = load_state()
        assert Phase.AURORE in st2.last_completed
        assert Phase.REM in st2.last_completed
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# === report_status ===========================================================

def test_report_status_shape():
    r = report_status()
    assert "active_phase" in r
    assert "active_organs" in r
    assert "sleep_debt" in r
    assert "debt_hours" in r
    assert isinstance(r["active_organs"], list)
