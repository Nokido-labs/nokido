"""
forge_desktop/core/desktop_bridge.py
=====================================
Pont entre l'UI PySide6 et les services Nokido.

Architecture indestructible :
  - LECTURE : directement depuis live_bridge.map (mmap) — < 1µs, zéro réseau
  - ÉCRITURE heartbeat : live_bridge.json_set depuis QTimer 1s
  - WATCHDOG : process séparé qui surveille gui.heartbeat dans mmap
  - FALLBACK HTTP : Hub /health /metrics /swarm pour les métriques étendues

QThread workers :
  - MMapPollerWorker   → lit mmap toutes les 100ms (état swarm + LLMs)
  - HubPollerWorker    → interroge Hub toutes les 3s (métriques étendues)
  - WindowsServicesWorker → psutil + sc query toutes les 3s
  - EventsDBWorker     → lit events.db toutes les 5s
"""
from __future__ import annotations
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

try:
    from PySide6.QtCore import QThread, Signal, QObject, QTimer
    HAS_QT = True
except ImportError:
    class QThread: pass
    class QObject: pass
    def Signal(*a): return None
    HAS_QT = False

HUB_URL = "http://127.0.0.1:8766"


# ── MMap Poller (primaire, ultra-rapide) ──────────────────────────────────────

class MMapPollerWorker(QThread):
    """
    Lit live_bridge.map toutes les 100ms.
    Remplace le broadcast UDP — aucun réseau, aucun socket.
    Émet les données swarm + LLM en temps réel.
    """
    swarm_updated    = Signal(dict)    # état swarm
    llm_updated      = Signal(dict)    # {llm_id: {state, vram_mb, tokens_s}}
    agents_updated   = Signal(dict)    # {agent_id: {state, ring, tokens}}
    heartbeat_sent   = Signal(float)   # timestamp du dernier beat
    watchdog_alert   = Signal(bool)    # True si watchdog détecte un freeze

    def __init__(self, interval_ms: int = 100, parent=None):
        super().__init__(parent)
        self.interval_ms = interval_ms
        self._running    = True
        self._bridge     = None
        self._last_seq   = -1

    def _get_bridge(self):
        if self._bridge is None:
            try:
                from live_bridge import bridge
                self._bridge = bridge
            except Exception:
                pass
        return self._bridge

    def run(self):
        while self._running:
            br = self._get_bridge()
            if br:
                try:
                    snap = br.snapshot().get("json", {})
                    seq  = snap.get("swarm.seq", 0)

                    # Swarm state — émettre seulement si changé
                    if seq != self._last_seq:
                        self._last_seq = seq
                        self.swarm_updated.emit({
                            "state":        snap.get("swarm.state",        "IDLE"),
                            "active_agent": snap.get("swarm.active_agent", ""),
                            "seq":          seq,
                            "ts":           snap.get("swarm.ts",           0.0),
                        })

                    # LLM states
                    llm_data = {}
                    for k, v in snap.items():
                        if k.startswith("llm."):
                            parts = k.split(".", 2)
                            if len(parts) == 3:
                                lid, field = parts[1], parts[2]
                                if lid not in llm_data:
                                    llm_data[lid] = {}
                                llm_data[lid][field] = v
                    if llm_data:
                        self.llm_updated.emit(llm_data)

                    # Agents thinking (conscience émanente)
                    agents_data = {}
                    for k, v in snap.items():
                        if k.startswith("agent."):
                            parts = k.split(".", 2)
                            if len(parts) == 3:
                                aid, field = parts[1], parts[2]
                                if aid not in agents_data:
                                    agents_data[aid] = {}
                                agents_data[aid][field] = v
                    if agents_data:
                        self.agents_updated.emit(agents_data)

                    # Watchdog alert
                    alert = snap.get("watchdog.alert", False)
                    if alert:
                        self.watchdog_alert.emit(True)

                    # Heartbeat GUI
                    br.json_set("gui.heartbeat", time.time())
                    br.json_set("gui.pid",       os.getpid())

                except Exception:
                    pass
            self.msleep(self.interval_ms)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(2000)


# ── Hub Poller (secondaire, données étendues) ─────────────────────────────────

class HubPollerWorker(QThread):
    """Interroge le Hub HTTP toutes les 3s pour les métriques étendues."""
    data_ready  = Signal(dict)
    hub_offline = Signal()

    def __init__(self, interval_ms: int = 3000, parent=None):
        super().__init__(parent)
        self.interval_ms = interval_ms
        self._running    = True

    def run(self):
        while self._running:
            result = {}
            ok     = False
            for ep, key in [("/health","health"), ("/metrics","metrics"),
                             ("/swarm","swarm"),   ("/team","team")]:
                try:
                    with urllib.request.urlopen(HUB_URL + ep, timeout=2) as r:
                        result[key] = json.loads(r.read().decode())
                    ok = True
                except Exception:
                    result[key] = {}
            if ok:
                self.data_ready.emit(result)
            else:
                self.hub_offline.emit()
            self.msleep(self.interval_ms)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(2000)


# ── Events DB reader ──────────────────────────────────────────────────────────

class EventsDBWorker(QThread):
    """Lit les N derniers events depuis events.db toutes les 5s."""
    events_ready = Signal(list)

    def __init__(self, n: int = 100, interval_ms: int = 5000, parent=None):
        super().__init__(parent)
        self.n            = n
        self.interval_ms  = interval_ms
        self._running     = True
        self._last_max_seq = -1   # n'émet que si nouveaux events

    def run(self):
        while self._running:
            try:
                db   = ROOT / "sandbox" / "events.db"
                conn = sqlite3.connect(str(db), timeout=3)
                max_seq = conn.execute(
                    "SELECT COALESCE(MAX(sequence_id), -1) FROM event_log"
                ).fetchone()[0]
                if max_seq != self._last_max_seq:
                    self._last_max_seq = max_seq
                    rows = conn.execute(
                        "SELECT timecode,sequence_id,agent_id,event_type,target,status "
                        "FROM event_log ORDER BY sequence_id DESC LIMIT ?", (self.n,)
                    ).fetchall()
                    events = [{"ts":r[0],"seq":r[1],"agent":r[2],
                               "type":r[3],"target":r[4],"status":r[5]}
                              for r in rows]
                    self.events_ready.emit(events)
                conn.close()
            except Exception:
                pass
            self.msleep(self.interval_ms)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(2000)


# ── Windows Services Monitor ──────────────────────────────────────────────────

class WindowsServicesWorker(QThread):
    """Surveille services NSSM + PIDs Python + VRAM toutes les 3s."""
    services_ready = Signal(dict)

    SERVICES = ["NokidoHub", "NokidoStreamlit", "LaForgeMCP"]

    def __init__(self, interval_ms: int = 3000, parent=None):
        super().__init__(parent)
        self.interval_ms = interval_ms
        self._running    = True

    def run(self):
        while self._running:
            result = {
                "services":  {},
                "processes": [],
                "memory":    {},
                "vram":      {},
            }
            # Services NSSM
            for svc in self.SERVICES:
                try:
                    r = subprocess.run(["sc","query",svc],
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3)
                    state = next((l.strip() for l in r.stdout.splitlines()
                                  if "STATE" in l), "UNKNOWN")
                    m     = re.search(r"PID\s*:\s*(\d+)", r.stdout)
                    pid   = int(m.group(1)) if m else 0
                    result["services"][svc] = {
                        "running": "RUNNING" in state,
                        "state":   state,
                        "pid":     pid,
                    }
                except Exception as e:
                    result["services"][svc] = {"running": False, "error": str(e)[:40]}

            # Processus Python actifs
            try:
                import psutil
                python_procs = []
                for proc in psutil.process_iter(
                        ["pid","name","cmdline","memory_info","cpu_percent"]):
                    if proc.info["name"] in ("python.exe","pythonw.exe"):
                        cmd = " ".join(proc.info["cmdline"] or [])[:80]
                        mem = (proc.info["memory_info"].rss // 1024 // 1024
                               if proc.info["memory_info"] else 0)
                        python_procs.append({
                            "pid": proc.info["pid"],
                            "cmd": cmd,
                            "mb":  mem,
                            "cpu": proc.info["cpu_percent"],
                        })
                result["processes"] = python_procs[:20]
                # RAM
                vm = psutil.virtual_memory()
                result["memory"] = {
                    "total_gb": round(vm.total   / 1024**3, 1),
                    "avail_gb": round(vm.available / 1024**3, 1),
                    "pct":      vm.percent,
                }
            except Exception:
                pass

            # VRAM via wmi
            try:
                import wmi
                w = wmi.WMI()
                for gpu in w.Win32_VideoController():
                    vram_mb = int(gpu.AdapterRAM or 0) // 1024 // 1024
                    result["vram"][gpu.Name] = {
                        "vram_mb": vram_mb,
                        "name":    gpu.Name,
                    }
            except Exception:
                pass

            self.services_ready.emit(result)
            self.msleep(self.interval_ms)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(2000)


# ── Service Controller ────────────────────────────────────────────────────────

class ServiceController(QObject):
    """Contrôle les services NSSM et processus — thread-safe via signaux."""
    action_done = Signal(str, bool, str)   # name, success, message

    def start_service(self, name: str):
        self._sc("start", name)

    def stop_service(self, name: str):
        self._sc("stop", name)

    def restart_service(self, name: str):
        self._sc("stop", name)
        self.msleep(1000) if hasattr(self, "msleep") else time.sleep(1)
        self._sc("start", name)

    def kill_pid(self, pid: int):
        try:
            import ctypes
            k32    = ctypes.windll.kernel32
            handle = k32.OpenProcess(0x0001, False, pid)
            if handle:
                ok = k32.TerminateProcess(handle, 1)
                k32.CloseHandle(handle)
                self.action_done.emit(f"PID {pid}", bool(ok),
                                      "TerminateProcess OK" if ok else "FAIL")
            else:
                # Fallback taskkill
                r = subprocess.run(["taskkill","/F","/PID",str(pid, encoding="utf-8", errors="replace")],
                                   capture_output=True, timeout=5)
                self.action_done.emit(f"PID {pid}", r.returncode == 0,
                                      r.stdout.strip()[:60])
        except Exception as e:
            self.action_done.emit(f"PID {pid}", False, str(e)[:60])

    def kill_switch(self):
        """Kill Switch — tue tous les process Nokido sauf self."""
        try:
            import psutil
            self_pid = os.getpid()
            killed   = []
            for proc in psutil.process_iter(["pid","name","cmdline"]):
                if proc.info["name"] in ("python.exe","pythonw.exe"):
                    cmd = " ".join(proc.info["cmdline"] or [])
                    if "Nokido" in cmd and proc.info["pid"] != self_pid:
                        proc.kill()
                        killed.append(proc.info["pid"])
            # Libérer VRAM — tuer Ollama si actif
            for proc in psutil.process_iter(["pid","name"]):
                if "ollama" in proc.info["name"].lower():
                    proc.kill()
                    killed.append(proc.info["pid"])
            self.action_done.emit(
                "KillSwitch", True,
                f"{len(killed)} process killed: {killed[:5]}"
            )
        except Exception as e:
            self.action_done.emit("KillSwitch", False, str(e)[:80])

    def read_log_tail(self, service_name: str, n: int = 60) -> str:
        log_path = ROOT / "logs" / f"{service_name.lower()}_service.log"
        if not log_path.exists():
            return f"[Log introuvable : {log_path}]"
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.splitlines()[-n:])
        except Exception as e:
            return f"[Erreur : {e}]"

    def _sc(self, action: str, name: str):
        try:
            r = subprocess.run(["sc",action,name],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            ok  = r.returncode == 0
            msg = (r.stdout or r.stderr).strip()[:80]
            self.action_done.emit(name, ok, msg)
        except Exception as e:
            self.action_done.emit(name, False, str(e)[:60])


# ── Watchdog Launcher ─────────────────────────────────────────────────────────

def spawn_watchdog(auto_restart: bool = True) -> int:
    """
    Lance le watchdog en process DETACHED indépendant.
    Retourne son PID. Zéro dépendance Qt.
    """
    try:
        watchdog_script = ROOT / "forge_desktop" / "watchdog.py"
        args = [sys.executable, str(watchdog_script)]
        if not auto_restart:
            args.append("--no-restart")
        proc = subprocess.Popen(
            args,
            creationflags=(
                subprocess.DETACHED_PROCESS |
                subprocess.CREATE_NEW_PROCESS_GROUP
            ),
            close_fds=True,
            stdout=open(ROOT/"logs"/"watchdog.log","a"),
            stderr=subprocess.STDOUT,
        )
        return proc.pid
    except Exception as e:
        return 0
