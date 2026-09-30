"""
forge_python_runner.py — Pool de workers Python pre-warmed
==========================================================
Remplace `subprocess.run([python, "-c", code])` par un pool de workers
long-lived. Premier call a chaque worker = lent (cold Python + imports),
calls suivants = ~50-200ms (sys.modules cache).

Architecture :
  - N=3 workers spawnes au premier appel a get_runner()
  - Communication JSON-RPC sur stdin/stdout (cf forge_python_worker)
  - Queue thread-safe pour distribuer les calls
  - Restart automatique apres K=100 calls (eviter pollution etat)
  - Restart automatique sur crash
  - Timeout par call avec kill du worker bloque

Usage :
  from forge_python_runner import get_runner
  result = get_runner().run_code(code, timeout=30)
  # result = {"ok": bool, "stdout": str, "stderr": str, "elapsed_ms": float}

Async wrapper :
  loop = asyncio.get_event_loop()
  result = await loop.run_in_executor(None, get_runner().run_code, code)
"""

from __future__ import annotations

import json
import logging
import queue
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
_WORKER_PY = _ROOT / "forge_python_worker.py"


def _run_isolated(code: str, timeout: int = 30) -> dict:
    import tempfile, os, time, subprocess, sys

    # Racine DERIVEE du fichier, jamais en dur : le dossier du depot porte encore
    # l'ancien nom et doit pouvoir etre renomme sans casser le code (phase 0 du
    # renommage vers Nokido, 2026-08-10). Depuis app/, parent.parent = racine.
    ROOT = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    APP = os.path.join(ROOT, "app")
    TOOLS = os.path.join(ROOT, "tools")
    hdr = (
        "import sys,os"
        + chr(10)
        + "sys.path.insert(0,"
        + repr(APP)
        + ")"
        + chr(10)
        + "sys.path.insert(0,"
        + repr(TOOLS)
        + ")"
        + chr(10)
        + "os.chdir("
        + repr(ROOT)
        + ")"
        + chr(10)
    )
    run_tmp = os.path.join(ROOT, ".run_tmp")
    os.makedirs(run_tmp, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".py", prefix="run_", dir=run_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(hdr)
            f.write(code)
        t0 = time.perf_counter()
        # FIX: Gestion d'encodage robuste avec fallback
        try:
            # On tente d'abord utf-8 (standard)
            r = subprocess.run(
                [sys.executable, tmp],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
            )
        except UnicodeDecodeError:
            r = subprocess.run(
                [sys.executable, tmp],
                capture_output=True,
                text=True,
                encoding="cp1252",
                errors="replace",
                timeout=timeout,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
            )

        ms = round((time.perf_counter() - t0) * 1000, 2)
        out = (r.stdout + (r.stderr[:300] if r.stderr else "")).strip()
        return {"ok": r.returncode == 0, "stdout": out, "stderr": "", "elapsed_ms": ms}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"ERR:timeout {timeout}s", "elapsed_ms": timeout * 1000}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": "ERR:" + str(e)[:200], "elapsed_ms": 0}
    finally:
        try:
            os.unlink(tmp)
        except:
            pass


@dataclass
class _Worker:
    proc: subprocess.Popen
    worker_id: int = 0
    call_count: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class PythonRunner:
    """Pool de workers Python pre-warmed."""

    def __init__(
        self,
        n_workers: int = 3,
        restart_after: int = 100,
        default_timeout: float = 30.0,
        startup_timeout: float = 10.0,
    ) -> None:
        self._n = max(1, n_workers)
        self._restart_after = restart_after
        self._default_timeout = default_timeout
        self._startup_timeout = startup_timeout
        self._available: queue.Queue[_Worker] = queue.Queue()
        self._all: list[_Worker] = []
        self._mgmt_lock = threading.Lock()
        self._shutdown = False
        self._spawn_pool()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _spawn_pool(self) -> None:
        for i in range(self._n):
            try:
                w = self._spawn_worker()
                w.worker_id = i
                self._all.append(w)
                self._available.put(w)
            except Exception as e:
                logger.error(f"[PythonRunner] Spawn worker {i} failed: {e}")

    def _spawn_worker(self) -> _Worker:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(_WORKER_PY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            text=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        errors="replace")
        # Attendre le ready signal
        ready = self._read_with_timeout(proc, self._startup_timeout)
        if not ready or not ready.get("ready"):
            try:
                proc.kill()
            except Exception:
                pass
            raise RuntimeError(f"Worker init failed: {ready}")
        return _Worker(proc=proc)

    def _replace_worker(self, dead: _Worker) -> None:
        with self._mgmt_lock:
            try:
                dead.proc.kill()
            except Exception:
                pass
            try:
                self._all.remove(dead)
            except ValueError:
                pass
            try:
                w = self._spawn_worker()
                self._all.append(w)
                self._available.put(w)
            except Exception as e:
                logger.error(f"[PythonRunner] Replace worker failed: {e}")

    def shutdown(self) -> None:
        """Kill tous les workers proprement."""
        self._shutdown = True
        with self._mgmt_lock:
            for w in self._all:
                try:
                    w.proc.kill()
                except Exception:
                    pass
            self._all.clear()

    # ── IPC ──────────────────────────────────────────────────────────────────

    def _read_with_timeout(self, proc: subprocess.Popen, timeout: float) -> Optional[dict]:
        """
        Lit une ligne JSON depuis proc.stdout avec timeout.
        Retourne dict parse, ou None si timeout / EOF.
        """
        result_holder: dict = {}
        done = threading.Event()

        def reader() -> None:
            try:
                line = proc.stdout.readline()
                if line:
                    result_holder["line"] = line
            except Exception as e:
                result_holder["error"] = str(e)
            finally:
                done.set()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        if not done.wait(timeout):
            return None
        line = result_holder.get("line")
        if not line:
            return None
        try:
            return json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None

    # ── Public API ───────────────────────────────────────────────────────────

    def worker_status(self) -> list:
        """Retourne PID + etat de chaque worker du pool."""
        return [
            {"id": w.worker_id, "pid": w.proc.pid, "alive": w.proc.poll() is None, "calls": w.call_count}
            for w in self._all
        ]

    def run_code(self, code: str, timeout: Optional[float] = None) -> dict:
        """
        Execute `code` dans un worker du pool.

        Returns:
            {"ok": bool, "stdout": str, "stderr": str, "elapsed_ms": float,
             "worker_id": int, "queue_wait_ms": float}
        """
        if self._shutdown:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Runner shutdown",
                "elapsed_ms": 0.0,
            }
        if not isinstance(code, str):
            return {"ok": False, "stdout": "", "stderr": "code must be string", "elapsed_ms": 0.0}
        # BYPASS POOL: gros payload ou multiline -> mkstemp isole (solution historique v13.6)
        if len(code) > 400 or chr(10) in code:
            t = timeout if timeout is not None else self._default_timeout
            return _run_isolated(code, timeout=int(t))

        t = timeout if timeout is not None else self._default_timeout

        # Queue wait (si tous busy)
        t_wait = time.perf_counter()
        try:
            worker = self._available.get(timeout=t)
        except queue.Empty:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Aucun worker disponible (timeout queue)",
                "elapsed_ms": round((time.perf_counter() - t_wait) * 1000.0, 2),
            }
        wait_ms = round((time.perf_counter() - t_wait) * 1000.0, 2)

        # Verifier que le worker est encore vivant
        if worker.proc.poll() is not None:
            self._replace_worker(worker)
            # Recursive retry une fois
            return self.run_code(code, timeout=t)

        # Envoyer la requete
        with worker.lock:
            req_id = secrets.token_hex(6)
            req = {"id": req_id, "code": code, "timeout": int(t)}
            try:
                worker.proc.stdin.write(json.dumps(req, ensure_ascii=False).encode("utf-8") + b"\n")
                worker.proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._replace_worker(worker)
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": f"Worker pipe broken: {e}",
                    "elapsed_ms": 0.0,
                }

            # Lire la reponse avec timeout
            resp = self._read_with_timeout(worker.proc, t)

        if resp is None:
            # Timeout ou EOF — kill et restart
            logger.warning(f"[PythonRunner] Worker timeout/EOF apres {t}s — restart")
            self._replace_worker(worker)
            return {
                "ok": False,
                "stdout": "",
                "stderr": f"Worker timeout ({t}s) ou EOF — restart",
                "elapsed_ms": round(t * 1000.0, 2),
            }

        # Verifier id match (paranoia)
        if resp.get("id") != req_id:
            logger.warning(f"[PythonRunner] id mismatch: sent={req_id} got={resp.get('id')}")
            self._replace_worker(worker)
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Worker response id mismatch",
                "elapsed_ms": 0.0,
            }

        # Tracking call_count + restart auto
        worker.call_count += 1
        if worker.call_count >= self._restart_after:
            logger.info(f"[PythonRunner] Worker call_count={worker.call_count} — restart pour cleanup")
            self._replace_worker(worker)
        else:
            self._available.put(worker)

        resp["queue_wait_ms"] = wait_ms
        return resp

    def stats(self) -> dict:
        """Stats pool."""
        with self._mgmt_lock:
            alive = sum(1 for w in self._all if w.proc.poll() is None)
            return {
                "workers_total": len(self._all),
                "workers_alive": alive,
                "available_now": self._available.qsize(),
                "calls_per_worker": [w.call_count for w in self._all],
                "restart_after": self._restart_after,
            }


# ── Singleton ────────────────────────────────────────────────────────────────

_RUNNER: Optional[PythonRunner] = None
_RUNNER_LOCK = threading.Lock()


def get_runner() -> PythonRunner:
    """Singleton (lazy init au premier appel)."""
    global _RUNNER
    if _RUNNER is None:
        with _RUNNER_LOCK:
            if _RUNNER is None:
                _RUNNER = PythonRunner()
    return _RUNNER


def shutdown_runner() -> None:
    """A appeler au shutdown du hub."""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is not None:
            _RUNNER.shutdown()
            _RUNNER = None
