"""
forge_desktop/core/gui_mmap.py
================================
Interface MMap ultra-rapide pour Forge-Sync OS.
Lit/écrit dans live_bridge.map (zone JSON) — zéro réseau, zéro socket.
Vitesse : < 1µs par lecture. Adapté aux logiciels temps réel.

Zone réservée GUI dans live_bridge JSON :
  gui.heartbeat      → float  — timestamp pulse GUI (watchdog check)
  gui.pid            → int    — PID du process desktop
  gui.state          → str    — RUNNING / FROZEN / KILLED
  gui.active_view    → str    — vue active
  llm.{id}.vram_mb   → int    — VRAM par LLM
  llm.{id}.tokens_s  → float  — tokens/sec
  llm.{id}.state     → str    — état LLM
  watchdog.pid       → int    — PID watchdog
  watchdog.last_beat → float  — dernier pulse watchdog
  watchdog.alert     → bool   — True si bridge frozen
  watchdog.kills     → list   — PIDs tués par watchdog
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


class GuiMMap:
    """
    Façade MMap pour la GUI desktop.
    Réutilise live_bridge.bridge (singleton) — même fichier mmap.
    Thread-safe via le lock interne de live_bridge.
    """

    def __init__(self):
        self._bridge = None
        self._pid    = os.getpid()
        self._init_bridge()

    def _init_bridge(self):
        try:
            from live_bridge import bridge
            self._bridge = bridge
            # Enregistrer le PID GUI
            bridge.json_set("gui.pid",   self._pid)
            bridge.json_set("gui.state", "RUNNING")
            bridge.json_set("gui.heartbeat", time.time())
        except Exception as e:
            self._bridge = None

    # ── Heartbeat — appelé par QTimer toutes les 1s ───────────────────────

    def beat(self, view: str = "") -> None:
        """Met à jour le heartbeat GUI — < 1µs."""
        if not self._bridge:
            return
        try:
            self._bridge.json_set("gui.heartbeat", time.time())
            if view:
                self._bridge.json_set("gui.active_view", view)
        except Exception:
            pass

    # ── Lecture état swarm ────────────────────────────────────────────────

    def swarm_state(self) -> dict:
        """Lit l'état swarm depuis mmap — < 1µs."""
        if not self._bridge:
            return {"state": "UNKNOWN", "active_agent": "", "seq": 0}
        try:
            lb = self._bridge.snapshot().get("json", {})
            return {
                "state":        lb.get("swarm.state",        "IDLE"),
                "active_agent": lb.get("swarm.active_agent", ""),
                "seq":          lb.get("swarm.seq",          0),
                "ts":           lb.get("swarm.ts",           0.0),
            }
        except Exception:
            return {"state": "UNKNOWN", "active_agent": "", "seq": 0}

    def all_llm_states(self) -> dict:
        """Lit l'état de tous les LLMs depuis mmap."""
        if not self._bridge:
            return {}
        try:
            lb  = self._bridge.snapshot().get("json", {})
            out = {}
            for k, v in lb.items():
                if k.startswith("llm."):
                    parts = k.split(".", 2)
                    if len(parts) == 3:
                        llm_id, field = parts[1], parts[2]
                        if llm_id not in out:
                            out[llm_id] = {}
                        out[llm_id][field] = v
            return out
        except Exception:
            return {}

    def watchdog_status(self) -> dict:
        """Lit l'état du watchdog depuis mmap."""
        if not self._bridge:
            return {"pid": 0, "alert": False, "last_beat": 0.0}
        try:
            lb = self._bridge.snapshot().get("json", {})
            return {
                "pid":       lb.get("watchdog.pid",       0),
                "last_beat": lb.get("watchdog.last_beat", 0.0),
                "alert":     lb.get("watchdog.alert",     False),
                "kills":     lb.get("watchdog.kills",     []),
            }
        except Exception:
            return {"pid": 0, "alert": False, "last_beat": 0.0}

    # ── Écriture état LLM (depuis workers) ───────────────────────────────

    def set_llm_state(self, llm_id: str, state: str,
                      vram_mb: int = 0, tokens_s: float = 0.0) -> None:
        if not self._bridge:
            return
        try:
            self._bridge.json_set(f"llm.{llm_id}.state",    state)
            self._bridge.json_set(f"llm.{llm_id}.vram_mb",  vram_mb)
            self._bridge.json_set(f"llm.{llm_id}.tokens_s", tokens_s)
        except Exception:
            pass

    # ── Lecture snapshot complet ──────────────────────────────────────────

    def full_snapshot(self) -> dict:
        """Snapshot complet — pour debug."""
        if not self._bridge:
            return {}
        try:
            return self._bridge.snapshot().get("json", {})
        except Exception:
            return {}

    # ── Shutdown propre ───────────────────────────────────────────────────

    def shutdown(self) -> None:
        if self._bridge:
            try:
                self._bridge.json_set("gui.state",     "KILLED")
                self._bridge.json_set("gui.heartbeat", 0.0)
            except Exception:
                pass


# Singleton exporté
gui_mmap = GuiMMap()
