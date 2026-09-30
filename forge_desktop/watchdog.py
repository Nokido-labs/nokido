"""
forge_desktop/watchdog.py
==========================
Watchdog Forge-Sync OS — Process Python INDÉPENDANT.
Lancé en DETACHED par main.py. Survit au crash de la GUI.

Rôle :
  1. Surveille gui.heartbeat dans live_bridge mmap
  2. Si delta > FREEZE_THRESHOLD → force TerminateProcess sur gui.pid
  3. Si delta > ALERT_THRESHOLD  → écrit watchdog.alert=True dans mmap
  4. Optionnel : relance la GUI après kill (AUTO_RESTART)

Dépendances : AUCUNE externe. Seulement stdlib + ctypes + live_bridge.
Mémoire : < 8 MB RSS.
CPU idle : 0% (sleep 2s en boucle).

Usage :
    python forge_desktop/watchdog.py [--no-restart]
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes
import os
import sys
import time
import json
import mmap
import struct
import argparse
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP  = ROOT / "app"
sys.path.insert(0, str(APP))

# ── Configuration ─────────────────────────────────────────────────────────────
POLL_INTERVAL    = 2.0    # secondes entre chaque check
ALERT_THRESHOLD  = 5.0    # secondes avant alerte
FREEZE_THRESHOLD = 10.0   # secondes avant kill forcé
AUTO_RESTART     = True   # relancer la GUI après kill

MAP_PATH = ROOT / "sandbox" / "live_bridge.map"
MAP_SIZE = 262144   # 256 KB — doit correspondre à live_bridge._MAP_SIZE

# ── Logging minimal ────────────────────────────────────────────────────────────
LOG_PATH = ROOT / "logs" / "watchdog.log"
LOG_PATH.parent.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("Watchdog")


# ── MMap direct (sans importer live_bridge — zéro import lourd) ───────────────

class _RawMMap:
    """
    Accès direct au fichier live_bridge.map.
    Lit/écrit le JSON zone sans importer live_bridge.
    Zéro dépendance — survivra à n'importe quel crash Python.
    """
    _HDR_SIZE  = 64
    _N_SLOTS   = 128
    _SLOT_SIZE = 128
    _JSON_OFF  = _HDR_SIZE + _N_SLOTS * _SLOT_SIZE   # 16448
    _JSON_SIZE = MAP_SIZE - _JSON_OFF

    def __init__(self):
        self._mm   = None
        self._fd   = None
        self._data = {}
        self._open()

    def _open(self):
        if not MAP_PATH.exists():
            log.warning("live_bridge.map introuvable — watchdog en mode dégradé")
            return
        try:
            self._fd = open(MAP_PATH, "r+b")
            self._mm = mmap.mmap(self._fd.fileno(), MAP_SIZE)
            log.info("MMap ouvert : %s", MAP_PATH)
        except Exception as e:
            log.error("MMap open failed: %s", e)

    def _read_json(self) -> dict:
        if not self._mm:
            return {}
        try:
            self._mm.seek(self._JSON_OFF)
            raw = self._mm.read(self._JSON_SIZE)
            # Trouver la fin du JSON (null byte)
            end = raw.find(b"\x00")
            if end == 0:
                return {}
            text = raw[:end].decode("utf-8", errors="replace")
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_json(self, data: dict) -> bool:
        if not self._mm:
            return False
        try:
            text  = json.dumps(data, ensure_ascii=False)
            bdata = text.encode("utf-8")
            if len(bdata) >= self._JSON_SIZE:
                return False
            padded = bdata + b"\x00" * (self._JSON_SIZE - len(bdata))
            self._mm.seek(self._JSON_OFF)
            self._mm.write(padded)
            self._mm.flush()
            return True
        except Exception as e:
            log.error("MMap write failed: %s", e)
            return False

    def get(self, key: str, default=None):
        data = self._read_json()
        parts = key.split(".")
        val = data
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p, default)
            else:
                return default
        return val

    def set(self, key: str, value) -> bool:
        data = self._read_json()
        # Navigation clés dotted ex: "watchdog.last_beat"
        parts = key.split(".")
        node = data
        for p in parts[:-1]:
            if not isinstance(node.get(p), dict):
                node[p] = {}
            node = node[p]
        node[parts[-1]] = value
        return self._write_json(data)

    def close(self):
        if self._mm:
            try: self._mm.close()
            except: pass
        if self._fd:
            try: self._fd.close()
            except: pass


# ── Windows API directs ────────────────────────────────────────────────────────

k32 = ctypes.windll.kernel32

PROCESS_TERMINATE    = 0x0001
PROCESS_QUERY_INFO   = 0x0400
SYNCHRONIZE          = 0x00100000

def _open_process(pid: int) -> ctypes.wintypes.HANDLE:
    return k32.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_INFO, False, pid)

def _is_running(pid: int) -> bool:
    """Vérifie si un PID est actif — sans lever d'exception."""
    if pid <= 0:
        return False
    try:
        handle = _open_process(pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong(0)
        k32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        k32.CloseHandle(handle)
        return exit_code.value == 259   # STILL_ACTIVE
    except Exception:
        return False

def _kill_pid(pid: int) -> bool:
    """Force kill via TerminateProcess — plus fiable que taskkill."""
    if pid <= 0:
        return False
    try:
        handle = _open_process(pid)
        if not handle:
            # Fallback taskkill
            import subprocess
            r = subprocess.run(["taskkill", "/F", "/PID", str(pid, encoding="utf-8")],
                               capture_output=True, timeout=5)
            return r.returncode == 0
        result = k32.TerminateProcess(handle, 1)
        k32.CloseHandle(handle)
        log.warning("TerminateProcess PID=%d → %s", pid, "OK" if result else "FAIL")
        return bool(result)
    except Exception as e:
        log.error("Kill PID %d failed: %s", pid, e)
        return False

def _spawn_gui() -> int:
    """Relance la GUI Forge-Sync OS — DETACHED."""
    try:
        import subprocess
        python = sys.executable
        main   = str(ROOT / "forge_desktop" / "main.py")
        proc   = subprocess.Popen(
            [python, main],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        log.info("GUI relancée PID=%d", proc.pid)
        return proc.pid
    except Exception as e:
        log.error("Spawn GUI failed: %s", e)
        return 0


# ── Watchdog loop ──────────────────────────────────────────────────────────────

class Watchdog:

    def __init__(self, auto_restart: bool = AUTO_RESTART):
        self._mm           = _RawMMap()
        self._auto_restart = auto_restart
        self._my_pid       = os.getpid()
        self._kills: list  = []
        self._running      = True

    def start(self):
        log.info("Watchdog démarré PID=%d", self._my_pid)
        # Enregistrer ce watchdog dans mmap
        self._mm.set("watchdog.pid",       self._my_pid)
        self._mm.set("watchdog.last_beat", time.time())
        self._mm.set("watchdog.alert",     False)
        self._mm.set("watchdog.kills",     [])

        while self._running:
            try:
                self._tick()
            except Exception as e:
                log.error("Watchdog tick error: %s", e)
            time.sleep(POLL_INTERVAL)

    def _tick(self):
        now = time.time()

        # Mettre à jour le heartbeat watchdog
        self._mm.set("watchdog.last_beat", now)

        # Lire le heartbeat GUI
        gui_hb  = self._mm.get("watchdog.last_beat", 0.0)
        gui_hb  = float(self._mm.get("gui.heartbeat", 0.0) or 0.0)
        gui_pid = int(self._mm.get("gui.pid", 0) or 0)

        if gui_hb <= 0 or gui_pid <= 0:
            # GUI pas encore démarrée — ignorer
            return

        # Si la GUI est terminée proprement (pid mort, pas de freeze), quitter
        if gui_pid > 0 and not _is_running(gui_pid):
            log.info("GUI PID=%d terminée proprement — watchdog s'arrête", gui_pid)
            self._running = False
            return

        delta = now - gui_hb

        if delta > FREEZE_THRESHOLD:
            # GUI frozen — KILL
            log.critical("GUI FROZEN %.1fs — kill PID=%d", delta, gui_pid)
            self._mm.set("watchdog.alert", True)

            if _is_running(gui_pid):
                killed = _kill_pid(gui_pid)
                if killed:
                    self._kills.append({"pid": gui_pid, "ts": now, "reason": "freeze"})
                    self._mm.set("watchdog.kills", self._kills[-10:])
                    self._mm.set("gui.state",     "KILLED")
                    self._mm.set("gui.heartbeat", 0.0)
                    log.warning("GUI PID=%d killed", gui_pid)

                    # Auto-restart
                    if self._auto_restart:
                        time.sleep(2)
                        new_pid = _spawn_gui()
                        if new_pid:
                            log.info("GUI restarted PID=%d", new_pid)

        elif delta > ALERT_THRESHOLD:
            # GUI lente — alerte sans kill
            if not self._mm.get("watchdog.alert", False):
                log.warning("GUI SLOW %.1fs — alerte (seuil kill=%.0fs)",
                            delta, FREEZE_THRESHOLD)
                self._mm.set("watchdog.alert", True)
        else:
            # GUI OK — clear alerte
            if self._mm.get("watchdog.alert", False):
                self._mm.set("watchdog.alert", False)

    def stop(self):
        self._running = False
        self._mm.set("watchdog.pid", 0)
        self._mm.close()
        log.info("Watchdog arrêté")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Forge-Sync Watchdog")
    parser.add_argument("--no-restart", action="store_true",
                        help="Ne pas relancer la GUI après kill")
    args = parser.parse_args()

    wd = Watchdog(auto_restart=not args.no_restart)
    try:
        wd.start()
    except KeyboardInterrupt:
        wd.stop()


if __name__ == "__main__":
    main()
