#!/usr/bin/env python3
"""
tools/nokido_modules.py - Interface CLI unifiee pour les modules Nokido.

Partage le meme supervisor (app/web_hub/launcher.py) que le panneau web :
pidfiles communs dans sandbox/run/, logs dans sandbox/logs/.

USAGE :
    python tools/nokido_modules.py list
    python tools/nokido_modules.py status [<module>]
    python tools/nokido_modules.py start <module>
    python tools/nokido_modules.py stop <module>
    python tools/nokido_modules.py restart <module>
    python tools/nokido_modules.py logs <module> [-n 100]
    python tools/nokido_modules.py up    # start TOUS
    python tools/nokido_modules.py down  # stop TOUS

MODULES : voir 'list'. Actuellement : tui_bridge, recon, graph.
Le hub lui-meme n est pas gerable via cet outil (il doit etre lance
exterieurement car l API launcher vit dedans).
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/bootstrap : interface CLI unifiee des modules (meme supervisor)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from app.web_hub.envfile import load_env_file

    load_env_file()
except Exception:
    pass


def _dim(s: str) -> str:
    return f"\x1b[2m{s}\x1b[0m"


def _green(s: str) -> str:
    return f"\x1b[32m{s}\x1b[0m"


def _red(s: str) -> str:
    return f"\x1b[31m{s}\x1b[0m"


def _yellow(s: str) -> str:
    return f"\x1b[33m{s}\x1b[0m"


def _tag(status: str) -> str:
    return {
        "running": _green("RUNNING"),
        "stopped": _dim("STOPPED"),
        "stale": _yellow("STALE"),
        "unknown": _red("UNKNOWN"),
    }.get(status, status)


def _print_status(st: dict) -> None:
    mod = st.get("module", "?")
    tag = _tag(st.get("status", "?"))
    title = st.get("title", "")
    pid = st.get("pid")
    port = st.get("port")
    uptime = st.get("uptime_s")
    parts = [f"[{tag}]", f"{mod}".ljust(12), f"{title}"]
    meta = []
    if pid:
        meta.append(f"pid={pid}")
    if port:
        meta.append(f"port={port}")
    if uptime is not None:
        meta.append(f"uptime={uptime}s")
    if meta:
        parts.append(_dim("  ".join(meta)))
    print("  ".join(parts))


async def _cmd_list() -> int:
    from app.web_hub.launcher import list_all

    for st in list_all():
        _print_status(st)
    return 0


async def _cmd_status(mod: str | None) -> int:
    from app.web_hub.launcher import MODULES, status

    if mod:
        if mod not in MODULES:
            print(_red(f"module inconnu : {mod}"), file=sys.stderr)
            return 2
        _print_status(status(mod))
    else:
        for k in MODULES:
            _print_status(status(k))
    return 0


async def _cmd_start(mod: str) -> int:
    from app.web_hub.launcher import MODULES, start

    if mod not in MODULES:
        print(_red(f"module inconnu : {mod}"), file=sys.stderr)
        return 2
    r = await start(mod, subject="cli")
    print(json.dumps(r, indent=2))
    return 0 if r.get("status") == "running" else 1


async def _cmd_stop(mod: str) -> int:
    from app.web_hub.launcher import MODULES, stop

    if mod not in MODULES:
        print(_red(f"module inconnu : {mod}"), file=sys.stderr)
        return 2
    r = await stop(mod, subject="cli")
    print(json.dumps(r, indent=2))
    return 0


async def _cmd_restart(mod: str) -> int:
    await _cmd_stop(mod)
    return await _cmd_start(mod)


async def _cmd_logs(mod: str, n: int) -> int:
    from app.web_hub.launcher import MODULES, tail_log

    if mod not in MODULES:
        print(_red(f"module inconnu : {mod}"), file=sys.stderr)
        return 2
    print(tail_log(mod, n=n))
    return 0


async def _cmd_up() -> int:
    from app.web_hub.launcher import MODULES, start

    rc = 0
    for k in MODULES:
        r = await start(k, subject="cli-up")
        tag = "started" if r.get("action") == "started" else r.get("action", "?")
        print(f"  [{tag}] {k}")
        if r.get("status") not in ("running",):
            rc = 1
    return rc


async def _cmd_down() -> int:
    from app.web_hub.launcher import MODULES, stop

    for k in MODULES:
        r = await stop(k, subject="cli-down")
        print(f"  [{r.get('action', '?')}] {k}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nokido - pilotage unifie des modules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Liste des modules + status")

    ps = sub.add_parser("status", help="Status d un module (ou tous)")
    ps.add_argument("module", nargs="?")

    for name in ("start", "stop", "restart"):
        sp = sub.add_parser(name, help=f"{name.capitalize()} un module")
        sp.add_argument("module")

    pl = sub.add_parser("logs", help="Affiche les N dernieres lignes du log")
    pl.add_argument("module")
    pl.add_argument("-n", type=int, default=100)

    sub.add_parser("up", help="Demarre TOUS les modules")
    sub.add_parser("down", help="Arrete TOUS les modules")

    args = parser.parse_args()
    cmd = args.cmd
    try:
        if cmd == "list":
            return asyncio.run(_cmd_list())
        if cmd == "status":
            return asyncio.run(_cmd_status(args.module))
        if cmd == "start":
            return asyncio.run(_cmd_start(args.module))
        if cmd == "stop":
            return asyncio.run(_cmd_stop(args.module))
        if cmd == "restart":
            return asyncio.run(_cmd_restart(args.module))
        if cmd == "logs":
            return asyncio.run(_cmd_logs(args.module, args.n))
        if cmd == "up":
            return asyncio.run(_cmd_up())
        if cmd == "down":
            return asyncio.run(_cmd_down())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
