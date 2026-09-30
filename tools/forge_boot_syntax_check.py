#!/usr/bin/env python3
"""forge_boot_syntax_check.py — Preflight AST au boot.

ast.parse() de TOUS les app/*.py + tools/*.py AVANT que la flotte ne démarre.

Pourquoi (incident 2026-06-16) : un .py cassé sur disque (WIP non-committé / clobber
multi-agent) chargé au reboot fait fail-close le gate du hub SANS message — le hub
bind :8766 quand même (l'import du gate se fait au ring-check runtime, pas au boot),
donc `nokido_start.ps1` affichait "hub up" en vert pendant que TOUT appel renvoyait
GATE_DENIED / 500 → tous les agents (gemini, codex, claude) éjectés du MCP, en silence.

Ce check rend la panne VISIBLE + PRÉCOCE. Zéro import des modules scannés (aucun
side-effect, juste ast.parse). Exit code = nombre de fichiers cassés (0 = propre).
Trace : logs/boot_syntax_check.log.
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/bootstrap : preflight AST de app/ et tools/ avant le boot"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SKIP = ("__pycache__", "_attic", "RAG_plain_bak", "node_modules", ".venv")


def scan() -> list[tuple[str, int, str]]:
    bad: list[tuple[str, int, str]] = []
    for sub in ("app", "tools"):
        d = ROOT / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            sp = str(p)
            if any(s in sp for s in _SKIP):
                continue
            try:
                ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=sp)
            except SyntaxError as e:
                rel = str(p.relative_to(ROOT)).replace("\\", "/")
                bad.append((rel, e.lineno or 0, e.msg))
            except Exception:
                # lecture impossible (ACL/verrou) -> non bloquant
                continue
    return bad


def main() -> int:
    bad = scan()
    try:
        log = ROOT / "logs" / "boot_syntax_check.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} : {len(bad)} broken ===\n")
            for fpath, ln, msg in bad:
                f.write(f"  {fpath}:{ln}: {msg}\n")
    except Exception:
        pass

    if not bad:
        print("[boot-syntax] OK - app/ + tools/ parse clean")
        return 0

    print(f"[boot-syntax] *** {len(bad)} BROKEN .py - hub gate va fail-close (silencieux !) ***")
    for fpath, ln, msg in bad:
        print(f"  BROKEN {fpath}:{ln}: {msg}")
    return len(bad)


if __name__ == "__main__":
    raise SystemExit(main())
