#!/usr/bin/env python3
"""
gemini_launcher.py — Gemini CLI interactif + relay hub en subprocess.
Usage : python gemini_launcher.py [args...]
        python gemini_launcher.py --no-relay
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path(__import__("os").path.expanduser(r"~"))
OAUTH = HOME / ".gemini" / "oauth_creds.json"
BACKUP = HOME / ".gemini" / "oauth_creds.backup.json"
NODE = r"C:\Program Files\nodejs\node.exe"
GEMINI_JS = __import__("os").path.expanduser(r"~\AppData\Roaming\npm\node_modules\@google\gemini-cli\bundle\gemini.js")
ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

NO_RELAY = "--no-relay" in sys.argv
args = [a for a in sys.argv[1:] if a != "--no-relay"]

env = {**os.environ, "GEMINI_FORCE_FILE_STORAGE": "1", "USERPROFILE": str(HOME), "HOME": str(HOME)}

# 1. Backup oauth
if OAUTH.exists():
    shutil.copy(OAUTH, BACKUP)

# 2. Relay hub en subprocess séparé (stdout/stderr vers fichier log)
relay_proc = None
if not NO_RELAY:
    relay = ROOT / "tools" / "gemini_hub_relay.py"
    if relay.exists():
        log_file = open(str(ROOT / "sandbox" / "gemini_hub_relay.log"), "a", encoding="utf-8")
        relay_proc = subprocess.Popen(
            [PYTHON, str(relay), "--interval", "15"],
            stdout=log_file,
            stderr=log_file,
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(
            f"[launcher] Hub relay PID={relay_proc.pid} (logs: sandbox/gemini_hub_relay.log)",
            flush=True,
        )
    else:
        print("[launcher] gemini_hub_relay.py introuvable — relay désactivé", flush=True)

# 3. Gemini CLI interactif au premier plan
print("[launcher] Gemini CLI démarré", flush=True)
proc = subprocess.run([NODE, GEMINI_JS, "--approval-mode=yolo"] + args, env=env)

# 4. Arrêter le relay quand Gemini quitte
if relay_proc:
    relay_proc.terminate()
    print("[launcher] Relay arrêté", flush=True)

# 5. Restaurer oauth si supprimé
if not OAUTH.exists() and BACKUP.exists():
    shutil.copy(BACKUP, OAUTH)
    print("[launcher] oauth_creds.json restauré", flush=True)

sys.exit(proc.returncode)
