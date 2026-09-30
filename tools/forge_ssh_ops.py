#!/usr/bin/env python
"""Executeur SSH souverain — pilote un hote du LAN depuis le contexte trusted.

Client OpenSSH natif Windows (ssh.exe / scp.exe) : pas de crypto Python
(paramiko/asyncssh sont casses ici, _cffi_backend ACL refuse en trusted).
Auth par cle uniquement, BatchMode : jamais d'invite interactive, donc
utilisable depuis un appel hub non tty.

Le sandbox `run` (LaForgeSbxOffline) n'a PAS d'egress LAN -> WinError 10013.
Ce script doit donc etre lance via `run action=trusted_script`.

  keygen              genere la paire ed25519 (idempotent) et imprime la PUBLIQUE
  sh   --host --user --cmd
  put  --host --user --src --dst
"""
from __future__ import annotations

__FORGE_COLOR__ = "reseau/ssh : executeur SSH souverain vers un hote du LAN (trusted)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

KEY_DIR = Path(r"C:\tmp\nokido_ssh")
KEY_PATH = KEY_DIR / "id_ed25519"
COMMENT = "nokido-pc"

_COMMON: List[str] = [
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "UserKnownHostsFile=NUL",
    "-o", "GlobalKnownHostsFile=NUL",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
]


def _lock_down(path: Path) -> None:
    """ssh.exe refuse une cle privee lisible par d'autres : ACL owner-only."""
    user = os.environ.get("USERNAME", "")
    if not user:
        return
    subprocess.run(["icacls", str(path), "/inheritance:r"],
                   capture_output=True, text=True, errors="replace")
    subprocess.run(["icacls", str(path), "/grant:r", f"{user}:R"],
                   capture_output=True, text=True, errors="replace")


def cmd_keygen() -> dict:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        res = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(KEY_PATH),
             "-N", "", "-C", COMMENT],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            return {"ok": False, "error": (res.stderr or res.stdout)[:300]}
    _lock_down(KEY_PATH)
    pub = KEY_PATH.with_suffix(".pub").read_text(encoding="utf-8").strip()
    return {"ok": True, "key": str(KEY_PATH), "public_key": pub}


def _base(user: str, host: str) -> Tuple[List[str], str]:
    args = list(_COMMON)
    if KEY_PATH.exists():
        args += ["-i", str(KEY_PATH)]
    return args, f"{user}@{host}"


def cmd_shell(host: str, user: str, cmd: str, timeout: int) -> dict:
    args, target = _base(user, host)
    try:
        res = subprocess.run(["ssh", *args, target, cmd], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=timeout + 10)
    except FileNotFoundError:
        return {"ok": False, "error": "ssh.exe introuvable (OpenSSH absent du PATH)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout ssh {target}"}
    return {
        "ok": res.returncode == 0,
        "rc": res.returncode,
        "stdout": (res.stdout or "")[:6000],
        "stderr": (res.stderr or "")[:2000],
    }


def cmd_put(host: str, user: str, src: str, dst: str, timeout: int) -> dict:
    args, target = _base(user, host)
    if not Path(src).exists():
        return {"ok": False, "error": f"source absente : {src}"}
    try:
        res = subprocess.run(["scp", *args, src, f"{target}:{dst}"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout + 10)
    except FileNotFoundError:
        return {"ok": False, "error": "scp.exe introuvable"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout scp {target}"}
    return {
        "ok": res.returncode == 0,
        "rc": res.returncode,
        "dst": f"{target}:{dst}",
        "stderr": (res.stderr or "")[:2000],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Executeur SSH souverain")
    sub = ap.add_subparsers(dest="op", required=True)
    sub.add_parser("keygen")
    p_sh = sub.add_parser("sh")
    p_sh.add_argument("--host", required=True)
    p_sh.add_argument("--user", required=True)
    p_sh.add_argument("--cmd", required=True)
    p_sh.add_argument("--timeout", type=int, default=45)
    p_put = sub.add_parser("put")
    p_put.add_argument("--host", required=True)
    p_put.add_argument("--user", required=True)
    p_put.add_argument("--src", required=True)
    p_put.add_argument("--dst", required=True)
    p_put.add_argument("--timeout", type=int, default=45)
    args = ap.parse_args()

    if args.op == "keygen":
        res = cmd_keygen()
    elif args.op == "sh":
        res = cmd_shell(args.host, args.user, args.cmd, args.timeout)
    else:
        res = cmd_put(args.host, args.user, args.src, args.dst, args.timeout)

    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
