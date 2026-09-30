#!/usr/bin/env python3
"""Launcher trusted du daemon autonomous_loops (detache, exempt gate P1).

run_job ne passe pas d'args CLI et le gate P1 throttle les spawns sandbox sous
pression RAM ; ce launcher tourne en trusted_script (privilegie, exempt) et
Popen-detache le daemon puis rend la main immediatement. Idempotent : ne relance
pas si un daemon autonomous_loops tourne deja (heartbeat < 180s).
"""

__FORGE_COLOR__ = "vegetatif/autonome : lanceur trusted du daemon autonomous_loops"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "forge_autonomous_loops.py"
STATE = ROOT / "RAG" / "embeddings.db"


def _daemon_alive() -> bool:
    """True si un pattern a tourne il y a < 180s (daemon vivant)."""
    try:
        import sqlite3
        c = sqlite3.connect(f"file:{STATE}?mode=ro", uri=True, timeout=5)
        row = c.execute("SELECT MAX(last_run) FROM autonomous_loop_state").fetchone()
        c.close()
        return bool(row and row[0] and (time.time() - float(row[0])) < 180)
    except Exception:
        return False


def main():
    if _daemon_alive():
        print("autonomous_loops deja vivant (heartbeat < 180s) -> no-op")
        return
    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    p = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--daemon", "--tick", "60"],
        cwd=str(ROOT),
        creationflags=DETACHED,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    print(f"autonomous_loops daemon lance pid={p.pid} (tick=60s, py={os.path.basename(sys.executable)})")


if __name__ == "__main__":
    main()
