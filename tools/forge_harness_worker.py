"""
forge_harness_worker.py — fleet worker that drives real CLI agents via the harness.

Runs as a supervised service with runAs=interactive so it lives in the OWNER's
session — the only context where agent CLIs (codex/claude/gemini/agy) and their
login are reachable (the LaForgeTrusted/run_job tier can't see the owner profile).

Job protocol (drop a JSON file in sandbox/harness_jobs/):
  {"agent": "codex", "args": ["exec","--skip-git-repo-check","-s","read-only","-"],
   "send": "Reply: PONG", "eof": true, "until": "PONG", "timeout": 120, "screen": false}
No "until" -> drain until the process exits (EOF) or timeout = full answer.
Optional "cwd": working directory of the agent. Without it the harness falls back to
C:\tmp -- measured 2026-10-15: codex, asked to audit the live repo, landed in C:\tmp,
found several stale copies there and rightly refused to guess which one was live.
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
# 27/10 : un job Vibe dure jusqu'a ~28 min ; sans battement PENDANT le job, le pouls gelait alors que le worker
# travaillait (relance 09 h 14, job pris 09 h 17, pouls fige a 03 h 04) et l'executeur le lisait mort.
# Le battement reste borne par le watchdog de process_job (kill_tree a l'echeance) : il atteste un travail en cours.
_POULS_PENDANT_JOB_S = 30.0
# 27/10 : instance figee 73 min (vivante, MUETTE) -- `--watch` n'ecrivait rien, ses exceptions partaient en
# logging.debug sans handler, faulthandler (logboot) ne couvre que le crash natif. Le chien de garde vide les
# piles de TOUS les fils dans stderr (= journal logboot) si un tour ou un job depasse son delai sans rearmer.
_CHIEN_REPOS_S = 180.0
_CHIEN_MARGE_JOB_S = 300.0


def _bootstrap():
    app = str(ROOT / "app")
    if os.path.isdir(app) and app not in sys.path:
        sys.path.append(app)


def _heartbeat(**extra):
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

    beat_daemon("harness_worker", **extra)


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
    h = harness_for(agent, args=args, interactive=interactive, stdin_devnull=not has_send,
                    cwd=job.get("cwd") or None)
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
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_harness_worker.py', 118, exc_info=True)
        t.join(5)
        if not result:
            return {"ok": False, "error": "timeout/wedge -> killed",
                    "backend": getattr(h, "backend", "?")}
    return result or {"ok": False, "error": "no result"}


def _caviarder_resultat(res: dict) -> dict:
    """RED7 (19/10) : output/screen/error d'un agent dont l'environnement porte FORGE_TOKEN_<AGENT> passent par le
    redacteur EXISTANT (tools/forge_log_redact.redact) avant d'etre ecrits et relus par l'executeur."""
    try:
        from nokido_agent.tools.forge_log_redact import redact
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        from forge_log_redact import redact
    return {k: (redact(v) if k in ("output", "screen", "error") and isinstance(v, str) else v)
            for k, v in (res or {}).items()}


def _run_pending():
    JOBS.mkdir(parents=True, exist_ok=True)
    done = 0
    for jf in sorted(JOBS.glob("*.json")):
        if jf.name.endswith(".result.json"):
            continue
        marker = jf.with_suffix(".done")
        if marker.exists():
            continue
        fin = threading.Event()
        batteur = threading.Thread(target=_battre_tant_que, args=(fin, jf.stem), name="pouls-pendant-job",
                                   daemon=True)
        try:
            jf.with_suffix(".started").write_text("1", encoding="utf-8")
            job = json.loads(jf.read_text(encoding="utf-8"))
            try:
                _poser_veto(jf.stem, float(job.get("timeout") or 600) + _CHIEN_MARGE_JOB_S)
            except Exception:  # noqa: BLE001
                _log().warning("veto de sommeil non pose pour %s", jf.stem, exc_info=True)
            batteur.start()
            _armer_chien(float(job.get("timeout") or 600) + _CHIEN_MARGE_JOB_S)
            t0 = time.time()
            _log().info("job %s demarre (agent=%s, timeout=%s)", jf.stem, job.get("agent"), job.get("timeout"))
            res = process_job(job)
            _log().info("job %s fini en %.0f s (agent=%s, ok=%s)", jf.stem, time.time() - t0, job.get("agent"),
                        res.get("ok"))
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": repr(e)[:400]}
            _log().warning("job %s en echec : %s", jf.stem, repr(e)[:300], exc_info=True)
        finally:
            fin.set()
            if batteur.is_alive():
                batteur.join(timeout=5)
            try:
                _lever_veto()
            except Exception:  # noqa: BLE001
                _log().warning("veto de sommeil non leve (il expirera seul)", exc_info=True)
        jf.with_suffix(".result.json").write_text(json.dumps(_caviarder_resultat(res), ensure_ascii=False),
                                                  encoding="utf-8")
        marker.write_text("1", encoding="utf-8")
        done += 1
    return done


def _log():
    """Journal du worker sur stderr -- sous logboot, stderr EST le journal du service."""
    import logging
    lg = logging.getLogger("harness_worker")
    if not lg.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s harness_worker %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False
    return lg


_SERVICE = "NokidoHarnessWorker"
_VETO_RENOUVEAU_S = 600.0


def _poser_veto(nom, duree_s):
    """Veto de sommeil (forge_resource_manager) : un job en vol ne se fait pas endormir. 28/10 : worker
    `sleeping` pendant un job claude_api (RAM ~86 %), 34 min de delegations closes « non lance »."""
    _bootstrap()
    from nokido_agent.app.forge_resource_manager import poser_veto_sommeil
    poser_veto_sommeil(_SERVICE, "job harness en vol : %s" % nom, duree_s)


def _lever_veto():
    _bootstrap()
    from nokido_agent.app.forge_resource_manager import lever_veto_sommeil
    lever_veto_sommeil(_SERVICE)


def _battre_tant_que(fin, nom):
    """Pouls PENDANT un job, toutes les _POULS_PENDANT_JOB_S, et renouvellement du veto de sommeil (borne a
    30 min cote resource manager : un job plus long le perdrait). Une erreur est journalisee et le fil
    CONTINUE : mort en silence, il laissait perimer le pouls d'un job sain."""
    while not fin.wait(_POULS_PENDANT_JOB_S):
        try:
            _heartbeat(job_en_cours=nom)
        except Exception:  # noqa: BLE001
            _log().warning("pouls pendant job %s en echec (le fil continue)", nom, exc_info=True)
        try:
            _poser_veto(nom, _VETO_RENOUVEAU_S)
        except Exception:  # noqa: BLE001
            _log().warning("veto de sommeil non renouvele pour %s", nom, exc_info=True)


# Le service tourne en « journal sans pipe » : sys.stderr ne va nulle part. Les piles du chien de garde
# et d'un plantage fatal vont donc dans un FICHIER (28/10 : deux silences sans trace, 27/10 et 28/10).
_CHEMIN_CHIEN = Path(__file__).resolve().parents[1] / "logs" / "harness_worker_faulthandler.log"
_FICHIER_CHIEN = None


def _fichier_chien():
    global _FICHIER_CHIEN
    if _FICHIER_CHIEN is None or _FICHIER_CHIEN.closed:
        _CHEMIN_CHIEN.parent.mkdir(parents=True, exist_ok=True)
        _FICHIER_CHIEN = open(_CHEMIN_CHIEN, "a", encoding="utf-8")  # noqa: SIM115 (vit avec le processus)
    return _FICHIER_CHIEN


def _armer_chien(delai_s):
    """(Re)arme le vidage des piles de tous les fils si personne ne rearme avant `delai_s`."""
    import faulthandler
    faulthandler.cancel_dump_traceback_later()
    faulthandler.dump_traceback_later(delai_s, repeat=False, file=_fichier_chien())


def _watch(interval=3.0):
    _log().info("demarre pid=%d, tour=%.1f s, jobs=%s", os.getpid(), interval, JOBS)
    try:
        import faulthandler
        faulthandler.enable(file=_fichier_chien(), all_threads=True)  # plantage fatal : la pile reste lisible
    except Exception:  # noqa: BLE001
        _log().warning("faulthandler non arme sur fichier", exc_info=True)
    while True:
        _armer_chien(_CHIEN_REPOS_S)
        try:
            _run_pending()
        except Exception:  # noqa: BLE001
            _log().warning("tour de surveillance en echec", exc_info=True)
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
