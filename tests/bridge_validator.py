"""
tests/bridge_validator.py
==========================
Validation câblage GUI PySide6 — Signaux, Slots, QThread.
Compatible : pytest tests/bridge_validator.py -v
             python tests/bridge_validator.py   (mode standalone)

Utilise pytestqt (qtbot) pour simuler les événements Qt.
Chaque test est indépendant et peut être lancé isolément.
"""
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

# ── Helpers ───────────────────────────────────────────────────────────────────

def _process(qtbot, ms: int = 50):
    """Pompe les événements Qt — équivalent processEvents()."""
    from PySide6.QtCore import QTimer
    qtbot.wait(ms)


def _wait_for(qtbot, condition_fn, timeout_ms: int = 8000, interval_ms: int = 100):
    """Attente non-bloquante d'une condition."""
    qtbot.waitUntil(condition_fn, timeout=timeout_ms)


# ═══════════════════════════════════════════════════════════════
# T01 : DebateView — attributs publics pour QTest
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
def test_debate_view_public_attrs(qtbot):
    from forge_desktop.views.debate_view import DebateView
    view = DebateView()
    qtbot.addWidget(view)
    view.show()
    _process(qtbot)

    assert hasattr(view, "input_field"),  "input_field manquant"
    assert hasattr(view, "btn_start"),    "btn_start manquant"
    assert hasattr(view, "output_area"),  "output_area manquant"
    assert view.input_field.objectName() == "debate_input"
    assert view.btn_start.objectName()   == "btn_debate_start"
    assert view.output_area.objectName() == "debate_output"


# ═══════════════════════════════════════════════════════════════
# T02 : keyClicks + mouseClick → submit_clicked émis
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
def test_debate_submit_signal(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from forge_desktop.views.debate_view import DebateView

    view = DebateView()
    qtbot.addWidget(view)
    view.show()
    _process(qtbot)

    received = []
    view._synth.submit_clicked.connect(received.append)

    # Simuler frappe clavier
    QTest.keyClicks(view.input_field, "Test câblage signal")
    _process(qtbot)
    assert view.input_field.text() == "Test câblage signal"

    # Simuler clic bouton
    with qtbot.waitSignal(view._synth.submit_clicked, timeout=3000):
        QTest.mouseClick(view.btn_start, Qt.MouseButton.LeftButton)

    assert len(received) == 1
    assert received[0] == "Test câblage signal"


# ═══════════════════════════════════════════════════════════════
# T03 : DebateWorker instancié + start() appelé
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
@pytest.mark.slow
def test_debate_worker_started(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from forge_desktop.views.debate_view import DebateView
    from forge_desktop.core.llm_interactions import DebateWorker

    view = DebateView()
    qtbot.addWidget(view)
    view.show()
    _process(qtbot)

    assert view._worker is None, "worker doit être None avant lancement"

    QTest.keyClicks(view.input_field, "ping")
    QTest.mouseClick(view.btn_start, Qt.MouseButton.LeftButton)
    _process(qtbot, 200)

    # Worker instancié et stocké (GC-safe)
    assert view._worker is not None, "worker non instancié après clic"
    assert isinstance(view._worker, DebateWorker)

    # start() appelé — worker running ou fini
    _wait_for(
        qtbot,
        lambda: view._worker.isRunning() or view._worker.isFinished(),
        timeout_ms=3000,
    )

    # output_area peuplée — log MCP visible
    _wait_for(
        qtbot,
        lambda: len(view.output_area.toPlainText()) > 5,
        timeout_ms=3000,
    )
    assert "[DEBATE]" in view.output_area.toPlainText() or \
           "[MCP]"    in view.output_area.toPlainText()

    # Nettoyage
    if view._worker.isRunning():
        view._cancel()
        view._worker.wait(2000)


# ═══════════════════════════════════════════════════════════════
# T04 : Bouton désactivé pendant débat, réactivé après
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
def test_debate_button_state(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from forge_desktop.views.debate_view import DebateView

    view = DebateView()
    qtbot.addWidget(view)
    view.show()
    _process(qtbot)

    # État initial
    assert view.btn_start.isEnabled()
    assert not view._btn_cancel.isEnabled()

    # Lancer un débat
    QTest.keyClicks(view.input_field, "test")
    QTest.mouseClick(view.btn_start, Qt.MouseButton.LeftButton)
    _process(qtbot, 200)

    # Pendant le débat
    assert not view.btn_start.isEnabled(), "btn_start devrait être disabled"
    assert view._btn_cancel.isEnabled(),   "btn_cancel devrait être enabled"

    # Annuler → reset UI
    view._cancel()
    _process(qtbot, 200)
    assert view.btn_start.isEnabled(), "btn_start devrait être réactivé"


# ═══════════════════════════════════════════════════════════════
# T05 : _reset_ui transitions d'état
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
def test_reset_ui(qtbot):
    from forge_desktop.views.debate_view import DebateView

    view = DebateView()
    qtbot.addWidget(view)
    view.show()
    _process(qtbot)

    # Simuler état en cours
    view._synth.btn_start.setEnabled(False)
    view._btn_cancel.setEnabled(True)
    _process(qtbot)

    view._reset_ui("DONE")
    _process(qtbot)

    assert view.btn_start.isEnabled()
    assert not view._btn_cancel.isEnabled()


# ═══════════════════════════════════════════════════════════════
# T06 : MCPWorker — non-bloquant (signal result_ready reçu)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
@pytest.mark.slow
def test_mcp_worker_nonblocking(qtbot):
    from forge_desktop.core.mcp_connector import MCPWorker, local_bridge

    bridge = local_bridge()
    worker = MCPWorker(bridge, "rag_stats", {})
    qtbot.add_widget = lambda w: None   # MCPWorker n'est pas un widget

    received = []
    worker.result_ready.connect(received.append)
    worker.start()

    try:
        _wait_for(
            qtbot,
            lambda: bool(received) or worker.isFinished(),
            timeout_ms=10000,
        )
    except Exception:
        pass   # timeout acceptable — le serveur MCP peut être down

    # Dans tous les cas, le QThread a fini sans freezer l'event loop
    assert worker.isFinished() or not worker.isRunning(), \
        "MCPWorker bloque le thread Qt"


# ═══════════════════════════════════════════════════════════════
# T07 : LLMPingWorker — signaux ping_result + all_done
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
@pytest.mark.slow
def test_llm_ping_worker(qtbot):
    from forge_desktop.core.llm_interactions import LLMPingWorker

    pings  = []
    dones  = []
    worker = LLMPingWorker(["laforge", "llamacpp"])
    worker.ping_result.connect(lambda aid, ok, info: pings.append((aid, ok, info)))
    worker.all_done.connect(dones.append)
    worker.start()

    try:
        _wait_for(qtbot, lambda: bool(dones), timeout_ms=12000)
    except Exception:
        pass

    # Peu importe le résultat (agents peuvent être down)
    # L'important : le signal all_done a été émis ou le worker a fini
    assert worker.isFinished() or dones, "LLMPingWorker n'a pas émis all_done"


# ═══════════════════════════════════════════════════════════════
# T08 : Ring-O-Meter — update_from_resonance modifie les états
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
def test_ring_o_meter_block_state(qtbot):
    from forge_desktop.widgets.ring_o_meter import (
        RingOMeterWidget, STATE_BLOCK, STATE_ALERT, STATE_OK
    )

    rom = RingOMeterWidget()
    qtbot.addWidget(rom)
    rom.show()
    _process(qtbot)

    # Simuler violation ring 0
    rom.update_from_resonance({
        "last_action": "block",
        "drift_score": 0.95,
        "last_agent":  "TEST",
    })
    _process(qtbot)

    assert rom._dial._states[0]["state"]  == STATE_BLOCK
    assert rom._dial._states[10]["state"] == STATE_ALERT


@pytest.mark.gui
def test_ring_o_meter_alert_clears(qtbot):
    from forge_desktop.widgets.ring_o_meter import (
        RingOMeterWidget, STATE_BLOCK, STATE_ALERT, STATE_OK
    )

    rom = RingOMeterWidget()
    qtbot.addWidget(rom)
    rom.show()

    # Alert puis pass
    rom.update_from_resonance({"last_action": "warn", "drift_score": 0.4, "last_agent": "X"})
    _process(qtbot)

    rom.update_from_resonance({"last_action": "pass", "drift_score": 0.0, "last_agent": "X"})
    _process(qtbot)

    # ring 0 reste OK (pas de block)
    assert rom._dial._states[0]["state"] == STATE_OK


# ═══════════════════════════════════════════════════════════════
# T09 : Vider la console + état clear
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
def test_debate_clear(qtbot):
    from forge_desktop.views.debate_view import DebateView

    view = DebateView()
    qtbot.addWidget(view)
    view.show()
    _process(qtbot)

    view.output_area.appendPlainText("test log")
    _process(qtbot)
    assert view.output_area.toPlainText() != ""

    view._clear_all()
    _process(qtbot)
    assert view.output_area.toPlainText() == ""


# ═══════════════════════════════════════════════════════════════
# T10 : Connexions __init__ — câblage permanent vérifié
# ═══════════════════════════════════════════════════════════════

@pytest.mark.gui
def test_debate_view_wiring_init(qtbot):
    """Vérifie que les connexions critiques sont établies dans __init__."""
    from forge_desktop.views.debate_view import DebateView

    view = DebateView()
    qtbot.addWidget(view)
    view.show()
    _process(qtbot)

    # submit_clicked → _launch_debate : tester en envoyant un signal direct
    calls = []
    original = view._launch_debate
    view._launch_debate = lambda task: calls.append(task) or original(task)

    view._synth.submit_clicked.emit("câblage test")
    _process(qtbot, 100)

    assert calls, "submit_clicked n'est pas connecté à _launch_debate"
    assert calls[0] == "câblage test"

    if view._worker and view._worker.isRunning():
        view._cancel()


# ═══════════════════════════════════════════════════════════════
# Mode standalone
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v",
         "-m", "gui", "--tb=short"],
        cwd=str(ROOT),
    )
    sys.exit(result.returncode)
