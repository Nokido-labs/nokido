"""
forge_desktop/main.py — Forge-Sync OS
Entry point. Lance le watchdog, initialise la MMap, démarre Qt.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

DETACHED_PROCESS = 0x00000008


def _kill_old_watchdogs():
    """Tue les instances watchdog.py déjà en cours avant d'en spawner une nouvelle."""
    try:
        r = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe' and CommandLine like '%watchdog.py%'",
             "get", "ProcessId", "/format:csv"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=5
        )
        for line in r.stdout.splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 2 and parts[-1].strip().isdigit():
                pid = int(parts[-1].strip())
                if pid != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _spawn_watchdog() -> int:
    _kill_old_watchdogs()
    python = sys.executable
    script = ROOT / "forge_desktop" / "watchdog.py"
    proc   = subprocess.Popen(
        [python, str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS,
    )
    return proc.pid


def main():
    # 1. Charger Nokido.env
    env_path = ROOT / "Nokido.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

    # 2. Lancer le watchdog DETACHED
    wd_pid = _spawn_watchdog()

    # 3. Qt App
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon, QFontDatabase

    app = QApplication(sys.argv)
    app.setApplicationName("Forge-Sync OS")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")

    # Répertoire de fonts locales (optionnel — supprime le warning Qt)
    fonts_dir = ROOT / "forge_desktop" / "fonts"
    if fonts_dir.exists():
        QFontDatabase.addApplicationFontFromData  # no-op si dossier vide
    # Fallback : forcer Segoe UI (disponible sur Windows)
    from PySide6.QtGui import QFont
    app.setFont(QFont("Segoe UI", 9))

    # 4. Fenêtre principale
    from forge_desktop.views.main_window import MainWindow
    window = MainWindow(watchdog_pid=wd_pid)
    window.show()

    # 5. AutoPilot Ring 5.5 — thread daemon, non-bloquant
    # Lit MMap, appelle MCP si seuil franchi (drift/vram/heartbeat)
    try:
        from forge_auto_pilot import start_autopilot
        start_autopilot(blocking=False)
    except Exception as _ap_err:
        print(f"[AutoPilot] non démarré: {_ap_err}")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
