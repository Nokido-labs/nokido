# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-05 | VER:v1_gemini_cli_daemon
#FORGE:[score:88|agent:claude-sonnet-4-6|temp:0.00|risk:0.20|ast:OK|test:KO|lint:OK|color:GREEN|attempt:1]

tools/gemini_cli_daemon.py — Daemon autonome Gemini CLI OAuth (Pattern D3)
===========================================================================

Différence avec gemini_poll_daemon.py (Pattern D2) :
  D2 : poll Hub /messages → appelle API Gemini REST (GEMINI_API_KEY, quota-limité)
  D3 : poll agent_messages SQLite → appelle gemini.cmd CLI (OAuth Google One, sans quota)

Architecture :
  1. Poll agent_messages WHERE to_agent='agt_gemini_cli' AND status='unread' toutes les N sec
  2. Pour chaque tâche : subprocess gemini.cmd -p <prompt> (CREATE_NO_WINDOW, timeout=120s)
  3. Écrit résultat dans agent_messages (from=agt_gemini_cli, to=<sender>)
  4. Marque la tâche originale 'read'
  5. Hub pickup résultat au prochain /messages check

Config env :
  GEMINI_CLI_POLL_INTERVAL  : secondes entre polls (défaut 15)
  GEMINI_CLI_BIN            : chemin gemini.cmd (défaut systemprofile npm)
  (base des messages)       : agent_messages suit forge_db_path.m2m_path(), interrupteur sandbox/m2m.switch
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:88|agent:claude-sonnet-4-6|temp:0.00|risk:0.20|ast:OK|test:KO|lint:OK|color:GREEN|attempt:1]"

import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

_ROOT_EARLY = Path(__file__).resolve().parent.parent
(_ROOT_EARLY / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GeminiCLI-D3] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            _ROOT_EARLY / "logs" / "gemini_cli_daemon.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("GeminiCLI.Daemon")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch
DB_PATH = Path(m2m_path())
POLL_INTERVAL = int(os.environ.get("GEMINI_CLI_POLL_INTERVAL", "15"))
GEMINI_BIN = os.environ.get(
    "GEMINI_CLI_BIN",
    r"C:\WINDOWS\system32\config\systemprofile\AppData\Roaming\npm\gemini.cmd",
)
AGENT_ID = "agt_gemini_cli"
MAX_PROMPT_LEN = 8000
CLI_TIMEOUT = 120

_stop = False


def _signal_handler(sig, frame):
    global _stop
    logger.info(f"Signal {sig} reçu — arrêt propre")
    _stop = True


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_messages (
            id TEXT PRIMARY KEY,
            from_agent TEXT,
            to_agent TEXT,
            correlation_id TEXT,
            method TEXT,
            payload TEXT,
            result TEXT,
            status TEXT DEFAULT 'unread',
            created_at TEXT,
            read_at TEXT
        )
    """)
    conn.commit()


def _fetch_pending(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT * FROM agent_messages WHERE to_agent=? AND status='unread' ORDER BY created_at LIMIT 5",
        (AGENT_ID,),
    ).fetchall()


def _mark_read(conn: sqlite3.Connection, msg_id: str) -> None:
    conn.execute(
        "UPDATE agent_messages SET status='read', read_at=? WHERE id=?",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), msg_id),
    )
    conn.commit()


def _write_result(conn: sqlite3.Connection, original: sqlite3.Row, result_text: str) -> None:
    payload = {}
    try:
        payload = json.loads(original["payload"] or "{}")
    except Exception:
        pass

    conn.execute(
        """INSERT OR REPLACE INTO agent_messages
           (id, from_agent, to_agent, correlation_id, method, payload, result, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            str(uuid.uuid4()),
            AGENT_ID,
            original["from_agent"] or "agt_claude",
            original["id"],  # corr_id = original msg id
            "task.result",
            json.dumps({"original_method": original["method"]}, ensure_ascii=False),
            result_text[:4000],
            "unread",
            time.strftime("%Y-%m-%dT%H:%M:%S"),
        ),
    )
    conn.commit()


def _call_gemini_cli(prompt: str) -> str:
    """Appelle gemini.cmd sans hijacker le terminal parent."""
    if not os.path.exists(GEMINI_BIN):
        return f"[ERR] gemini.cmd not found: {GEMINI_BIN}"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            [GEMINI_BIN, "-p", prompt[:MAX_PROMPT_LEN]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT,
            creationflags=flags,
        )
        return r.stdout.strip() or r.stderr.strip()[:500] or "[EMPTY]"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] gemini.cmd exceeded {CLI_TIMEOUT}s"
    except Exception as e:
        return f"[ERR] {e}"


def _process_message(conn: sqlite3.Connection, msg: sqlite3.Row) -> None:
    payload = {}
    try:
        payload = json.loads(msg["payload"] or "{}")
    except Exception:
        pass

    prompt = payload.get("prompt") or payload.get("task") or payload.get("message") or str(payload)
    logger.info(f"Task from={msg['from_agent']} method={msg['method']} prompt={prompt[:80]}...")

    result = _call_gemini_cli(prompt)
    logger.info(f"Result ({len(result)} chars): {result[:120]}")

    _write_result(conn, msg, result)
    _mark_read(conn, msg["id"])


def run_daemon() -> None:
    logger.info(f"Gemini CLI Daemon D3 démarré — poll={POLL_INTERVAL}s bin={GEMINI_BIN}")
    logger.info(f"DB: {DB_PATH} | agent_id={AGENT_ID}")

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    if not os.path.exists(GEMINI_BIN):
        logger.error(f"gemini.cmd introuvable: {GEMINI_BIN} — daemon en attente passive")

    while not _stop:
        try:
            conn = _db()
            _ensure_schema(conn)
            pending = _fetch_pending(conn)
            for msg in pending:
                if _stop:
                    break
                try:
                    _process_message(conn, msg)
                except Exception as e:
                    logger.error(f"Erreur message {msg['id']}: {e}")
                    _mark_read(conn, msg["id"])
            conn.close()
        except Exception as e:
            logger.error(f"DB error: {e}")

        for _ in range(POLL_INTERVAL):
            if _stop:
                break
            time.sleep(1)

    logger.info("Daemon arrêté proprement.")


if __name__ == "__main__":
    run_daemon()
