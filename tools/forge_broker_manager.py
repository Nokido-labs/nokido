"""
forge_broker_manager.py — Nokido v18.5
Orchestrateur des brokers — route les messages vers le bon agent selon l intention.
Permet de lancer tous les brokers en parallele ou de les router dynamiquement.

Usage:
    python tools/forge_broker_manager.py --all       # Lance tous les brokers
    python tools/forge_broker_manager.py --broker gemini
    python tools/forge_broker_manager.py --status
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
PYTHON = sys.executable

BROKERS = {
    "gemini": ("forge_broker_gemini.py", "agt_gemini", "Raisonnement + Long ctx"),
    "fast": ("forge_broker_fast.py", "agt_groq", "Speed <500ms, scoring"),
    "deepseek": ("forge_broker_deepseek.py", "agt_deepseek", "Code + Reasoning OSS"),
    "mistral": ("forge_broker_mistral.py", "agt_mistral", "EU/RGPD, function calling"),
    "local": ("forge_broker_local.py", "agt_local", "Ollama offline, zero cloud"),
}


def start_broker(name: str, detach: bool = True) -> int:
    entry = BROKERS.get(name)
    if not entry:
        print(f"Broker inconnu: {name}")
        return -1
    script, agent_id, desc = entry
    script_path = TOOLS / script
    log_path = ROOT / "sandbox" / f"{agent_id}.log"
    pid_path = ROOT / "sandbox" / f"{agent_id}.pid"

    # Tuer l ancien si present
    if pid_path.exists():
        old_pid = pid_path.read_text().strip()
        subprocess.run(["taskkill", "/F", "/PID", old_pid], capture_output=True)
        time.sleep(0.5)

    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "LAFORGE_ALLOW_SECRETS_READ": "1",
    }
    log_file = open(log_path, "w", encoding="utf-8")

    if detach:
        p = subprocess.Popen(
            [PYTHON, str(script_path)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            env=env,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        p = subprocess.Popen([PYTHON, str(script_path)], cwd=str(ROOT), env=env)

    pid_path.write_text(str(p.pid))
    print(f"[{name}] {agent_id} PID={p.pid} → {log_path.name}")
    return p.pid


def status() -> None:
    print("\n=== STATUS BROKERS ===")
    for name, (script, agent_id, desc) in BROKERS.items():
        pid_path = ROOT / "sandbox" / f"{agent_id}.pid"
        log_path = ROOT / "sandbox" / f"{agent_id}.log"
        if pid_path.exists():
            pid = pid_path.read_text().strip()
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                capture_output=True,
                text=True,
                errors="replace",
            )
            up = "python" in r.stdout.lower()
            last = ""
            if log_path.exists():
                lines = log_path.read_text(errors="replace").split("\n")
                last = next((l for l in reversed(lines) if l.strip()), "")[-60:]
            print(f"  {'UP' if up else 'DOWN':4s} [{name:8s}] {agent_id:15s} PID={pid:6s} | {last}")
        else:
            print(f"  ---- [{name:8s}] {agent_id:15s} non démarré")
    print()


def main():
    ap = argparse.ArgumentParser(description="Nokido Broker Manager")
    ap.add_argument("--all", action="store_true", help="Lancer tous les brokers")
    ap.add_argument("--broker", help="Lancer un broker specifique")
    ap.add_argument("--stop", help="Arreter un broker")
    ap.add_argument("--status", action="store_true", help="Status tous les brokers")
    args = ap.parse_args()

    if args.status:
        status()
        return
    if args.stop:
        pid_path = ROOT / "sandbox" / f"agt_{args.stop}.pid"
        if pid_path.exists():
            pid = pid_path.read_text().strip()
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            print(f"Stopped agt_{args.stop} PID={pid}")
        return
    if args.broker:
        start_broker(args.broker, detach=False)
        return
    if args.all:
        print("Lancement de tous les brokers...")
        for name in BROKERS:
            start_broker(name)
            time.sleep(0.5)
        time.sleep(2)
        status()
        return
    ap.print_help()


if __name__ == "__main__":
    main()
