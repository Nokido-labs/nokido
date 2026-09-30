#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_owner_bridge.py — pont OWNER-CONTEXT : exécute des commandes dans la
SESSION CONSOLE de l'owner (user) depuis le hub SYSTEM.

POURQUOI : le hub `run shell` tombe sur LaForgeSbxOffline (user bas-priv) qui
n'a PAS accès au service WSL (E_ACCESSDENIED) ni au pipe Docker. WSL et Docker
Desktop sont per-user / GUI → ils n'existent QUE dans la session de l'owner
loggé. Ce pont permet à SYSTEM (qui a SeTcbPrivilege) de lancer une commande
DANS la session owner et d'en récupérer la sortie (handoff par fichier).

ANTI-DUP : COMPOSE `forge_sandbox_exec.spawn_as_interactive_jobbed`
(WTSQueryUserToken + CreateProcessAsUser, lpDesktop=winsta0\\default,
Job-Object KILL_ON_JOB_CLOSE) — ne réimplémente PAS le spawn Win32.

CONTRAINTE : le CALLER doit avoir SeTcbPrivilege (= LocalSystem). Donc à lancer
via `run action=trusted_script` (privilégié), JAMAIS via `run shell` (sandbox).
Si aucun user n'est loggé en console → SandboxError (rien à ponter).

USAGE :
  python forge_owner_bridge.py --probe            # diag wsl/docker/wasm owner
  python forge_owner_bridge.py "wsl -l -v"        # une commande
  python forge_owner_bridge.py --json "docker ps" # sortie JSON
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_sandbox_exec import SandboxError, spawn_as_interactive_jobbed  # noqa: E402

BRIDGE_DIR = Path(os.environ.get("LAFORGE_OWNER_BRIDGE_DIR", r"C:\tmp\owner_bridge"))


def _decode(p: Path) -> str:
    """wsl.exe -l -v écrit en UTF-16LE (octets nuls) ; les commandes Linux en
    UTF-8. Décode robustement selon la densité de nuls."""
    if not p.exists():
        return ""
    b = p.read_bytes()
    if not b:
        return ""
    if b.count(b"\x00") > len(b) // 4:
        return b.decode("utf-16-le", "replace")
    return b.decode("utf-8", "replace")


def run_in_owner(commands, timeout: float = 90.0) -> dict:
    """Exécute une ou plusieurs commandes shell DANS la session console owner.
    Retourne {ok, rc, stdout, user, jid, timed_out}. Handoff par fichier :
    le child (session owner) redirige stdout/stderr vers un fichier que SYSTEM
    relit ensuite (l'héritage de handle inter-session n'est pas fiable)."""
    if isinstance(commands, str):
        commands = [commands]
    jid = secrets.token_hex(6)
    d = BRIDGE_DIR / jid
    d.mkdir(parents=True, exist_ok=True)
    out = d / "out.txt"
    rc = d / "rc.txt"
    done = d / "done.flag"
    bat = d / "run.cmd"

    body = ["@echo off", "chcp 65001 >nul", f'> "{out}" 2>&1 (']
    for c in commands:
        body.append(f"  echo ===CMD=== {c}")
        body.append(f"  {c}")
        body.append("  echo.")
    body.append(")")
    body.append(f'echo %ERRORLEVEL%> "{rc}"')
    body.append(f'echo done> "{done}"')
    bat.write_text("\r\n".join(body), encoding="utf-8")

    res = spawn_as_interactive_jobbed(f'cmd.exe /c "{bat}"')
    job = res.get("_job")  # DOIT rester en vie (KILL_ON_JOB_CLOSE) jusqu'à lecture
    deadline = time.time() + timeout
    while time.time() < deadline:
        if done.exists():
            break
        time.sleep(0.4)
    ok = done.exists()
    result = {
        "ok": bool(ok),
        "rc": (_decode(rc).strip() or None) if ok else None,
        "stdout": _decode(out),
        "user": res.get("sandbox_user"),
        "jid": jid,
        "timed_out": not ok,
    }
    del job  # libère le Job-Object après lecture (child déjà terminé)
    return result


# Périmètre owner-context : WSL + Docker + runtimes wasm, vus depuis la session
# user (et non le user sandbox du hub).
_PROBE = [
    "whoami",
    "wsl -l -v",
    'wsl -- sh -lc "command -v wasmedge wasmtime; wasmedge --version 2>&1 | head -1"',
    "wasmtime --version",
    "where wasmtime",
    'docker version --format "{{.Server.Version}}"',
    'docker ps -a --format "{{.Names}} | {{.Image}} | {{.Status}}"',
    'docker images --format "{{.Repository}}:{{.Tag}}"',
]


def probe() -> dict:
    return run_in_owner(_PROBE, timeout=120)


def main() -> int:
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    try:
        if not args or args[0] == "--probe":
            r = probe()
        else:
            r = run_in_owner(args[0])
    except SandboxError as e:
        r = {"ok": False, "error": str(e), "hint": "no console session OR caller lacks SeTcbPrivilege (run via trusted_script as SYSTEM)"}
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"[owner-bridge] user={r.get('user')} ok={r.get('ok')} rc={r.get('rc')} timed_out={r.get('timed_out')}")
        if r.get("error"):
            print("ERROR:", r["error"], "\nHINT:", r.get("hint"))
        print(r.get("stdout", ""))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
