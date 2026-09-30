# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_batch_forge_runner_fix_bridge
#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]
CONTRAINTE: fix bridge import dans status() - bug bloquant decouvert lors session 2026-04-24 orchestration Gemini
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]"
"""
forge_runner.py — Spawn détaché via os.spawnl / Popen sans wait
================================================================
Protocole :
  1. spawn(code)          → task_id  (<1ms, aucun I/O disque)
  2. live_bridge.task_new → slot mmap alloué
  3. os.spawnl P_NOWAIT   → process enfant détaché immédiatement
  4. Enfant               → écrit résultat dans live_bridge.task_set
  5. Hub/MCP              → bridge.task_get(tid) depuis mmap

Le MCP stdio ne fait JAMAIS .wait() ni .communicate().
Zéro fichier temp : le code est passé via variable d'environnement
(max 32KB, suffisant pour toute tâche Nokido).

FIX 2026-04-24: import bridge top-level pour que status() fonctionne.
Auparavant bridge etait importe localement dans spawn() uniquement,
provoquant NameError sur chaque appel a status().
"""


import os
import sys
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PYTHON = sys.executable

# Import bridge top-level (FIX 2026-04-24) - necessaire pour status()
# Avant, bridge etait importe localement dans spawn() uniquement, ce qui
# rendait status() non fonctionnel car il reference `bridge` sans import.
try:
    from nokido_agent.app.live_bridge import bridge
except ImportError:
    # Fallback : on essaie aussi depuis app/ en cas de path non injecte
    _app_path = _ROOT / "app"
    if str(_app_path) not in sys.path:
        sys.path.insert(0, str(_app_path))
    from nokido_agent.app.live_bridge import bridge

_WIN = sys.platform == "win32"
_DETACH = 0
if _WIN:
    _DETACH = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

# Template minimal — chargé une fois, pas de fichier temp
_RUNNER_TMPL = r"""
import sys, os, time, base64
sys.path.insert(0, r"__APP__")
sys.path.insert(0, r"__TOOLS__")
_ef = r"__ENV__"
if os.path.exists(_ef):
    for _l in open(_ef, encoding="utf-8").read().splitlines():
        _l = _l.strip()
        if "=" in _l and not _l.startswith("#"):
            _k,_,_v = _l.partition("="); _v=_v.split("#")[0].strip()
            if _k.strip() and _v: os.environ.setdefault(_k.strip(), _v)
from live_bridge import bridge as _br, ST_RUN, ST_OK, ST_ERR, ST_TMO
from pathlib import Path
ROOT = Path(r"__ROOT__")
_tid = os.environ.get("_LAFORGE_TID","unknown")
_br.task_set(_tid, ST_RUN)
_t0 = time.monotonic()
try:
    # forge_db `db`/`db_evt` étaient l'ancienne API (avant refactor
    # get_conn/get_conn_readonly). Garder import optionnel pour les
    # vieux scripts qui les attendent en globals exec.
    try:
        from forge_db import db, db_evt   # type: ignore[attr-defined]
    except Exception:
        db, db_evt = None, None
    import json, sqlite3, threading, subprocess
    _code = base64.b64decode(os.environ["_LAFORGE_CODE"]).decode("utf-8")
    _result = None
    exec(_code, {
        "__builtins__": __import__("builtins"),
        "ROOT": ROOT, "Path": Path, "os": os, "sys": sys,
        "time": time, "json": json, "sqlite3": sqlite3,
        "threading": threading, "subprocess": subprocess,
        "db": db, "db_evt": db_evt,
        "bridge": _br,
    })
    _dur = int((time.monotonic()-_t0)*1000)
    _out = str(_result)[:63] if _result is not None else "OK"
    _br.task_set(_tid, ST_OK, result=_out, dur_ms=_dur)
except Exception as _e:
    _dur = int((time.monotonic()-_t0)*1000)
    _br.task_set(_tid, ST_ERR, result=f"{type(_e).__name__}:{str(_e)[:50]}", dur_ms=_dur)
"""


def spawn(code: str, prefix: str = "task", timeout_s: int = 60) -> str:
    """
    Lance `code` dans un process totalement détaché.
    Retourne task_id immédiatement (<1ms).
    Aucun fichier temp, aucun .wait().
    """
    tid = bridge.task_new(prefix)

    # Encoder le code en base64 pour le passer via env (évite les fichiers)
    import base64

    code_b64 = base64.b64encode(code.encode("utf-8")).decode()

    # Construire le script runner en mémoire (stdin pipe)
    runner = (
        _RUNNER_TMPL.replace("__APP__", str(_ROOT / "app"))
        .replace("__TOOLS__", str(_ROOT / "tools"))
        .replace("__ENV__", str(_ROOT / "Nokido.env"))
        .replace("__ROOT__", str(_ROOT))
    )

    env = {**os.environ, "_LAFORGE_TID": tid, "_LAFORGE_CODE": code_b64}

    # Popen avec stdin=PIPE — on envoie le script via stdin, zéro fichier
    proc = subprocess.Popen(
        [_PYTHON, "-c", runner],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=str(_ROOT),
        close_fds=True,
        creationflags=_DETACH,
    )

    # Timeout watchdog dans un thread daemon (ne bloque pas le MCP)
    def _watch(p=proc, t=tid, to=timeout_s) -> None:
        """Watch.

        Args:
            p: Description.
            t: Description.
            to: Description.
        """
        try:
            p.wait(timeout=to)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                from nokido_agent.app.live_bridge import bridge as _br, ST_TMO

                _br.task_set(t, ST_TMO, result="timeout")
            except Exception:
                pass

    import threading

    threading.Thread(target=_watch, daemon=True, name=f"W-{tid}").start()
    return tid


def status(task_id: str) -> dict:
    """
    Lit le statut depuis live_bridge (mmap, zéro I/O disque).

    FIX 2026-04-24: bridge est maintenant importe au top-level, donc
    cette fonction fonctionne. Auparavant elle retournait systematiquement
    "ERR:name 'bridge' is not defined".
    """
    try:
        d = bridge.task_get(task_id)
        return d or {"id": task_id, "status": "unknown"}
    except Exception as e:
        return {"id": task_id, "status": f"ERR:{e}"}


# Import bootstrap au niveau module pour SESSION_STICKY_NS_V1
try:
    from nokido_agent.app import bootstrap as _bootstrap_mod

    _run_code_fn = _bootstrap_mod.run_code
except Exception:
    _bootstrap_mod = None
    _run_code_fn = None


def run_sync(code: str, timeout_s: int = 15) -> str:
    """
    Exécution synchrone dans le même process (bootstrap).
    SESSION_STICKY_NS_V1 : namespace persistant entre appels.
    """
    try:
        fn = _run_code_fn or __import__("bootstrap").run_code
        return fn(code)
    except Exception as e:
        return f"ERR:{type(e).__name__}:{str(e)[:120]}"
