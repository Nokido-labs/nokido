#!/usr/bin/env python3
"""forge_wasm_bridge.py — pont OWNER-context hub <-> WasmEdge (WSL Debian).

POURQUOI (mesuré 2026-06-17) : le hub (LaForgeTrusted) est ACL-denied sur `wsl`
(Wsl/Service/E_ACCESSDENIED), y compris via sandbox=console. Il NE PEUT PAS exécuter
WasmEdge installé dans WSL Debian. Pattern AUTOPOÏÈSE (cf forge_backend_power) :

  - CÔTÉ HUB  : `submit_wasm()` écrit sandbox/wasm_jobs/<id>.req.json (file I/O seul,
    jamais wsl) puis poll <id>.res.json. Vérifie d'abord le heartbeat du daemon.
  - CÔTÉ OWNER: `--daemon` (session user, accès WSL) lit les .req.json, exécute
    `wsl -d Debian wasmedge ...`, réécrit .res.json, bat un heartbeat.

Respecte le mur ACL au lieu de le forcer.

Usage (OWNER, ex via `!` / schtask) :
  forge_wasm_bridge.py --selftest   # forge add.wasm + l'exécute, attend 7 (preuve E2E)
  forge_wasm_bridge.py --once       # traite la file une fois puis sort
  forge_wasm_bridge.py --daemon     # boucle poll 0.5s + heartbeat (schtask owner)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "sandbox" / "wasm_jobs"
JOBS.mkdir(parents=True, exist_ok=True)
DISTRO = "Debian"
WASMEDGE = "/home/user/.wasmedge/bin/wasmedge"
HEARTBEAT = JOBS / ".heartbeat"

# WASM minimal : (module (func (export "add")(param i32 i32)(result i32)
#                  local.get 0  local.get 1  i32.add)) — 41 octets, validé à la main.
ADD_WASM = bytes([
    0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00,          # \0asm v1
    0x01, 0x07, 0x01, 0x60, 0x02, 0x7f, 0x7f, 0x01, 0x7f,    # type: (i32,i32)->i32
    0x03, 0x02, 0x01, 0x00,                                  # func: 1 of type 0
    0x07, 0x07, 0x01, 0x03, 0x61, 0x64, 0x64, 0x00, 0x00,    # export "add" func 0
    0x0a, 0x09, 0x01, 0x07, 0x00, 0x20, 0x00, 0x20, 0x01,    # code: get0 get1
    0x6a, 0x0b,                                              # i32.add end
])


# ───────────────────────────── OWNER side (invoke wsl) ──────────────────────
def win_to_wsl(p: str) -> str:
    """C:\\x\\y -> /mnt/c/x/y ; laisse les chemins déjà-posix intacts."""
    p = str(p).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:]}"
    return p


def run_wasmedge(wasm_path: str, func: str | None, args: list, timeout: int = 30) -> dict:
    wsl_path = win_to_wsl(wasm_path)
    cmd = ["wsl", "-d", DISTRO, "-e", WASMEDGE]
    if func:
        cmd += ["--reactor", wsl_path, func] + [str(a) for a in (args or [])]
    else:
        cmd += [wsl_path] + [str(a) for a in (args or [])]
    t0 = time.time()
    try:
        pr = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        return {"ok": pr.returncode == 0, "rc": pr.returncode,
                "stdout": (pr.stdout or "").strip(), "stderr": (pr.stderr or "").strip(),
                "elapsed_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": f"timeout {timeout}s",
                "elapsed_ms": timeout * 1000}
    except Exception as e:  # noqa
        return {"ok": False, "rc": -1, "stdout": "", "stderr": str(e),
                "elapsed_ms": int((time.time() - t0) * 1000)}


def process_once() -> int:
    n = 0
    for req in sorted(JOBS.glob("*.req.json")):
        try:
            spec = json.loads(req.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = run_wasmedge(spec.get("wasm_path", ""), spec.get("func"),
                           spec.get("args") or [], int(spec.get("timeout", 30)))
        out = req.with_name(req.name.replace(".req.json", ".res.json"))
        out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        try:
            req.unlink()
        except Exception:
            pass
        n += 1
    return n


def daemon() -> int:
    print(f"[forge_wasm_bridge] OWNER daemon up — watching {JOBS}", flush=True)
    while True:
        try:
            HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
            process_once()
        except Exception as e:  # noqa
            print(f"[forge_wasm_bridge] loop err: {e}", flush=True)
        time.sleep(0.5)


# ───────────────────────────── HUB side (file I/O only) ─────────────────────
def daemon_alive(max_age: float = 15.0) -> bool:
    try:
        return (time.time() - float(HEARTBEAT.read_text(encoding="utf-8"))) < max_age
    except Exception:
        return False


def submit_wasm(wasm_path: str, func: str | None = None, args: list | None = None,
                timeout: int = 30, wait_s: float = 40.0, poll: float = 0.25) -> dict:
    """CÔTÉ HUB (jamais wsl) : enqueue une requête + poll le résultat écrit par le
    daemon OWNER. Retourne {ok, rc, stdout, stderr, elapsed_ms}."""
    import uuid

    if not daemon_alive():
        return {"ok": False, "rc": -1, "stdout": "",
                "stderr": "forge_wasm_bridge daemon OWNER inactif (heartbeat absent/stale) — "
                          "lancer: python tools/forge_wasm_bridge.py --daemon (session owner)",
                "elapsed_ms": 0}
    jid = uuid.uuid4().hex[:12]
    req = JOBS / f"{jid}.req.json"
    res = JOBS / f"{jid}.res.json"
    req.write_text(json.dumps({"id": jid, "wasm_path": str(wasm_path), "func": func,
                               "args": list(args or []), "timeout": int(timeout)}),
                   encoding="utf-8")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if res.exists():
            try:
                out = json.loads(res.read_text(encoding="utf-8"))
            except Exception:
                time.sleep(poll)
                continue
            try:
                res.unlink()
            except Exception:
                pass
            return out
        time.sleep(poll)
    for p in (req, res):
        try:
            p.unlink()
        except Exception:
            pass
    return {"ok": False, "rc": -1, "stdout": "", "stderr": f"bridge timeout {wait_s}s",
            "elapsed_ms": int(wait_s * 1000)}


# ───────────────────────────── CLI ─────────────────────────────────────────
def selftest() -> int:
    wasm = JOBS / "_selftest_add.wasm"
    wasm.write_bytes(ADD_WASM)
    res = run_wasmedge(str(wasm), "add", [3, 4], timeout=30)
    ok = bool(res.get("ok")) and res.get("stdout", "").strip().splitlines()[-1:] == ["7"]
    print(json.dumps({"selftest_ok": ok, "expected": 7, "result": res}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main(argv: list) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--once" in argv:
        print(json.dumps({"processed": process_once()}))
        return 0
    if "--daemon" in argv:
        return daemon()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
