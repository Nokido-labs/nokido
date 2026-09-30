#!/usr/bin/env python3
"""
tools/nokido.py - Entrypoint unifie Nokido.

LE script a executer : il orchestre hub + tous les modules.

USAGE :
    python tools/nokido.py up       # start hub + tous modules
    python tools/nokido.py down     # stop tout
    python tools/nokido.py status   # vue consolidee
    python tools/nokido.py hub      # start juste le hub
    python tools/nokido.py open     # ouvre navigateur sur le hub
    python tools/nokido.py logs <module> [-n 100]
    python tools/nokido.py doctor   # sante : deps, config, token, ports

Pour piloter les modules individuellement, voir tools/nokido_modules.py
(ce wrapper delegate les cas courants).
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/bootstrap : entrypoint unifie, orchestre hub et modules"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import asyncio
import importlib
import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Charge Nokido.env (ou .env) avant tout import qui lit l env
try:
    from app.web_hub.envfile import load_env_file

    load_env_file()
except Exception:
    pass  # fail-silent : l env shell reste prioritaire


def _dim(s):
    return f"\x1b[2m{s}\x1b[0m"


def _g(s):
    return f"\x1b[32m{s}\x1b[0m"


def _r(s):
    return f"\x1b[31m{s}\x1b[0m"


def _y(s):
    return f"\x1b[33m{s}\x1b[0m"


def _print_status(st: dict) -> None:
    tag = {
        "running": _g("RUNNING"),
        "stopped": _dim("STOPPED"),
        "stale": _y("STALE"),
        "unknown": _r("UNKNOWN"),
    }.get(st.get("status", "?"), st.get("status", "?"))
    mod = st.get("module", "?")
    title = st.get("title", "")
    meta = []
    if st.get("pid"):
        meta.append(f"pid={st['pid']}")
    if st.get("port"):
        meta.append(f"port={st['port']}")
    if st.get("uptime_s") is not None:
        meta.append(f"uptime={st['uptime_s']}s")
    print(f"  [{tag}]  {mod:12s} {title}  {_dim('  '.join(meta)) if meta else ''}")


async def cmd_status() -> int:
    from app.web_hub.launcher import list_all

    print("=== Nokido modules ===")
    for st in list_all():
        _print_status(st)
    return 0


async def cmd_hub() -> int:
    from app.web_hub.launcher import MODULES, start

    if "hub" not in MODULES:
        print(_r("hub non declare dans le registre"), file=sys.stderr)
        return 2
    r = await start("hub", subject="cli-nokido")
    _print_status(r)
    return 0 if r.get("status") == "running" else 1


async def cmd_up() -> int:
    from app.web_hub.launcher import MODULES, start

    ordered = ["hub"] + [k for k in MODULES if k != "hub"]
    rc = 0
    for k in ordered:
        r = await start(k, subject="cli-up")
        status = r.get("status")
        action = r.get("action", "?")
        mark = _g("OK") if status == "running" else _r("KO")
        print(f"  [{mark}] {k:12s} action={action}")
        if status != "running":
            rc = 1
    return rc


async def cmd_down() -> int:
    from app.web_hub.launcher import MODULES, stop

    ordered = [k for k in MODULES if k != "hub"] + ["hub"]
    for k in ordered:
        r = await stop(k, subject="cli-down")
        print(f"  [{_dim(r.get('action', '?'))}] {k}")
    return 0


async def cmd_logs(mod: str, n: int) -> int:
    from app.web_hub.launcher import MODULES, tail_log

    if mod not in MODULES:
        print(_r(f"module inconnu : {mod}"), file=sys.stderr)
        return 2
    print(tail_log(mod, n=n))
    return 0


def cmd_open() -> int:
    port = int(os.environ.get("LAFORGE_HUB_PORT", "7400"))
    url = f"http://127.0.0.1:{port}/"
    print(f"Opening {url}")
    try:
        webbrowser.open(url)
        return 0
    except Exception as e:
        print(_r(f"webbrowser.open failed: {e}"), file=sys.stderr)
        return 1


def cmd_doctor() -> int:
    """Diagnostic : deps, config, token, ports."""
    print("=== nokido doctor ===")
    rc = 0
    # Deps via importlib (pas de builtin import avec string)
    for m in ("fastapi", "uvicorn", "httpx", "websockets", "jwt", "psutil", "textual_serve"):
        try:
            mod = importlib.import_module(m)
            ver = getattr(mod, "__version__", "?")
            print(f"  [{_g('OK')}] {m:14s} {ver}")
        except ImportError:
            print(f"  [{_r('KO')}] {m}")
            rc = 1

    token = os.environ.get("LAFORGE_ADMIN_TOKEN")
    if token:
        print(f"  [{_g('OK')}] LAFORGE_ADMIN_TOKEN set ({len(token)} chars)")
    else:
        print(
            f"  [{_y('WARN')}] LAFORGE_ADMIN_TOKEN absent -> fail-closed : "
            f"hub refusera les requetes auth"
        )
        rc = 1

    auth_enabled = os.environ.get("LAFORGE_AUTH_ENABLED", "1")
    if auth_enabled in ("0", "false", "False"):
        print(f"  [{_y('WARN')}] LAFORGE_AUTH_ENABLED=0 (dev mode, auth OFF)")

    import socket

    for port in (7400, 7410, 7420, 7430, 7440):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            print(f"  [{_g('OK')}] port {port} libre")
        except OSError:
            print(f"  [{_y('BUSY')}] port {port} occupe (peut-etre module en cours)")
        finally:
            s.close()

    try:
        from app.web_hub.launcher import list_all

        print("  Modules:")
        for st in list_all():
            _print_status(st)
    except Exception as e:
        print(f"  [{_r('KO')}] import launcher: {e}")
        rc = 1

    return rc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nokido - entrypoint unifie",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="Start hub + tous les modules")
    sub.add_parser("down", help="Stop tous les modules")
    sub.add_parser("status", help="Vue consolidee")
    sub.add_parser("hub", help="Start juste le hub")
    sub.add_parser("open", help="Ouvre le navigateur sur le hub")
    sub.add_parser("doctor", help="Sante : deps + config + ports")
    pl = sub.add_parser("logs", help="Tail des logs d un module")
    pl.add_argument("module")
    pl.add_argument("-n", type=int, default=100)

    args = parser.parse_args()
    c = args.cmd
    try:
        if c == "status":
            return asyncio.run(cmd_status())
        if c == "hub":
            return asyncio.run(cmd_hub())
        if c == "up":
            return asyncio.run(cmd_up())
        if c == "down":
            return asyncio.run(cmd_down())
        if c == "logs":
            return asyncio.run(cmd_logs(args.module, args.n))
        if c == "open":
            return cmd_open()
        if c == "doctor":
            return cmd_doctor()
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
