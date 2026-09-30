"""
forge_harness_worker.py — fleet worker that drives real CLI agents via the harness.

Runs as a supervised service with runAs=interactive so it lives in the OWNER's
session — the only context where agent CLIs (codex/claude/gemini/agy) and their
login are reachable (the LaForgeTrusted/run_job tier can't see the owner profile).

Job protocol (drop a JSON file in sandbox/harness_jobs/):
  {"agent": "codex", "args": ["exec","--skip-git-repo-check","-s","read-only","-"],
   "send": "Reply: PONG", "eof": true, "until": "PONG", "timeout": 120, "screen": false}
No "until" -> drain until the process exits (EOF) or timeout = full answer.
No "send" -> stdin is DEVNULL (the CLI gets EOF immediately = no hang waiting input).
Each job runs under a WATCHDOG (own thread + hard wall-clock deadline) and a
kill-tree on overrun, so a hanging agent CANNOT wedge the worker loop.
The worker writes <id>.result.json, then marks <id>.done + heartbeat.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "locomoteur/fleet runner, pilote les CLI agents via le harness"  # declare le 2026-09-06 (audit : REGULE sans organe)

import json
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "sandbox" / "harness_jobs"
HEARTBEAT = ROOT / "sandbox" / "harness_worker.heartbeat"


def _bootstrap():
    app = str(ROOT / "app")
    if os.path.isdir(app) and app not in sys.path:
        sys.path.append(app)


def _heartbeat():
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`). Ce pouls n'etait pas
    # du JSON mais une date ISO NUE : l'audit le comptait ILLISIBLE (mesure du
    # 2026-08-25) et il ne portait aucun pid.
    #
    # L'amorce est LOCALE et non deleguee a un appel anterieur : `_bootstrap` est
    # idempotent, l'appeler ici coute une comparaison et rend le pouls independant
    # de l'ordre d'appel. Deux daemons sont morts le 2026-09-05 d'une amorce qui
    # vivait ailleurs dans le fichier (`forge_docker_keeper`, `forge_tdr_sentinel`).
    _bootstrap()
    from nokido_agent.app.forge_heartbeat import beat_daemon

    beat_daemon("harness_worker")


def process_job(job):
    """Drive one agent job via the harness, under a watchdog. Returns
    {ok, output, screen, backend} or {ok: False, error}. A hanging agent is
    kill-tree'd at the deadline so the worker loop never wedges."""
    _bootstrap()
    from nokido_agent.app.forge_cli_harness import harness_for, kill_tree
    agent = job.get("agent", "")
    args = job.get("args") or []
    interactive = job.get("mode") == "interactive"
    has_send = job.get("send") is not None
    timeout = float(job.get("timeout", 120))
    h = harness_for(agent, args=args, interactive=interactive, stdin_devnull=not has_send)
    result = {}

    def _drive():
        h.start()
        try:
            if job.get("settle"):
                time.sleep(float(job["settle"]))
                h.read(0.3)
            if has_send:
                h.send(str(job["send"]))
            if job.get("eof"):
                h.send_eof()
            marker = job.get("until")
            if marker:
                out = h.read_until(marker, timeout=timeout)
            else:
                out = ""
                _end = time.time() + timeout
                while time.time() < _end:
                    chunk = h.read(1.0)
                    out += chunk
                    if not chunk and not h.alive():
                        break
            scr = h.screen() if job.get("screen") else ""
            result.update({"ok": True, "output": out, "screen": scr, "backend": h.backend})
        except Exception as exc:  # noqa: BLE001
            result.update({"ok": False, "error": repr(exc)[:300], "backend": getattr(h, "backend", "?")})
        finally:
            h.stop()

    t = threading.Thread(target=_drive, daemon=True)
    t.start()
    t.join(timeout + 15)  # hard wall-clock: job timeout + grace for start/stop
    if t.is_alive():
        # Wedged: kill the agent process tree so the drive thread unblocks; the
        # worker loop continues regardless.
        try:
            kill_tree(getattr(h._b.proc, "pid", None))
        except Exception:  # noqa: BLE001
            pass
        t.join(5)
        if not result:
            return {"ok": False, "error": "timeout/wedge -> killed",
                    "backend": getattr(h, "backend", "?")}
    return result or {"ok": False, "error": "no result"}


def _run_pending():
    JOBS.mkdir(parents=True, exist_ok=True)
    done = 0
    for jf in sorted(JOBS.glob("*.json")):
        if jf.name.endswith(".result.json"):
            continue
        marker = jf.with_suffix(".done")
        if marker.exists():
            continue
        try:
            job = json.loads(jf.read_text(encoding="utf-8"))
            res = process_job(job)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": repr(e)[:400]}
        jf.with_suffix(".result.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        marker.write_text("1", encoding="utf-8")
        done += 1
    return done


def _watch(interval=3.0):
    while True:
        try:
            _run_pending()
        except Exception:  # noqa: BLE001
            pass
        _heartbeat()
        time.sleep(interval)


def _selftest():
    """Drive a deterministic fake agent (cmd.exe) through the job pipeline."""
    JOBS.mkdir(parents=True, exist_ok=True)
    job = {"agent": "cmd", "args": ["/q", "/k"], "settle": 0.4,
           "send": "echo WORKER_OK_77", "until": "_77", "timeout": 8, "screen": True}
    res = process_job(job)
    ok = res.get("ok") and "_77" in (res.get("output") or "")
    # wedge guard: a hanging cmd (no eof, marker never appears) must NOT wedge —
    # returns within timeout+grace, killed.
    t0 = time.time()
    hang = process_job({"agent": "cmd", "args": ["/k"], "send": "rem busy",
                        "until": "NEVER_XYZ", "timeout": 3})
    elapsed = time.time() - t0
    no_wedge = elapsed < 30
    print(json.dumps({"backend": res.get("backend"), "ok": ok,
                      "screen_marker": "WORKER_OK_77" in (res.get("screen") or ""),
                      "wedge_guard_ok": no_wedge, "hang_elapsed_s": round(elapsed, 1),
                      "pass": ok and no_wedge}, ensure_ascii=False))
    return 0 if (ok and no_wedge) else 1


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "--watch"
    if arg == "--selftest":
        raise SystemExit(_selftest())
    if arg == "--once":
        print(json.dumps({"processed": _run_pending()}))
        return
    iv = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    _watch(iv)


if __name__ == "__main__":
    main()
