"""
forge_desktop/views/pipeline_engine_view.py
============================================
PIPELINE_ENGINE_V17 — Replace interaction_view
Sequential_Task_Runner | OneMCP_V17 | Step_by_Step_Status

Layout :
  ┌─────────────────────────────────────────────────┐
  │  Sidebar (Active_Task_List) │ Main (Live_Diff)   │
  │                             │                     │
  │  [Task 1] DONE              │  diff output live   │
  │  [Task 2] RUNNING  ●        │                     │
  │  [Task 3] PENDING           │                     │
  ├─────────────────────────────┴─────────────────────┤
  │  Footer : VRAM % | Tokens/node | Git status        │
  └─────────────────────────────────────────────────────┘
"""
from __future__ import annotations
import asyncio
import copy
import time
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QLineEdit, QTextEdit,
    QListWidget, QListWidgetItem, QGroupBox,
    QProgressBar, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize
from PySide6.QtGui import QColor, QFont

# ── Palette ───────────────────────────────────────────────────────────────────
S = {
    "IDLE":    ("#444",    "#111"),
    "PENDING": ("#ff9800", "#1a1200"),
    "RUNNING": ("#00bcd4", "#001a1a"),
    "DONE":    ("#4caf50", "#001a00"),
    "FAILED":  ("#f44336", "#1a0000"),
    "BLOCKED": ("#9c27b0", "#110018"),
    "HEALING": ("#ffeb3b", "#1a1a00"),
}
MONO = "font-family:'Cascadia Code','Consolas'; font-size:11px;"
DARK = f"background:#0a0a0a; color:#c2c0b6; {MONO}"


# ── Task Entry ────────────────────────────────────────────────────────────────
class TaskEntry:
    _counter = 0
    def __init__(self, task: str, agents: list, source: str = "Manual"):
        TaskEntry._counter += 1
        self.task_id    = f"T{TaskEntry._counter:03d}"
        self.task       = task
        self.agents     = agents
        self.source     = source
        self.status     = "PENDING"
        self.created_at = time.time()
        self.started_at = 0.0
        self.ended_at   = 0.0
        self.turns      = []
        self.tokens_out = 0
        self.error      = ""
        self.diff_lines = []

    @property
    def elapsed_ms(self) -> int:
        if self.ended_at:
            return int((self.ended_at - self.started_at) * 1000)
        if self.started_at:
            return int((time.time() - self.started_at) * 1000)
        return 0


# ── Sidebar Task Item ─────────────────────────────────────────────────────────
class _TaskItem(QFrame):
    clicked = Signal(str)

    def __init__(self, entry: TaskEntry, parent=None):
        super().__init__(parent)
        self.task_id = entry.task_id
        self._entry  = entry
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self._build()
        self.refresh(entry)

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 4, 8, 4)
        lo.setSpacing(2)

        hdr = QHBoxLayout()
        self._id_lbl = QLabel()
        self._id_lbl.setStyleSheet(f"color:#666; font-size:9px; {MONO}")
        hdr.addWidget(self._id_lbl)
        hdr.addStretch()
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(f"font-size:9px; font-weight:600; {MONO}")
        hdr.addWidget(self._status_lbl)
        self._dot = QLabel("●")
        self._dot.setStyleSheet("font-size:8px; color:#00bcd4;")
        self._dot.setVisible(False)
        hdr.addWidget(self._dot)
        lo.addLayout(hdr)

        self._task_lbl = QLabel()
        self._task_lbl.setStyleSheet(f"color:#c2c0b6; font-size:11px;")
        lo.addWidget(self._task_lbl)

        self._meta_lbl = QLabel()
        self._meta_lbl.setStyleSheet("color:#333; font-size:9px;")
        lo.addWidget(self._meta_lbl)

    def refresh(self, entry: TaskEntry):
        col, bg = S.get(entry.status, S["IDLE"])
        self.setStyleSheet(
            f"QFrame {{background:{bg}; border-left:2px solid {col}44;"
            " border-radius:4px; margin:1px 0;}}"
        )
        self._id_lbl.setText(entry.task_id)
        self._status_lbl.setText(entry.status)
        self._status_lbl.setStyleSheet(
            f"font-size:9px; font-weight:600; color:{col}; {MONO}"
        )
        self._dot.setVisible(entry.status == "RUNNING")
        self._task_lbl.setText(entry.task[:50] + ("…" if len(entry.task)>50 else ""))
        agents_str = ",".join(entry.agents[:3])
        self._meta_lbl.setText(
            f"{agents_str}  {entry.elapsed_ms}ms" if entry.started_at else agents_str
        )

    def mousePressEvent(self, _):
        self.clicked.emit(self.task_id)


# ── Pipeline Worker ───────────────────────────────────────────────────────────
class _PipelineWorker(QThread):
    step_update  = Signal(str, str, str)  # task_id, status, detail
    turn_out     = Signal(str, str, str, int)  # task_id, agent, text, chars
    task_done    = Signal(str, dict)   # task_id, result
    git_trigger  = Signal(str)         # commit message
    heal_trigger = Signal(str)         # error description

    def __init__(self, entry: TaskEntry, parent=None):
        super().__init__(parent)
        self._entry = entry

    def run(self):
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        e = self._entry
        e.started_at = time.time()

        try:
            # Step 1 : ADR check
            self.step_update.emit(e.task_id, "ADR_CHECK", "Ring2 validation…")
            adr_context = ""
            enriched    = e.task
            try:
                from forge_resonance_filter import resonance_check
                check = resonance_check("PIPELINE", e.task)
                if check["action"] == "block":
                    e.status  = "BLOCKED"
                    e.error   = check.get("correction","")[:200]
                    e.ended_at= time.time()
                    self.step_update.emit(e.task_id, "BLOCKED", e.error[:80])
                    self.task_done.emit(e.task_id, {"status":"BLOCKED","error":e.error})
                    return
                enriched    = check.get("enriched_prompt", e.task)
                adr_context = check.get("correction","")
            except Exception:
                pass

            # Step 2 : Run
            self.step_update.emit(e.task_id, "RUNNING",
                                  f"{len(e.agents)} agents")

            async def _run():
                from forge_swarm_team import _default_team, LeadOrchestrator
                team = _default_team()
                seen: dict = {}
                for pid in e.agents:
                    if pid not in seen:
                        team.activate(pid)
                        seen[pid] = 1
                    else:
                        base = next((p for p in team.participants if p.id==pid),None)
                        if base:
                            cl = copy.deepcopy(base)
                            cl.id = f"{pid}_{seen[pid]+1}"
                            cl.config = dict(base.config)
                            cl.config["system"] = "Tu es un critique. Identifie les failles."
                            cl.active = True
                            team.participants.append(cl)
                        seen[pid] += 1
                orc = LeadOrchestrator()
                return await orc.run(enriched, team, context=adr_context)

            loop = asyncio.new_event_loop()
            res  = loop.run_until_complete(_run())
            loop.close()

            e.turns = res.get("results", [])
            e.tokens_out = sum(len(str(r.get("response",""))) for r in e.turns)

            # Émettre les turns
            for turn in e.turns:
                self.turn_out.emit(
                    e.task_id,
                    turn.get("participant_id","?"),
                    str(turn.get("response",""))[:600],
                    len(str(turn.get("response",""))),
                )

            e.status   = "DONE"
            e.ended_at = time.time()
            self.step_update.emit(e.task_id, "DONE",
                f"{len(e.turns)} turns | {e.elapsed_ms}ms | {e.tokens_out} chars")
            self.task_done.emit(e.task_id, {
                "status":    "DONE",
                "turns":     len(e.turns),
                "elapsed_ms":e.elapsed_ms,
                "tokens_out":e.tokens_out,
                "session_id":res.get("session_id",""),
            })

            # on_success : git commit
            self.git_trigger.emit(
                f"pipeline: {e.task_id} — {e.task[:40]}"
            )

        except Exception as exc:
            e.status   = "FAILED"
            e.error    = str(exc)[:300]
            e.ended_at = time.time()
            self.step_update.emit(e.task_id, "FAILED", e.error[:80])
            self.task_done.emit(e.task_id, {"status":"FAILED","error":e.error})
            # on_error : autopilot heal
            self.heal_trigger.emit(e.error)


# ── Live Diff Viewer ──────────────────────────────────────────────────────────
class _LiveDiffViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0,0,0,0)
        lo.setSpacing(4)

        self._header = QLabel("— no task selected —")
        self._header.setStyleSheet(f"color:#555; font-size:11px; {MONO}")
        lo.addWidget(self._header)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(DARK + " border:1px solid #1a1a1a; border-radius:4px;")
        lo.addWidget(self._output, 1)

    def set_task(self, entry: TaskEntry):
        col, _ = S.get(entry.status, S["IDLE"])
        self._header.setText(
            f"{entry.task_id}  [{entry.status}]  "
            f"{','.join(entry.agents)}  {entry.elapsed_ms}ms"
        )
        self._header.setStyleSheet(f"color:{col}; font-size:11px; {MONO}")

    def append_turn(self, agent: str, text: str):
        col = "#2196f3"
        for k,v in {"laforge":"#2196f3","llamacpp":"#ff9800","gemini":"#4caf50",
                    "CLAUDE":"#00bcd4","groq":"#ff5722","deepseek":"#795548"}.items():
            if k.lower() in agent.lower():
                col = v; break

        self._output.append(
            f'<span style="color:{col};font-family:Cascadia Code;font-size:11px;">'
            f'[{agent}]</span>'
        )
        self._output.append(
            f'<span style="color:#c2c0b6;font-size:11px;">{text[:800]}</span>'
        )
        self._output.append('<br/>')
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear(self):
        self._output.clear()
        self._header.setText("— no task selected —")
        self._header.setStyleSheet(f"color:#555; font-size:11px; {MONO}")


# ── Footer VRAM + Token ───────────────────────────────────────────────────────
class _Footer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 0, 8, 0)
        lo.setSpacing(16)

        # VRAM
        lo.addWidget(QLabel("VRAM"))
        self._vram_bar = QProgressBar()
        self._vram_bar.setRange(0, 100)
        self._vram_bar.setValue(0)
        self._vram_bar.setFixedSize(80, 8)
        self._vram_bar.setTextVisible(False)
        self._vram_bar.setStyleSheet(
            "QProgressBar{background:#111;border:none;border-radius:4px;}"
            "QProgressBar::chunk{background:#2196f3;border-radius:4px;}"
        )
        lo.addWidget(self._vram_bar)
        self._vram_lbl = QLabel("—")
        self._vram_lbl.setStyleSheet("color:#555; font-size:10px;")
        lo.addWidget(self._vram_lbl)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#222;"); lo.addWidget(sep)

        # Tokens/node
        self._tok_lbl = QLabel("tokens/node: —")
        self._tok_lbl.setStyleSheet("color:#555; font-size:10px;")
        lo.addWidget(self._tok_lbl)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color:#222;"); lo.addWidget(sep2)

        # Git status
        self._git_lbl = QLabel("git: idle")
        self._git_lbl.setStyleSheet("color:#444; font-size:10px;")
        lo.addWidget(self._git_lbl)

        lo.addStretch()

        # Queue status
        self._queue_lbl = QLabel("queue: 0")
        self._queue_lbl.setStyleSheet("color:#444; font-size:10px;")
        lo.addWidget(self._queue_lbl)

        self.setStyleSheet("background:#0d0d0d; border-top:1px solid #1a1a1a;")

        # Refresh VRAM toutes les 3s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_vram)
        self._timer.start(3000)

    def _refresh_vram(self):
        try:
            import subprocess
            r = subprocess.run(
                ["nvidia-smi","--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=2
            )
            if r.returncode == 0 and r.stdout.strip():
                used, total = r.stdout.strip().split(",")
                pct = 100 * int(used.strip()) / max(1, int(total.strip()))
                self._update_vram(pct, int(used.strip()), int(total.strip()))
                return
        except Exception:
            pass
        self._vram_lbl.setText("iGPU")

    def _update_vram(self, pct: float, used: int, total: int):
        self._vram_bar.setValue(int(pct))
        col = "#f44336" if pct>80 else ("#ff9800" if pct>60 else "#2196f3")
        self._vram_bar.setStyleSheet(
            "QProgressBar{background:#111;border:none;border-radius:4px;}"
            f"QProgressBar::chunk{{background:{col};border-radius:4px;}}"
        )
        self._vram_lbl.setText(f"{used}MB/{total}MB")

    def set_tokens(self, tokens: int, node_count: int):
        avg = tokens // max(1, node_count)
        self._tok_lbl.setText(f"tokens/node: {avg:,}")

    def set_git(self, msg: str):
        self._git_lbl.setText(f"git: {msg[:30]}")
        self._git_lbl.setStyleSheet("color:#4caf50; font-size:10px;")
        QTimer.singleShot(5000, lambda:
            self._git_lbl.setStyleSheet("color:#444; font-size:10px;"))

    def set_queue(self, n: int):
        self._queue_lbl.setText(f"queue: {n}")
        col = "#ff9800" if n > 0 else "#444"
        self._queue_lbl.setStyleSheet(f"color:{col}; font-size:10px;")


# ── Main Engine View ──────────────────────────────────────────────────────────
class PipelineEngineView(QWidget):
    """
    PIPELINE_ENGINE_V17
    Sidebar (task list) | Main (live diff) | Footer (VRAM/tokens/git)
    Sequential_Task_Runner — on_success→git, on_error→autopilot_heal
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks:   dict[str, TaskEntry] = {}
        self._queue:   list[str] = []
        self._running: str | None = None
        self._worker:  _PipelineWorker | None = None
        self._items:   dict[str, _TaskItem] = {}
        self._total_tokens = 0
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr_bar = QWidget()
        hdr_bar.setFixedHeight(40)
        hdr_bar.setStyleSheet("background:#0d0d0d; border-bottom:1px solid #1a1a1a;")
        hdr_lo = QHBoxLayout(hdr_bar)
        hdr_lo.setContentsMargins(12, 0, 12, 0)
        title = QLabel("⬡  Pipeline Engine — Sequential_Batch v17")
        title.setStyleSheet("font-size:13px; font-weight:600; color:#c2c0b6;")
        hdr_lo.addWidget(title)
        hdr_lo.addStretch()
        self._engine_badge = QLabel("IDLE")
        self._engine_badge.setStyleSheet(
            f"background:#111; color:#444; font-size:10px; font-weight:600;"
            f" padding:2px 8px; border-radius:4px; border:1px solid #222; {MONO}"
        )
        hdr_lo.addWidget(self._engine_badge)
        outer.addWidget(hdr_bar)

        # ── Input strip ───────────────────────────────────────────────────────
        inp_bar = QWidget()
        inp_bar.setFixedHeight(38)
        inp_bar.setStyleSheet("background:#0d0d0d; border-bottom:1px solid #111;")
        inp_lo = QHBoxLayout(inp_bar)
        inp_lo.setContentsMargins(8, 4, 8, 4)
        inp_lo.setSpacing(6)

        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText("Task payload…")
        self._task_input.setStyleSheet(
            f"background:#111; color:#c2c0b6; border:1px solid #222;"
            f" border-radius:4px; padding:2px 8px; {MONO}"
        )
        self._task_input.returnPressed.connect(self._enqueue)
        inp_lo.addWidget(self._task_input, 3)

        self._agents_input = QLineEdit("nokido,llamacpp")
        self._agents_input.setFixedWidth(160)
        self._agents_input.setStyleSheet(
            f"background:#111; color:#888; border:1px solid #1a1a1a;"
            f" border-radius:4px; padding:2px 6px; {MONO}"
        )
        inp_lo.addWidget(self._agents_input)

        self._enqueue_btn = QPushButton("+ Enqueue")
        self._enqueue_btn.setFixedWidth(80)
        self._enqueue_btn.setStyleSheet(
            "background:#0a1a0a; border:1px solid #4caf5066; color:#4caf50;"
            " border-radius:4px; font-size:11px;"
        )
        self._enqueue_btn.clicked.connect(self._enqueue)
        inp_lo.addWidget(self._enqueue_btn)

        self._run_next_btn = QPushButton("▶")
        self._run_next_btn.setFixedWidth(32)
        self._run_next_btn.setStyleSheet(
            "background:#0a1a0a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; font-size:14px; font-weight:600;"
        )
        self._run_next_btn.clicked.connect(self._run_next)
        inp_lo.addWidget(self._run_next_btn)

        self._clear_btn = QPushButton("✕")
        self._clear_btn.setFixedWidth(26)
        self._clear_btn.setStyleSheet(
            "background:#111; border:1px solid #222; color:#444;"
            " border-radius:4px; font-size:11px;"
        )
        self._clear_btn.clicked.connect(self._clear_done)
        inp_lo.addWidget(self._clear_btn)

        outer.addWidget(inp_bar)

        # ── Body (splitter) ───────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("background:#0a0a0a;")
        sb_lo = QVBoxLayout(sidebar)
        sb_lo.setContentsMargins(4, 4, 4, 4)
        sb_lo.setSpacing(2)
        queue_hdr = QLabel("Active Task List")
        queue_hdr.setStyleSheet("color:#444; font-size:9px; padding:2px 4px;")
        sb_lo.addWidget(queue_hdr)
        self._task_list_container = QWidget()
        self._task_list_lo = QVBoxLayout(self._task_list_container)
        self._task_list_lo.setSpacing(2)
        self._task_list_lo.setContentsMargins(0,0,0,0)
        self._task_list_lo.addStretch()
        sb_lo.addWidget(self._task_list_container, 1)
        splitter.addWidget(sidebar)

        # Main — live diff
        self._diff = _LiveDiffViewer()
        splitter.addWidget(self._diff)
        splitter.setSizes([220, 460])
        outer.addWidget(splitter, 1)

        # ── Footer ────────────────────────────────────────────────────────────
        self._footer = _Footer()
        outer.addWidget(self._footer)

    # ── Queue management ──────────────────────────────────────────────────────

    def _enqueue(self):
        task = self._task_input.text().strip()
        if not task:
            return
        agents = [a.strip() for a in self._agents_input.text().split(",") if a.strip()]
        entry  = TaskEntry(task, agents)
        self._tasks[entry.task_id] = entry
        self._queue.append(entry.task_id)

        item = _TaskItem(entry)
        item.clicked.connect(self._select_task)
        self._items[entry.task_id] = item
        self._task_list_lo.insertWidget(self._task_list_lo.count()-1, item)

        self._task_input.clear()
        self._footer.set_queue(len(self._queue))
        self._set_badge("PENDING")

        # Auto-run si idle
        if self._running is None:
            self._run_next()

    def _run_next(self):
        if self._running or not self._queue:
            return
        task_id = self._queue.pop(0)
        self._running = task_id
        entry = self._tasks[task_id]
        entry.status = "RUNNING"

        # Afficher dans diff
        self._diff.clear()
        self._diff.set_task(entry)
        self._items[task_id].refresh(entry)
        self._set_badge("RUNNING")
        self._footer.set_queue(len(self._queue))

        self._worker = _PipelineWorker(entry, parent=self)
        self._worker.step_update.connect(self._on_step)
        self._worker.turn_out.connect(self._on_turn)
        self._worker.task_done.connect(self._on_task_done)
        self._worker.git_trigger.connect(self._on_git)
        self._worker.heal_trigger.connect(self._on_heal)
        self._worker.start()

    def _clear_done(self):
        for tid in list(self._tasks.keys()):
            if self._tasks[tid].status in ("DONE","FAILED","BLOCKED"):
                if tid in self._items:
                    self._items[tid].deleteLater()
                    del self._items[tid]
                del self._tasks[tid]
        self._footer.set_queue(len(self._queue))

    def _select_task(self, task_id: str):
        entry = self._tasks.get(task_id)
        if not entry:
            return
        self._diff.clear()
        self._diff.set_task(entry)
        for turn in entry.turns:
            self._diff.append_turn(
                turn.get("participant_id","?"),
                str(turn.get("response",""))[:600]
            )

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_step(self, task_id: str, status: str, detail: str):
        entry = self._tasks.get(task_id)
        if entry:
            entry.status = status
            if task_id in self._items:
                self._items[task_id].refresh(entry)
            if task_id == self._running:
                self._diff.set_task(entry)
        self._set_badge(status)

    def _on_turn(self, task_id: str, agent: str, text: str, chars: int):
        if task_id == self._running:
            self._diff.append_turn(agent, text)

    def _on_task_done(self, task_id: str, result: dict):
        entry = self._tasks.get(task_id)
        if entry:
            entry.status = result.get("status","DONE")
            entry.ended_at = time.time()
            self._total_tokens += entry.tokens_out
            if task_id in self._items:
                self._items[task_id].refresh(entry)
            if task_id == self._running:
                self._diff.set_task(entry)

        self._running = None
        done_count = sum(1 for e in self._tasks.values() if e.status=="DONE")
        self._footer.set_tokens(self._total_tokens, done_count)
        self._set_badge("IDLE" if not self._queue else "PENDING")

        # Auto-run suivant
        if self._queue:
            QTimer.singleShot(200, self._run_next)

    def _on_git(self, msg: str):
        self._footer.set_git(f"committed: {msg[:24]}")

    def _on_heal(self, error: str):
        self._footer.set_git(f"HEAL: {error[:24]}")
        self._set_badge("HEALING")
        self._footer._git_lbl.setStyleSheet("color:#ffeb3b; font-size:10px;")

    def _set_badge(self, status: str):
        col, bg = S.get(status, S["IDLE"])
        self._engine_badge.setText(status)
        self._engine_badge.setStyleSheet(
            f"background:{bg}; color:{col}; font-size:10px; font-weight:600;"
            f" padding:2px 8px; border-radius:4px; border:1px solid {col}44; {MONO}"
        )

    def closeEvent(self, event):
        """Arrêt propre des workers QThread."""
        if hasattr(self, '_worker') and self._worker is not None:
            if hasattr(self._worker, 'stop'):
                self._worker.stop()
            if hasattr(self._worker, 'wait'):
                self._worker.wait(1000)
            if hasattr(self._worker, 'terminate'):
                self._worker.terminate()
        super().closeEvent(event)