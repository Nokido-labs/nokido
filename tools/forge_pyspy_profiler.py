#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_pyspy_profiler.py — profiling runtime du hub (saturation / timeouts).

Zone d'ombre PERF #1 (roadmap observabilité chantier #2) : le hub (:8766,
nokido_hub.py) tombe en timeout/down sous charge (frappé 5×+ le 2026-06-02)
sans qu'on sache QUELLE pile bloque. py-spy = sampling profiler externe (lit la
mémoire du process, n'instrumente pas le code) → flame graph + dump de piles
LIVE, y compris sous saturation, sans modifier ni redémarrer le hub.

Modes :
  check          : localise py-spy, trouve le PID hub, teste l'attache (dump).
                   À lancer EN PREMIER — lève les risques (install / version 3.14
                   / privilège ReadProcessMemory) avant de profiler pour de vrai.
  dump  [--pid P]              : snapshot INSTANTANÉ des piles (toutes threads).
                                 Idéal en pleine saturation (non-bloquant).
  record [--pid P] [--seconds N] : flame graph SVG sur N s (--nonblocking, ne
                                 met PAS le hub en pause).

Sorties dans sandbox/profiles/. Lancer en trusted_script (LaForgeTrusted =
privilégié, peut attacher au process hub).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "sandbox", "profiles")

_HOME = __import__("os").path.expanduser(r"~")
BIN_DIR = r"C:\tmp\nokido_bin"  # hors ACL profil : écrivable+exécutable par trusted
PYSPY_CANDIDATES = [
    os.path.join(BIN_DIR, "py-spy.exe"),
    os.path.join(_HOME, r"miniforge3\Scripts\py-spy.exe"),
    os.path.join(_HOME, r"miniforge3\envs\laforge_py314\Scripts\py-spy.exe"),
    os.path.join(_HOME, r".cargo\bin\py-spy.exe"),
]


def _dynamic_candidates() -> list[str]:
    import glob
    import site
    cands: list[str] = []
    # Scripts de l'env courant (sys.executable).
    cands.append(os.path.join(os.path.dirname(sys.executable), "Scripts", "py-spy.exe"))
    cands.append(os.path.join(os.path.dirname(sys.executable), "py-spy.exe"))
    # user-site (pip install --user) — version-spécifique sous %APPDATA%\Python.
    try:
        ub = site.getuserbase()
        for pat in (os.path.join(ub, "Scripts", "py-spy.exe"),
                    os.path.join(ub, "Python*", "Scripts", "py-spy.exe")):
            cands.extend(glob.glob(pat))
    except Exception:
        pass
    return cands


def find_pyspy() -> str | None:
    w = shutil.which("py-spy")
    if w:
        return w
    for c in PYSPY_CANDIDATES + _dynamic_candidates():
        try:
            if os.path.exists(c):
                return c
        except OSError:
            pass
    return None


def cmd_install() -> int:
    """Télécharge le wheel py-spy et en extrait py-spy.exe vers BIN_DIR.

    `pip install --user` échoue pour LaForgeTrusted (pas de profil → C:\\Users\\
    Default refusé). Le binaire py-spy est un exécutable Rust standalone : on le
    sort du wheel directement dans C:\\tmp\\nokido_bin (hors ACL profil).
    """
    import glob
    import zipfile

    dst = os.path.join(BIN_DIR, "py-spy.exe")
    if os.path.exists(dst):
        print(f"[install] déjà présent : {dst}")
        return 0
    os.makedirs(BIN_DIR, exist_ok=True)
    dl = os.path.join(BIN_DIR, "_dl")
    os.makedirs(dl, exist_ok=True)
    rc, out, err = _run(
        [sys.executable, "-m", "pip", "download", "py-spy",
         "--only-binary=:all:", "-d", dl], 300
    )
    print(f"[install] pip download rc={rc}")
    whls = glob.glob(os.path.join(dl, "py_spy*win_amd64.whl"))
    if not whls:
        print((out + err)[-600:])
        return 5
    with zipfile.ZipFile(whls[0]) as z:
        names = [n for n in z.namelist() if n.lower().endswith("py-spy.exe")]
        if not names:
            print(f"[install] py-spy.exe absent du wheel : {z.namelist()[:20]}")
            return 6
        with z.open(names[0]) as src, open(dst, "wb") as o:
            o.write(src.read())
    print(f"[install] py-spy extrait -> {dst}")
    return 0 if find_pyspy() else 7


def get_hub_pid() -> int | None:
    # 1. heartbeat (si présent).
    hb = os.path.join(ROOT, "sandbox", "hub.heartbeat")
    try:
        if os.path.exists(hb):
            pid = json.loads(open(hb, encoding="utf-8").read()).get("pid")
            if pid:
                return int(pid)
    except Exception:
        pass
    # 2. psutil : process python dont la cmdline contient nokido_hub.
    try:
        import psutil  # type: ignore
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            cl = " ".join(p.info.get("cmdline") or [])
            if "nokido_hub" in cl:
                return int(p.info["pid"])
    except Exception:
        pass
    # 3. supervisor :8765 (NokidoMCP).
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=8) as r:
            st = json.loads(r.read().decode("utf-8", "replace"))
        pid = st.get("services", {}).get("NokidoMCP", {}).get("pid")
        return int(pid) if pid else None
    except Exception:
        return None


def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return -1, "", f"{type(exc).__name__}: {exc}"


def cmd_check() -> int:
    pyspy = find_pyspy()
    pid = get_hub_pid()
    print(f"[check] py-spy   = {pyspy or 'INTROUVABLE (pip install py-spy)'}")
    print(f"[check] hub PID  = {pid or 'INTROUVABLE'}")
    if not pyspy:
        return 2
    rc, out, err = _run([pyspy, "--version"], 15)
    print(f"[check] version  = rc={rc} {out.strip()} {err.strip()}")
    if not pid:
        return 3
    # Test attache : dump instantané (révèle support 3.14 + privilège).
    rc, out, err = _run([pyspy, "dump", "--pid", str(pid)], 30)
    print(f"[check] dump test rc={rc}")
    if rc == 0:
        head = "\n".join(out.splitlines()[:12])
        print("[check] OK — attache au hub fonctionne. Extrait :\n" + head)
    else:
        print("[check] ECHEC attache. stderr :\n" + err[:600])
        if "error 5" in err.lower() or "refus" in err.lower():
            print(
                "\n[check] CAUSE : le hub tourne en SYSTEM (spawné par "
                "LaForge-Master) ; py-spy a besoin d'ÉLÉVATION (admin + "
                "SeDebugPrivilege).\n[check] REMÈDE — PowerShell ADMIN (user) :\n"
                f'         & "{find_pyspy()}" dump --pid {pid}\n'
                f'         & "{find_pyspy()}" record --pid {pid} -d 30 -o hub.svg --nonblocking -s\n'
                "[check] (ou enregistrer une tâche SYSTEM one-shot — voir roadmap)."
            )
    return 0 if rc == 0 else 4


def cmd_stacks(frames: int) -> int:
    """Lit l'endpoint hub /debug/stacks (IRM async sans élévation) et affiche
    l'histogramme de coroutines (détecteur de pileup) + compteurs. Nécessite le
    réseau (lancer en trusted_script ; l'offline n'a pas de réseau sortant)."""
    import json
    import urllib.request
    url = f"http://127.0.0.1:8766/debug/stacks?frames={frames}"
    try:
        d = json.loads(urllib.request.urlopen(url, timeout=20).read())
    except Exception as exc:  # noqa: BLE001
        print(f"ABORT GET {url}: {exc}")
        return 2
    print(f"[stacks] n_tasks={d['n_tasks']} n_threads={d['n_threads']} ts={d['ts']}")
    print("[stacks] coro_histogram (pileup detector) :")
    for k, v in d["coro_histogram"].items():
        print(f"   {v:>3}x  {k}")
    busy = [t for t in d.get("threads", []) if "time.sleep" not in " ".join(t.get("stack", []))
            and "work_queue.get" not in " ".join(t.get("stack", []))
            and ".wait(" not in " ".join(t.get("stack", []))]
    print(f"[stacks] threads non-idle: {[t['name'] for t in busy]}")
    return 0


def cmd_dump(pid: int | None) -> int:
    pyspy = find_pyspy()
    pid = pid or get_hub_pid()
    if not (pyspy and pid):
        print(f"ABORT: pyspy={pyspy} pid={pid}")
        return 2
    os.makedirs(OUT_DIR, exist_ok=True)
    rc, out, err = _run([pyspy, "dump", "--pid", str(pid)], 30)
    if rc != 0:
        print(f"dump rc={rc}\n{err[:600]}")
        return rc
    path = os.path.join(OUT_DIR, f"hub_dump_{pid}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"[dump] {path} ({len(out)} bytes)")
    print(out[:2000])
    return 0


def cmd_record(pid: int | None, seconds: int) -> int:
    pyspy = find_pyspy()
    pid = pid or get_hub_pid()
    if not (pyspy and pid):
        print(f"ABORT: pyspy={pyspy} pid={pid}")
        return 2
    os.makedirs(OUT_DIR, exist_ok=True)
    out_svg = os.path.join(OUT_DIR, f"hub_flame_{pid}_{int(time.time())}.svg")
    cmd = [pyspy, "record", "--pid", str(pid), "--duration", str(seconds),
           "--rate", "100", "--nonblocking", "--subprocesses",
           "--output", out_svg, "--format", "flamegraph"]
    print(f"[record] {seconds}s sur PID {pid} (non-bloquant)...")
    rc, out, err = _run(cmd, seconds + 60)
    if rc == 0 and os.path.exists(out_svg):
        print(f"[record] flame graph -> {out_svg}")
        return 0
    print(f"[record] rc={rc}\n{(err or out)[:600]}")
    return rc or 5


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="py-spy profiler du hub Nokido")
    ap.add_argument("mode", choices=["check", "install", "dump", "record", "stacks"])
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--frames", type=int, default=6)
    args = ap.parse_args()
    if args.mode == "install":
        return cmd_install()
    if args.mode == "check":
        return cmd_check()
    if args.mode == "stacks":
        return cmd_stacks(args.frames)
    if args.mode == "dump":
        return cmd_dump(args.pid)
    return cmd_record(args.pid, args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
