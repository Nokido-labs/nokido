#!/usr/bin/env python3
"""
tools/forge_stream_mutation.py — FORGE_STREAM_MUTATION_V1
==========================================================
Streaming live du ParallelMutationWorker avec :
  - Ring buffer (50 lignes max)
  - Filtre sémantique sur tags [AST:OK] [RESULT:*] [BILAN] etc.
  - Early exit si trop d'échecs consécutifs
  - Poll non-bloquant via mutation_state.json (heartbeat)
  - Réallocation worker si latence > seuil

Usage :
  python tools/forge_stream_mutation.py                  # dry-run
  python tools/forge_stream_mutation.py --real           # mutation réelle
  python tools/forge_stream_mutation.py --poll           # poll état courant
  python tools/forge_stream_mutation.py --workers 4
  python tools/forge_stream_mutation.py --files app/forge_handlers.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = __import__("os").path.expanduser(r"~\miniforge3\python.exe")
STATE = ROOT / "sandbox" / "mutation_state.json"

# Tags sémantiques — seules ces lignes remontent
SEMANTIC_TAGS = [
    "[AST:OK]",
    "[AST:FAIL]",
    "[RESULT:",
    "[BILAN]",
    "[TIMEOUT]",
    "=== Parallel",
    "Fichiers :",
    "[LATENCY",
]

# Emojis par tag
TAG_ICONS = {
    "[AST:OK]": "✅",
    "[AST:FAIL]": "❌",
    "[RESULT:OK]": "✅",
    "[RESULT:KO]": "🚨",
    "[BILAN]": "📊",
    "[TIMEOUT]": "⏱",
}


def poll_state() -> dict:
    """Lit mutation_state.json — non-bloquant."""
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def print_state(state: dict) -> None:
    """Affiche l'état courant du worker."""
    if not state:
        print("  Aucun run en cours (mutation_state.json absent)")
        return
    status = state.get("status", "?")
    ok = state.get("ok_count", 0)
    total = state.get("total", 0)
    done = state.get("done", 0)
    elapsed = state.get("elapsed_ms", 0)
    print(f"  Status : {status}")
    print(f"  Progrès: {done}/{total} traités — {ok} OK")
    if elapsed:
        print(f"  Durée  : {elapsed}ms")
    last = state.get("last_result")
    if last:
        icon = "✅" if last["status"] == "OK" else "🚨"
        print(f"  Dernier: {icon} {last['target']} | {last['agent']} | {last['elapsed']}ms")


def stream_worker(
    dry_run: bool = True,
    workers: int = 2,
    files: list[str] | None = None,
    max_consecutive_fails: int = 4,
    latency_warn_ms: int = 30000,
) -> dict:
    """
    Lance ParallelMutationWorker en mode streaming.
    Ring buffer 50 lignes, filtre sémantique, early exit.
    """
    cmd = [PYTHON, "-u", "ParallelMutationWorker.py", "--workers", str(workers)]
    if dry_run:
        cmd.append("--dry-run")
    if files:
        cmd += ["--files"] + files

    print("\n🔀 FORGE_STREAM_MUTATION_V1")
    print(f"   dry_run={dry_run} | workers={workers} | early_exit@{max_consecutive_fails} fails")
    print(f"   cmd: {' '.join(cmd[1:4])}...\n")

    tail = deque(maxlen=50)  # ring buffer
    ok_count = 0
    fail_count = 0
    consec_fail = 0
    total = 0
    agent_stats: dict[str, dict] = {}  # latence par agent
    t0 = time.monotonic()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        bufsize=1,
        stdin=subprocess.DEVNULL,
    )

    try:
        for line in iter(proc.stdout.readline, ""):
            line_s = line.rstrip()
            tail.append(line_s)

            # Filtre sémantique — affiche uniquement les tags utiles
            is_tagged = any(tag in line_s for tag in SEMANTIC_TAGS)

            if is_tagged:
                icon = next((v for k, v in TAG_ICONS.items() if k in line_s), "  ")
                print(f"  {icon} {line_s}")

                # Parsing résultats
                if "[RESULT:OK]" in line_s:
                    ok_count += 1
                    consec_fail = 0
                    # Parse latence : [RESULT:OK] file | agent | 12345ms
                    parts = line_s.split("|")
                    if len(parts) >= 3:
                        agent = parts[1].strip()
                        ms_str = parts[2].strip().replace("ms", "")
                        try:
                            ms = int(ms_str)
                            if agent not in agent_stats:
                                agent_stats[agent] = {"total_ms": 0, "count": 0}
                            agent_stats[agent]["total_ms"] += ms
                            agent_stats[agent]["count"] += 1
                            if ms > latency_warn_ms:
                                print(f"  ⚠ [LATENCY:{ms}ms] {agent} — lent")
                        except ValueError:
                            pass

                elif "[RESULT:KO]" in line_s:
                    fail_count += 1
                    consec_fail += 1
                    if consec_fail >= max_consecutive_fails:
                        print(f"\n  🛑 EARLY EXIT — {consec_fail} échecs consécutifs")
                        proc.terminate()
                        break

                elif "[BILAN]" in line_s:
                    # Parse bilan final
                    pass

            # Toujours afficher les erreurs non taguées critiques
            elif any(k in line_s for k in ["Traceback", "Error:", "CRITICAL", "exception"]):
                print(f"  ⚠ {line_s}")

    except KeyboardInterrupt:
        print("\n  ⛔ Interruption utilisateur")
        proc.terminate()
    finally:
        proc.wait()

    duration = round(time.monotonic() - t0, 1)

    # Stats agents
    if agent_stats:
        print("\n  📈 Latences agents:")
        for agent, stats in sorted(
            agent_stats.items(), key=lambda x: x[1]["total_ms"] / max(x[1]["count"], 1)
        ):
            avg = stats["total_ms"] // max(stats["count"], 1)
            print(f"     {agent:20s} avg={avg}ms ({stats['count']} runs)")

    # État final via heartbeat
    state = poll_state()
    total = state.get("total", ok_count + fail_count)

    print(f"\n  {'✅' if fail_count == 0 else '⚠'} BILAN: {ok_count}/{total} OK en {duration}s")

    # Ring buffer — affiche les 10 dernières lignes si des erreurs
    if fail_count > 0:
        print("\n  --- Dernières lignes (ring buffer) ---")
        for l in list(tail)[-10:]:
            if l.strip():
                print(f"  {l}")

    return {
        "ok": ok_count,
        "fail": fail_count,
        "total": total,
        "duration": duration,
        "agents": agent_stats,
        "rc": proc.returncode,
    }


def main():
    parser = argparse.ArgumentParser(description="FORGE_STREAM_MUTATION_V1")
    parser.add_argument("--real", action="store_true", help="Mutation réelle (pas dry-run)")
    parser.add_argument("--poll", action="store_true", help="Poll état courant seulement")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--files", nargs="*", help="Fichiers spécifiques")
    parser.add_argument(
        "--max-fails", type=int, default=4, help="Early exit après N échecs consécutifs"
    )
    parser.add_argument("--latency", type=int, default=30000, help="Seuil alerte latence (ms)")
    args = parser.parse_args()

    if args.poll:
        state = poll_state()
        print("📊 État mutation courante:")
        print_state(state)
        return

    result = stream_worker(
        dry_run=not args.real,
        workers=args.workers,
        files=args.files,
        max_consecutive_fails=args.max_fails,
        latency_warn_ms=args.latency,
    )
    sys.exit(0 if result["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
