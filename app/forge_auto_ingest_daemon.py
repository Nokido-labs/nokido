"""
app/forge_auto_ingest_daemon.py — Periodic Auto-Ingest
======================================================
Démon qui surveille data/rag_files/ et ingère les nouveaux fichiers toutes les 5 minutes.
Utilise forge_hot_ingest.py.
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

# Setup path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_hot_ingest import get_watcher


def run_daemon():
    print("[DAEMON] Auto-ingest started.")
    watcher = get_watcher()
    # On force un premier scan
    watcher._scan()

    while True:
        try:
            print(f"[DAEMON] Scan cycle at {time.strftime('%H:%M:%S')}...")
            watcher._scan()
            time.sleep(300)  # 5 minutes
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[DAEMON] Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    run_daemon()
