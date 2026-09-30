# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_brain_client
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
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
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_brain_client.py — Client ZMQ pour le brain_worker
========================================================
Remplace run_ssh() par un appel via le tunnel SSH persistant du brain.

Protocole :
  REQ :5557  ssh_run {cmd, req_id, sudo}  → {ok, req_id, topic, pub_port}
  SUB :5558  topic b"ssh:<req_id>"        → chunks {type, data, done, exit}

Usage (TUI) :
  from forge_brain_client import brain_ssh_run
  out, err, code = await brain_ssh_run("uptime")

  # Ou avec callback pour affichage temps réel :
  await brain_ssh_run("journalctl -n 100", on_chunk=lambda c: print(c))
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

REP_PORT = 5557
PUB_PORT = 5558
_TIMEOUT = 15.0  # secondes max pour recevoir done=True


def _zmq_req(payload: dict, timeout_ms: int = 2000) -> Optional[dict]:
    """Envoi REQ/REP synchrone — thread-safe, crée son propre contexte."""
    try:
        import zmq

        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        sock.connect(f"tcp://127.0.0.1:{REP_PORT}")
        try:
            # Frontière ZMQ : sérialise le trace_id dans tout payload brain_worker.
            try:
                from nokido_agent.app.forge_trace_context import get_trace_id

                payload.setdefault("trace_id", get_trace_id())
            except Exception:
                pass
            sock.send(json.dumps(payload, ensure_ascii=False).encode())
            raw = sock.recv()
            return json.loads(raw.decode())
        finally:
            sock.close()
            ctx.term()
    except Exception as e:
        logger.debug(f"[brain_client] REQ: {e}")
        return None


async def brain_ssh_run(
    cmd: str,
    sudo: bool = False,
    timeout: float = _TIMEOUT,
    on_chunk: Optional[Callable[[str], None]] = None,
) -> Tuple[str, str, int]:
    """
    Exécute cmd via le tunnel SSH persistant du brain_worker.
    Retourne (stdout, stderr, exit_code) comme run_ssh().
    Si on_chunk est fourni, il est appelé avec chaque chunk stdout en temps réel.
    """
    req_id = f"tui_{uuid.uuid4().hex[:8]}"

    # 1. Envoyer la commande au brain (REQ sync dans un executor)
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(None, _zmq_req, {"cmd": "ssh_run", "cmd": cmd, "req_id": req_id, "sudo": sudo})  # noqa: F601

    if not resp or not resp.get("ok"):
        err = resp.get("error", "brain_worker non disponible") if resp else "brain_worker non disponible"
        logger.warning(f"[brain_ssh] {err}")
        # Fallback sur connexion directe si brain indisponible
        return await _direct_ssh_fallback(cmd, sudo, timeout)

    topic = f"ssh:{req_id}".encode()

    # 2. Souscrire au topic PUB et collecter les chunks
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    exit_code = -1

    try:
        import zmq
        import zmq.asyncio as zaio

        ctx = zaio.Context()
        sub = ctx.socket(zmq.SUB)
        sub.setsockopt(zmq.LINGER, 0)
        sub.setsockopt(zmq.RCVTIMEO, int(timeout * 1000))
        sub.connect(f"tcp://127.0.0.1:{PUB_PORT}")
        sub.subscribe(topic)

        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if await sub.poll(timeout=500):
                    frames = await sub.recv_multipart(zmq.NOBLOCK)
                    if len(frames) < 2:
                        continue
                    payload = json.loads(frames[1].decode())
                    ptype = payload.get("type", "")

                    if ptype == "stdout":
                        chunk = payload.get("data", "")
                        stdout_parts.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)

                    elif ptype == "stderr":
                        stderr_parts.append(payload.get("data", ""))

                    elif ptype in ("done", "error"):
                        exit_code = payload.get("exit", -1 if ptype == "error" else 0)
                        if ptype == "error":
                            stderr_parts.append(payload.get("msg", ""))
                        break
        finally:
            sub.close()
            ctx.term()

    except ImportError:
        return await _direct_ssh_fallback(cmd, sudo, timeout)
    except Exception as e:
        logger.warning(f"[brain_ssh] SUB error: {e}")
        return await _direct_ssh_fallback(cmd, sudo, timeout)

    return "".join(stdout_parts), "".join(stderr_parts), exit_code


async def _direct_ssh_fallback(cmd: str, sudo: bool, timeout: float) -> Tuple[str, str, int]:
    """Fallback : connexion SSH directe si brain_worker indisponible."""
    try:
        import sys as _sys

        for mn in ("__main__", "Nokido", "app.Nokido"):
            m = _sys.modules.get(mn)
            if m and hasattr(m, "run_ssh"):
                return await m.run_ssh(cmd, sudo, int(timeout))
    except Exception as e:
        logger.debug(f"[ssh_fallback] {e}")
    return "", f"SSH indisponible: {cmd}", -1


def brain_ssh_available() -> bool:
    """Vérifie rapidement si le brain répond et a SSH connecté."""
    resp = _zmq_req({"cmd": "ssh_status"}, timeout_ms=500)
    return bool(resp and resp.get("ok") and resp.get("data", {}).get("connected"))
