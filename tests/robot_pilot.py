"""
tests/robot_pilot.py — Test live des commandes @ via log applicatif
====================================================================
Methode : ecrire un fichier trigger -> Nokido le poll -> executer
Pas de reload, pas de subprocess, pas de Textual headless.

Usage : python tests/robot_pilot.py
        python tests/robot_pilot.py --cmd "@rag info"
"""
import sys, os, json, time, asyncio
from pathlib import Path

ROOT = Path(__file__).parent.parent
TRIGGER = ROOT / "sandbox" / "robot_trigger.json"
CAPTURE = ROOT / "sandbox" / "robot_capture.json"

# ── Suite de tests ────────────────────────────────────────────────────────────
# (commande, mots-cles attendus dans le log dans les 5s)
TESTS = [
    # RAG
    ("@rag info",        ["chunk", "Chunk", "FAISS", "RAG", "source"]),
    ("@rag list",        ["source", "/", "indexé", "RAG"]),
    ("@rag size",        ["Ko", "Mo", "source", "taille"]),
    # Role
    ("@role list",       ["Analyste", "Debugger", "Planner"]),
    ("@role assign Debugger", ["Debugger", "actif", "role", "Role"]),
    # Mode
    ("@mode status",     ["mode", "actif", "général", "auto"]),
    ("@mode set auto",   ["auto", "mode", "Mode"]),
    # NR
    ("@nr",              ["NR", "PASS", "FAIL", "AST", "check"]),
    # Help
    ("@help",            ["@rag", "@role", "@mode", "@nr"]),
    # Ollama
    ("@ollama list",     ["model", "qwen", "ollama", "Ollama"]),
    # Services
    ("@services",        ["service", "Service", "endpoint", "OK"]),
    # Mem
    ("@mem",             ["mem", "Mem", "mémoire", "session"]),
    # Model
    ("@model",           ["model", "Model", "actif", "qwen"]),
    # Audit
    ("@audit",           ["audit", "Audit", "OK", "check"]),
]

def _find_tui_log() -> Path | None:
    """Trouver le log applicatif TUI le plus recent (pas le log MCP)."""
    logs = sorted(
        (ROOT / "logs").glob("laforge_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    for log in logs:
        txt = log.read_text(encoding="utf-8", errors="ignore")
        if "Boot" in txt and "rag_engine" in txt:
            return log
    return logs[0] if logs else None

def _log_tail(log: Path, since_size: int) -> str:
    """Lire le nouveau contenu depuis since_size."""
    txt = log.read_text(encoding="utf-8", errors="ignore")
    return txt[since_size:]

def run_tests(only_cmd: str | None = None):
    log = _find_tui_log()
    if not log:
        print("CRITICAL: aucun log TUI trouve — Nokido est-il demarre ?")
        sys.exit(2)
    print(f"Log TUI : {log.name}")

    suite = TESTS if not only_cmd else [(c, k) for c, k in TESTS if c == only_cmd]
    if only_cmd and not suite:
        suite = [(only_cmd, ["OK", "ok", "chunk", "Chunk"])]

    results = []
    all_ok = True

    for cmd, keywords in suite:
        # Taille log avant
        size_before = log.stat().st_size

        # Ecrire le trigger
        TRIGGER.write_text(json.dumps({"cmd": cmd, "ts": time.time()}), encoding="utf-8")
        print(f"\n⌨  {cmd}")
        print(f"   → tape cette commande dans ta TUI, puis attends...")

        # Attendre max 8s que le log grossisse
        deadline = time.time() + 8
        new_content = ""
        while time.time() < deadline:
            time.sleep(0.3)
            new_content = _log_tail(log, size_before)
            if new_content.strip():
                break

        if not new_content.strip():
            results.append((cmd, False, "TIMEOUT — aucune reponse dans le log"))
            all_ok = False
            continue

        found = [kw for kw in keywords if kw in new_content]
        ok = len(found) > 0

        # Derniere ligne significative
        sig = [l for l in new_content.splitlines() if l.strip() and "DEBUG" not in l]
        snippet = sig[-1][:120] if sig else new_content[:120]

        results.append((cmd, ok, f"found={found} | {snippet}"))
        if not ok:
            all_ok = False

    # ── Affichage ────────────────────────────────────────────────────────────
    W = 72
    print("\n" + "=" * W)
    print("  ROBOT PILOT — RESULTATS")
    print("=" * W)
    for cmd, ok, detail in results:
        print(f"\n{'✅' if ok else '❌'}  {cmd}")
        print(f"    {detail}")
    print("\n" + "=" * W)
    print(f"  {'✅ TOUS OK — commit autorise' if all_ok else '❌ ECHECS — commit REJETE'}")
    print("=" * W)
    return all_ok

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--cmd", default=None, help="Tester une seule commande")
    p.add_argument("--auto", action="store_true", help="Mode auto : lire trigger depuis sandbox/")
    args = p.parse_args()
    ok = run_tests(only_cmd=args.cmd)
    sys.exit(0 if ok else 1)
