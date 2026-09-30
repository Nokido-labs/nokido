#!/usr/bin/env python3
"""
gemini_hub_relay.py v3.0 — PTY wrapper OAuth persistant
=========================================================
Gemini CLI tourne en session interactive via PTY (winpty).
OAuth maintenu en vie → pas de quota/auth cassé.
Poll hub → écrit sur stdin PTY → lit stdout PTY → notifie hub.

Usage: python tools/gemini_hub_relay.py [--interval 15]
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(__import__("os").path.expanduser(r"~"))
NODE = r"C:\Program Files\nodejs\node.exe"
GEMINI_JS = __import__("os").path.expanduser(r"~\AppData\Roaming\npm\node_modules\@google\gemini-cli\bundle\gemini.js")
HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766/mcp")
# SECURITY 2026-05-02 : hardcoded fallback token removed.
TOKEN = os.environ.get("FORGE_MCP_TOKEN", "")
if not TOKEN:
    print(
        "[gemini_hub_relay] WARN: FORGE_MCP_TOKEN env not set. Hub auth will fail.", file=sys.stderr
    )
POLL_INTERVAL = int(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else 15
LOG_PATH = ROOT / "sandbox" / "gemini_hub_relay.log"

_running = True
_pty = None  # winpty.PtyProcess
_out_queue = queue.Queue()  # lignes lues depuis le PTY
_ready = threading.Event()  # PTY prêt à recevoir


def log(level: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{level:4}] {msg}"
    enc = sys.stdout.encoding or "utf-8"
    print(line.encode(enc, errors="replace").decode(enc), flush=True)
    try:
        with open(str(LOG_PATH), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def hub_call(params: dict) -> dict:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    ).encode()
    req = urllib.request.Request(
        HUB_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
            "X-Agent-Name": "GEMINI_RELAY",
        },
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=8).read())


def hub_poll() -> str | None:
    try:
        r = hub_call({"name": "hub", "arguments": {"action": "poll"}})
        t = r["result"]["content"][0]["text"]
        return None if t == "Aucune notification." else t
    except Exception as e:
        log("WARN", f"poll: {e}")
        return None


def hub_notify(msg: str):
    try:
        hub_call(
            {
                "name": "hub",
                "arguments": {"action": "notify", "message": f"[GEMINI_RELAY] {msg[:600]}"},
            }
        )
    except Exception as e:
        log("WARN", f"notify: {e}")


# ── PTY Reader thread ─────────────────────────────────────────────────────────
def _pty_reader():
    """Lit en continu le PTY et pousse dans _out_queue."""
    global _pty, _running
    buf = ""
    while _running:
        if _pty is None:
            time.sleep(0.5)
            continue
        try:
            chunk = _pty.read(4096)
            if not chunk:
                time.sleep(0.1)
                continue
            # Nettoyer codes ANSI
            clean = re.sub(r"\x1b\[[0-9;]*[mABCDEFGHJKSTfhilmnprsu]", "", chunk)
            clean = re.sub(r"\x1b\[\?[0-9;]*[hl]", "", clean)
            clean = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", clean)
            buf += clean
            # Détecter prompt prêt ("> " en début de ligne)
            if re.search(r"^[\s>]*>\s*$", buf, re.MULTILINE):
                _ready.set()
            # Pousser les lignes complètes
            lines = buf.split("\n")
            for line in lines[:-1]:
                line = line.strip()
                if line and not line.startswith(">"):
                    _out_queue.put(line)
                    log("GEM", line[:100])
            buf = lines[-1]
        except Exception as e:
            if _running:
                log("WARN", f"PTY read: {e}")
            time.sleep(1)


# ── Lancer Gemini CLI via PTY ─────────────────────────────────────────────────
def start_pty():
    global _pty, _running
    import winpty

    oauth = HOME / ".gemini" / "oauth_creds.json"
    backup = HOME / ".gemini" / "oauth_creds.backup.json"
    if oauth.exists():
        shutil.copy(oauth, backup)

    env = {
        **os.environ,
        "GEMINI_FORCE_FILE_STORAGE": "1",
        "USERPROFILE": str(HOME),
        "HOME": str(HOME),
        "NO_COLOR": "1",
        "TERM": "xterm-256color",
    }

    agy_path = r"%USERPROFILE%\AppData\Local\agy\bin\agy.exe"
    if os.path.exists(agy_path):
        cmd = rf'{agy_path} --dangerously-skip-permissions'
    elif os.path.exists(NODE):
        cmd = f'"{NODE}" "{GEMINI_JS}" --approval-mode=yolo'
    else:
        cmd = "agy --dangerously-skip-permissions"
    log("INFO", f"PTY launch: {cmd[:80]}")

    _pty = winpty.PtyProcess.spawn(cmd, env=env, cwd=str(ROOT.parent))
    log("INFO", f"PTY PID={_pty.pid} (CWD={ROOT.parent})")

    # Attendre que le prompt soit prêt (max 30s)
    _ready.clear()
    if _ready.wait(timeout=30):
        log("INFO", "PTY prêt — Gemini CLI interactif démarré")
    else:
        log("WARN", "PTY timeout attente prompt — on continue quand même")


def send_to_pty(text: str) -> str:
    """Envoie une commande au PTY et attend la réponse (max 60s)."""
    global _pty
    if _pty is None or not _pty.isalive():
        log("WARN", "PTY mort — relance")
        start_pty()
        time.sleep(3)

    # Vider la queue avant d'envoyer
    while not _out_queue.empty():
        _out_queue.get_nowait()

    _ready.clear()
    _pty.write(text + "\n")
    log(" ->", text[:80])

    # Attendre réponse (prompt suivant = réponse terminée)
    collected = []
    deadline = time.time() + 60
    while time.time() < deadline:
        _ready.wait(timeout=2)
        # Drain queue
        while not _out_queue.empty():
            collected.append(_out_queue.get_nowait())
        if _ready.is_set():
            break

    result = "\n".join(collected).strip()
    return result or "(pas de réponse)"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global _running

    log("INFO", f"=== gemini_hub_relay v3.0 PTY | poll={POLL_INTERVAL}s ===")

    # Démarrer PTY reader thread
    t_reader = threading.Thread(target=_pty_reader, daemon=True, name="pty_reader")
    t_reader.start()

    # Lancer Gemini CLI
    start_pty()

    # Whoami initial
    time.sleep(5)
    out = send_to_pty("hub action=whoami")
    hub_notify(f"BOOT whoami: {out[:400]}")

    log("INFO", f"Poll loop active — interval={POLL_INTERVAL}s")
    while _running:
        time.sleep(POLL_INTERVAL)
        notif = hub_poll()
        if not notif:
            log("INFO", "Aucune notification")
            continue
        log("HUB", f"Message recu: {notif[:80]}")
        # Extraire commandes ou envoyer le message brut
        lines = notif.splitlines()
        cmds = [
            l.strip()
            for l in lines
            if l.strip().startswith(("hub ", "run ", "query ", "read ", "write "))
        ]
        prompt = (
            "\n".join(cmds)
            if cmds
            else (
                f"Tu es Gemini agent Nokido. Traite ce message du hub:\n{notif[:500]}\n"
                "Exécute les actions demandées et notifie [GEMINI][DONE] quand terminé."
            )
        )
        out = send_to_pty(prompt)
        if out:
            hub_notify(out[:800])


if __name__ == "__main__":
    main()
